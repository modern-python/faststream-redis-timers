import typing

from faststream.message import StreamMessage


if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class TimerMessage(typing.TypedDict):
    type: typing.Literal["timer"]
    channel: str
    timer_id: str
    data: bytes


class TimerStreamMessage(StreamMessage["TimerMessage"]):
    """Stream message that removes the timer from Redis only on ack/reject.

    Lease-based at-least-once delivery: the timer remains in the timeline
    (with its score pushed forward by `lease_ttl`) while the handler runs.
    `ack()` and `reject()` atomically remove it; `nack()` is a no-op so the
    lease expires and another worker re-claims the timer.
    """

    def __init__(
        self,
        *args: typing.Any,
        _remove: "Callable[[], Awaitable[None]] | None" = None,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._remove = _remove

    async def _commit(self) -> None:
        if self._remove is None:
            return
        await self._remove()

    async def ack(self) -> None:
        if self.committed is None:
            await self._commit()
        await super().ack()

    async def reject(self) -> None:
        if self.committed is None:
            await self._commit()
        await super().reject()
