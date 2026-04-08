from typing import TYPE_CHECKING, Literal, override

from faststream.message import StreamMessage
from typing_extensions import TypedDict


if TYPE_CHECKING:
    from redis.asyncio import Redis


class TimerMessage(TypedDict):
    type: Literal["timer"]
    channel: str
    timer_id: str
    data: bytes


class TimerStreamMessage(StreamMessage["TimerMessage"]):
    def __init__(
        self,
        *,
        _redis_client: "Redis[bytes]",
        _timer_key: str,
        _timeline_key: str,
        _payloads_key: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._redis_client = _redis_client
        self._timer_key = _timer_key
        self._timeline_key = _timeline_key
        self._payloads_key = _payloads_key

    @override
    async def ack(self) -> None:
        if not self.committed:
            async with self._redis_client.pipeline(transaction=True) as pipe:
                pipe.zrem(self._timeline_key, self._timer_key)
                pipe.hdel(self._payloads_key, self._timer_key)
                await pipe.execute()
        await super().ack()

    @override
    async def nack(self) -> None:
        await super().nack()  # timer stays in Redis for retry

    @override
    async def reject(self) -> None:
        if not self.committed:
            async with self._redis_client.pipeline(transaction=True) as pipe:
                pipe.zrem(self._timeline_key, self._timer_key)
                pipe.hdel(self._payloads_key, self._timer_key)
                await pipe.execute()
        await super().reject()
