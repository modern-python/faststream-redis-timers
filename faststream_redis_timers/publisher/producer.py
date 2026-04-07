import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NoReturn

from faststream.message import encode_message

from faststream_redis_timers.message import TIMER_SEPARATOR
from faststream_redis_timers.response import TimerPublishCommand


if TYPE_CHECKING:
    from fast_depends.library.serializer import SerializerProto
    from faststream._internal.types import AsyncCallable

    from faststream_redis_timers.configs import ConnectionState


class TimersProducer:
    _parser: "AsyncCallable"  # type: ignore[assignment]
    _decoder: "AsyncCallable"  # type: ignore[assignment]

    def __init__(
        self,
        *,
        connection: "ConnectionState",
        timeline_key: str,
        payloads_key: str,
        serializer: "SerializerProto | None" = None,
    ) -> None:
        self._connection = connection
        self._timeline_key = timeline_key
        self._payloads_key = payloads_key
        self.serializer = serializer

    async def publish(self, cmd: TimerPublishCommand) -> None:
        client = self._connection.client
        body, content_type = encode_message(cmd.body, serializer=self.serializer)
        payload = json.dumps({"b": body.hex(), "ct": content_type}).encode()

        timer_key = f"{cmd.destination}{TIMER_SEPARATOR}{cmd.timer_id}"
        activation_ts = (datetime.now(tz=UTC) + cmd.activate_in).timestamp()

        async with client.pipeline(transaction=True) as pipe:
            pipe.zadd(self._timeline_key, {timer_key: activation_ts})
            pipe.hset(self._payloads_key, timer_key, payload)
            await pipe.execute()

    async def request(self, cmd: TimerPublishCommand) -> NoReturn:
        msg = "Timers do not support request-reply"
        raise NotImplementedError(msg)

    async def publish_batch(self, cmd: TimerPublishCommand) -> NoReturn:
        msg = "Use multiple publish() calls for multiple timers"
        raise NotImplementedError(msg)

    def connect(self, serializer: "SerializerProto | None" = None) -> None:
        self.serializer = serializer
