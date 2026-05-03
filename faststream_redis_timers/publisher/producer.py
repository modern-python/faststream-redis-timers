import typing

from faststream_redis_timers.envelope import TimerMessageFormat
from faststream_redis_timers.response import TimerPublishCommand


if typing.TYPE_CHECKING:
    from fast_depends.library.serializer import SerializerProto
    from faststream._internal.types import AsyncCallable

    from faststream_redis_timers.configs import ConnectionState


class TimersProducer:
    _parser: "AsyncCallable"
    _decoder: "AsyncCallable"

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
        payload = TimerMessageFormat.encode(
            message=cmd.body,
            reply_to=cmd.reply_to,
            headers=cmd.headers,
            correlation_id=cmd.correlation_id or "",
            serializer=self.serializer,
        )

        timeline_key = f"{self._timeline_key}:{cmd.destination}"
        payloads_key = f"{self._payloads_key}:{cmd.destination}"
        activation_ts = cmd.activate_at.timestamp()

        async with client.pipeline(transaction=True) as pipe:
            pipe.zadd(timeline_key, {cmd.timer_id: activation_ts})
            pipe.hset(payloads_key, cmd.timer_id, payload)
            await pipe.execute()

    async def cancel(self, full_topic: str, timer_id: str) -> None:
        client = self._connection.client
        timeline_key = f"{self._timeline_key}:{full_topic}"
        payloads_key = f"{self._payloads_key}:{full_topic}"
        async with client.pipeline(transaction=True) as pipe:
            pipe.zrem(timeline_key, timer_id)
            pipe.hdel(payloads_key, timer_id)
            await pipe.execute()

    async def request(self, cmd: TimerPublishCommand) -> typing.NoReturn:  # pragma: no cover
        msg = "Timers do not support request-reply"
        raise NotImplementedError(msg)

    async def publish_batch(self, cmd: TimerPublishCommand) -> typing.NoReturn:  # pragma: no cover
        msg = "Use multiple publish() calls for multiple timers"
        raise NotImplementedError(msg)

    def connect(self, serializer: "SerializerProto | None" = None) -> None:  # pragma: no cover
        self.serializer = serializer
