import typing
from typing import TypedDict

from faststream.message import StreamMessage

from faststream_redis_timers.subscriber.lua import COMMIT_LUA


if typing.TYPE_CHECKING:
    from redis.asyncio import Redis


class TimerMessage(TypedDict):
    type: typing.Literal["timer"]
    channel: str
    timer_id: str
    data: bytes


class TimerStreamMessage(StreamMessage["TimerMessage"]):
    """
    Stream message that removes the timer from Redis only on ack/reject.

    Lease-based at-least-once delivery: the timer remains in the timeline
    (with its score pushed forward by `lease_ttl`) while the handler runs.
    `ack()` and `reject()` atomically remove it; `nack()` is a no-op so the
    lease expires and another worker re-claims the timer.
    """

    def __init__(
        self,
        *args: typing.Any,
        client: "Redis[bytes] | None" = None,
        timeline_key: str = "",
        payloads_key: str = "",
        timer_id: str = "",
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._client = client
        self._timeline_key = timeline_key
        self._payloads_key = payloads_key
        self._timer_id = timer_id

    async def _commit(self) -> None:
        if self._client is None or not self._timer_id:
            return
        await self._client.eval(
            COMMIT_LUA,
            2,
            self._timeline_key,
            self._payloads_key,
            self._timer_id,
        )

    async def ack(self) -> None:
        if self.committed is None:
            await self._commit()
        await super().ack()

    async def reject(self) -> None:
        if self.committed is None:
            await self._commit()
        await super().reject()
