import logging
import random
import time
import typing
from collections.abc import Sequence
from contextlib import suppress

import anyio
from faststream._internal.endpoint.subscriber import SubscriberSpecification, SubscriberUsecase
from faststream._internal.endpoint.subscriber.mixins import TasksMixin
from faststream.specification.asyncapi.utils import resolve_payloads
from faststream.specification.schema import Message, Operation, SubscriberSpec

from faststream_redis_timers.message import TimerMessage
from faststream_redis_timers.parser.parser import TimerParser
from faststream_redis_timers.subscriber.config import TimersSubscriberConfig, TimersSubscriberSpecificationConfig
from faststream_redis_timers.subscriber.lua import CLAIM_LUA, CLAIM_SHA, eval_cached


# Cap exponent so 2 ** count cannot overflow into useless float ops once delay is at the cap.
_BACKOFF_EXP_CAP = 30


if typing.TYPE_CHECKING:
    from anyio.abc import TaskGroup
    from faststream._internal.endpoint.publisher import PublisherProto
    from faststream._internal.endpoint.subscriber.call_item import CallsCollection
    from faststream.message import StreamMessage
    from redis.asyncio import Redis

    from faststream_redis_timers.configs import TimersBrokerConfig


class TimersSubscriberSpecification(SubscriberSpecification["TimersBrokerConfig", TimersSubscriberSpecificationConfig]):
    @property
    def name(self) -> str:
        prefix = getattr(self._outer_config, "prefix", "")
        return f"{prefix}{self.config.topic}:{self.call_name}"

    def get_schema(self) -> dict[str, SubscriberSpec]:
        return {
            self.name: SubscriberSpec(
                description=self.description,
                operation=Operation(
                    message=Message(
                        title=f"{self.name}:Message",
                        payload=resolve_payloads(self.get_payloads()),
                    ),
                    bindings=None,
                ),
                bindings=None,
            )
        }


class TimersSubscriber(TasksMixin, SubscriberUsecase[TimerMessage]):
    _outer_config: "TimersBrokerConfig"

    def __init__(
        self,
        config: TimersSubscriberConfig,
        specification: TimersSubscriberSpecification,
        calls: "CallsCollection[typing.Any]",
    ) -> None:
        timer_parser = TimerParser(config)
        config.parser = timer_parser.parse_message
        config.decoder = timer_parser.decode_message
        super().__init__(config, specification, calls)
        self._config = config

    @property
    def _client(self) -> "Redis[bytes]":
        return self._outer_config.connection.client

    @typing.override
    async def start(self) -> None:
        await super().start()
        self._post_start()

        start_signal = anyio.Event()
        if self.calls:
            self.add_task(self._consume, (self._client,), {"start_signal": start_signal})
            with anyio.fail_after(self._outer_config.start_timeout):
                await start_signal.wait()
        else:
            start_signal.set()

    async def _consume(self, client: "Redis[bytes]", *, start_signal: anyio.Event) -> None:
        with suppress(Exception):
            if await client.ping():
                start_signal.set()

        base = self._config.timer_sub.polling_interval
        max_idle = self._config.timer_sub.max_polling_interval
        idle_count = 0
        error_attempt = 0

        limiter = anyio.CapacityLimiter(self._config.timer_sub.max_concurrent)
        async with anyio.create_task_group() as tg:
            while self.running:
                try:
                    fetched = await self._get_msgs(client, tg, limiter)
                except Exception as e:  # noqa: BLE001  # pragma: no cover
                    self._log(log_level=logging.ERROR, message="Message fetch error", exc_info=e)
                    error_attempt = min(error_attempt + 1, _BACKOFF_EXP_CAP)
                    delay = min(2.0 ** (error_attempt - 1) * random.uniform(0.5, 1.5), 30.0)  # noqa: S311
                    await anyio.sleep(delay)
                else:
                    error_attempt = 0
                    if fetched > 0:
                        idle_count = 0
                    elif fetched == 0:
                        idle_count = min(idle_count + 1, _BACKOFF_EXP_CAP)
                        delay = min(base * (2.0 ** (idle_count - 1)) * random.uniform(0.5, 1.5), max_idle)  # noqa: S311
                        await anyio.sleep(delay)
                    else:
                        # back-pressured (limiter saturated): yield briefly without growing idle counter
                        await anyio.sleep(base)
                finally:
                    if not start_signal.is_set():
                        start_signal.set()

    async def _get_msgs(
        self,
        client: "Redis[bytes]",
        tg: "TaskGroup",
        limiter: anyio.CapacityLimiter,
    ) -> int:
        """Fetch and dispatch due timers. Return count fetched, or -1 if back-pressured."""
        stats = limiter.statistics()
        free = int(limiter.total_tokens) - int(stats.borrowed_tokens) - int(stats.tasks_waiting)
        if free <= 0:
            return -1

        now = time.time()
        timer_ids: list[bytes] = await client.zrangebyscore(
            self._config.topic_timeline_key, "-inf", now, start=0, num=free
        )
        if not timer_ids:
            return 0

        self._log(log_level=logging.DEBUG, message=f"Fetched {len(timer_ids)} due timers")
        lease_ttl = self._config.timer_sub.lease_ttl
        for raw_id in timer_ids:
            tg.start_soon(self._claim_and_consume, raw_id, lease_ttl, limiter)
        return len(timer_ids)

    async def _claim_and_consume(
        self,
        raw_id: bytes | str,
        lease_ttl: int,
        limiter: anyio.CapacityLimiter,
    ) -> None:
        try:
            async with limiter:
                now = time.time()
                claim_score = now + lease_ttl
                timer_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
                raw_payload: bytes | None = await eval_cached(
                    self._client,
                    CLAIM_LUA,
                    CLAIM_SHA,
                    2,
                    self._config.topic_timeline_key,
                    self._config.topic_payloads_key,
                    timer_id,
                    now,
                    claim_score,
                )
                if raw_payload is None:
                    self._log(
                        log_level=logging.DEBUG,
                        message=f"Timer {timer_id!r} claim contested (already leased or canceled)",
                    )
                    return
                msg = TimerMessage(
                    type="timer",
                    channel=self._config.full_topic,
                    timer_id=timer_id,
                    data=raw_payload,
                )
                self._log(log_level=logging.DEBUG, message=f"Timer {timer_id!r} delivered to handler")
                await self.consume(msg)
        except Exception as e:  # noqa: BLE001  # pragma: no cover
            self._log(
                log_level=logging.ERROR,
                message=f"Timer {raw_id!r} consume error",
                exc_info=e,
            )

    @typing.override
    async def stop(self) -> None:
        with anyio.move_on_after(self._outer_config.graceful_timeout):
            await super().stop()

    @typing.override
    async def get_one(self, *, timeout: float = 5.0) -> typing.NoReturn:
        msg = "TimersBroker does not support get_one()"
        raise NotImplementedError(msg)

    def _make_response_publisher(
        self,
        message: "StreamMessage[TimerMessage]",  # noqa: ARG002
    ) -> Sequence["PublisherProto"]:
        return ()

    def get_log_context(
        self,
        message: "StreamMessage[TimerMessage] | None",
    ) -> dict[str, str]:
        if message and message.raw_message:
            return {
                "channel": message.raw_message.get("channel", ""),
                "message_id": getattr(message, "message_id", ""),
            }
        return {
            "channel": self._config.timer_sub.topic,
            "message_id": "",
        }
