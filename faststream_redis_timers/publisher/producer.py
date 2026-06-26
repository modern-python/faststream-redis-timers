import typing

from faststream._internal.parser import DefaultCodec

from faststream_redis_timers.envelope import TimerMessageFormat
from faststream_redis_timers.response import TimerPublishCommand


if typing.TYPE_CHECKING:
    from fast_depends.library.serializer import SerializerProto
    from faststream._internal.parser import CodecProto
    from faststream._internal.types import AsyncCallable

    from faststream_redis_timers.store import TimerStore


class TimersProducer:
    _parser: "AsyncCallable"
    _decoder: "AsyncCallable"
    codec: "CodecProto" = DefaultCodec()

    def __init__(
        self,
        *,
        store: "TimerStore",
        serializer: "SerializerProto | None" = None,
    ) -> None:
        self._store = store
        self.serializer = serializer

    async def publish(self, cmd: TimerPublishCommand) -> None:
        payload = await TimerMessageFormat.encode(
            message=cmd.body,
            reply_to=cmd.reply_to,
            headers=cmd.headers,
            correlation_id=cmd.correlation_id or "",
            serializer=self.serializer,
        )
        await self._store.schedule(cmd.destination, cmd.timer_id, payload, cmd.activate_at.timestamp())

    async def cancel(self, full_topic: str, timer_id: str) -> None:
        await self._store.remove(full_topic, timer_id)

    async def request(self, cmd: TimerPublishCommand) -> typing.NoReturn:  # pragma: no cover
        msg = "Timers do not support request-reply"
        raise NotImplementedError(msg)

    async def publish_batch(self, cmd: TimerPublishCommand) -> typing.NoReturn:  # pragma: no cover
        msg = "Use multiple publish() calls for multiple timers"
        raise NotImplementedError(msg)

    def connect(self, serializer: "SerializerProto | None" = None) -> None:  # pragma: no cover
        self.serializer = serializer
