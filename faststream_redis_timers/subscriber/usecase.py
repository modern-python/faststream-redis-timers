import logging
import time
import typing
from collections.abc import Sequence
from contextlib import suppress

import anyio
from faststream._internal.endpoint.subscriber import SubscriberSpecification, SubscriberUsecase
from faststream._internal.endpoint.subscriber.mixins import TasksMixin
from faststream.specification.asyncapi.utils import resolve_payloads
from faststream.specification.schema import Message, Operation, SubscriberSpec
from redis.asyncio.lock import Lock

from faststream_redis_timers.message import TimerMessage
from faststream_redis_timers.parser.parser import TimerParser
from faststream_redis_timers.subscriber.config import TimersSubscriberConfig, TimersSubscriberSpecificationConfig


if typing.TYPE_CHECKING:
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
            with anyio.fail_after(3.0):
                await start_signal.wait()
        else:
            start_signal.set()

    async def _consume(self, client: "Redis[bytes]", *, start_signal: anyio.Event) -> None:
        with suppress(Exception):
            if await client.ping():
                start_signal.set()

        connected = True
        while self.running:
            try:
                await self._get_msgs(client)
            except Exception as e:  # noqa: BLE001  # pragma: no cover
                self._log(
                    log_level=logging.ERROR,
                    message="Message fetch error",
                    exc_info=e,
                )
                if connected:
                    connected = False
                await anyio.sleep(5)
            else:
                if not connected:  # pragma: no cover
                    connected = True
            finally:
                if not start_signal.is_set():
                    with suppress(Exception):  # pragma: no cover
                        start_signal.set()

    async def _get_msgs(self, client: "Redis[bytes]") -> None:
        now = time.time()
        timer_ids: list[bytes] = await client.zrangebyscore(self._config.topic_timeline_key, "-inf", now)

        if not timer_ids:
            await anyio.sleep(self._config.timer_sub.polling_interval)
            return

        count = 0
        for raw_id in timer_ids:
            if count >= self._config.timer_sub.max_concurrent:
                break

            timer_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            lock = Lock(
                client,
                f"{self._config.lock_prefix}{self._config.full_topic}:{timer_id}",
                timeout=self._config.timer_sub.lock_ttl,
                blocking=False,
            )

            acquired = await lock.acquire()
            if not acquired:
                continue

            try:
                raw_payload: bytes | None = await client.hget(self._config.topic_payloads_key, timer_id)
                if raw_payload is None:
                    await client.zrem(self._config.topic_timeline_key, timer_id)
                    continue

                async with client.pipeline(transaction=True) as pipe:
                    pipe.zrem(self._config.topic_timeline_key, timer_id)
                    pipe.hdel(self._config.topic_payloads_key, timer_id)
                    await pipe.execute()

                msg = TimerMessage(
                    type="timer",
                    channel=self._config.full_topic,
                    timer_id=timer_id,
                    data=raw_payload,
                )
                await self.consume(msg)
                count += 1
            finally:
                await lock.release()

    @typing.override
    async def stop(self) -> None:
        with anyio.move_on_after(self._outer_config.graceful_timeout):
            await super().stop()

    @typing.override
    async def get_one(self, *, timeout: float = 5.0) -> typing.NoReturn:  # noqa: ASYNC109
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
