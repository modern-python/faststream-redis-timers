import logging
import time
from collections.abc import Sequence
from contextlib import suppress
from typing import TYPE_CHECKING, Any, NoReturn, override

import anyio
from faststream._internal.endpoint.subscriber import SubscriberSpecification, SubscriberUsecase
from faststream._internal.endpoint.subscriber.mixins import TasksMixin
from faststream.specification.asyncapi.utils import resolve_payloads
from faststream.specification.schema import Message, Operation, SubscriberSpec

from faststream_redis_timers.message import TIMER_SEPARATOR, TimerMessage
from faststream_redis_timers.parser.parser import TimerParser
from faststream_redis_timers.subscriber.config import TimersSubscriberConfig, TimersSubscriberSpecificationConfig


if TYPE_CHECKING:
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


class TimersSubscriber(TasksMixin, SubscriberUsecase[TimerMessage]):  # type: ignore[misc]
    _outer_config: "TimersBrokerConfig"

    def __init__(
        self,
        config: TimersSubscriberConfig,
        specification: TimersSubscriberSpecification,
        calls: "CallsCollection[Any]",
    ) -> None:
        timer_parser = TimerParser(config)
        config.parser = timer_parser.parse_message
        config.decoder = timer_parser.decode_message
        super().__init__(config, specification, calls)
        self._config = config
        self._read_lock = anyio.Lock()

    @property
    def _client(self) -> "Redis[bytes]":
        return self._outer_config.connection.client

    @override
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
        if await client.ping():
            start_signal.set()

        connected = True
        while self.running:
            try:
                await self._get_msgs(client)
            except Exception as e:  # noqa: BLE001
                self._log(
                    log_level=logging.ERROR,
                    message="Message fetch error",
                    exc_info=e,
                )
                if connected:
                    connected = False
                await anyio.sleep(5)
            else:
                if not connected:
                    connected = True
            finally:
                if not start_signal.is_set():
                    with suppress(Exception):
                        start_signal.set()

    async def _get_msgs(self, client: "Redis[bytes]") -> None:
        from redis.asyncio.lock import Lock  # noqa: PLC0415

        now = time.time()
        timer_keys: list[bytes] = await client.zrangebyscore(self._config.timeline_key, "-inf", now)

        if not timer_keys:
            await anyio.sleep(self._config.timer_sub.polling_interval)
            return

        count = 0
        for raw_key in timer_keys:
            if count >= self._config.timer_sub.max_concurrent:
                break

            key_str = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            lock = Lock(
                client,
                f"{self._config.lock_prefix}{key_str}",
                timeout=self._config.timer_sub.lock_ttl,
                blocking=False,
            )

            acquired = await lock.acquire()
            if not acquired:
                continue

            try:
                raw_payload: bytes | None = await client.hget(self._config.payloads_key, key_str)
                if raw_payload is None:
                    await client.zrem(self._config.timeline_key, key_str)
                    continue

                sep = TIMER_SEPARATOR
                if sep not in key_str:
                    continue  # malformed key

                topic, timer_id = key_str.split(sep, 1)
                msg = TimerMessage(
                    type="timer",
                    channel=topic,
                    timer_id=timer_id,
                    data=raw_payload,
                )
                await self.consume(msg)
                count += 1
            finally:
                await lock.release()

    @override
    async def stop(self) -> None:
        with anyio.move_on_after(self._outer_config.graceful_timeout):
            async with self._read_lock:
                await super().stop()

    @override
    async def get_one(self, *, timeout: float = 5.0) -> NoReturn:  # noqa: ASYNC109
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
