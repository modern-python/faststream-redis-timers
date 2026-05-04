import typing
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from faststream._internal.testing.broker import TestBroker, change_producer

from faststream_redis_timers.broker import TimersBroker
from faststream_redis_timers.envelope import TimerMessageFormat
from faststream_redis_timers.message import TimerMessage
from faststream_redis_timers.publisher.producer import TimersProducer
from faststream_redis_timers.publisher.usecase import TimersPublisher
from faststream_redis_timers.response import TimerPublishCommand
from faststream_redis_timers.subscriber.usecase import TimersSubscriber


if typing.TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(frozen=True, slots=True)
class ScheduledTimer:
    """Record of a publish call captured by `TestTimersBroker.scheduled_timers`."""

    topic: str
    timer_id: str
    activate_at: datetime
    body: typing.Any
    correlation_id: str = ""
    headers: dict[str, typing.Any] | None = None


class TestTimersBroker(TestBroker[TimersBroker]):
    scheduled_timers: list[ScheduledTimer]

    def __init__(self, broker: TimersBroker, **kwargs: typing.Any) -> None:
        super().__init__(broker, **kwargs)
        self.scheduled_timers = []

    @staticmethod
    def create_publisher_fake_subscriber(
        broker: TimersBroker,
        publisher: TimersPublisher,
    ) -> tuple[TimersSubscriber, bool]:
        subscriber: TimersSubscriber | None = None
        for handler in broker._subscribers:  # noqa: SLF001
            if handler._config.full_topic == publisher.config.full_topic:  # noqa: SLF001
                subscriber = handler
                break
        if subscriber is None:
            is_real = False
            subscriber = broker.subscriber(publisher.config.topic)
        else:
            is_real = True
        return subscriber, is_real

    @contextmanager
    def _patch_producer(self, broker: TimersBroker) -> "Iterator[None]":
        producer = FakeTimersProducer(broker, scheduled_timers=self.scheduled_timers)
        with change_producer(broker.config.broker_config, producer):
            yield

    @contextmanager
    def _patch_broker(self, broker: TimersBroker) -> "Iterator[None]":
        # Test-broker contract: messages deliver immediately, so there are
        # never any pending timers. Stub the inspection paths to return that.
        mock_client = AsyncMock()
        mock_client.zrangebyscore.return_value = []  # get_pending_timers -> []
        mock_client.zscore.return_value = None  # has_pending -> False
        # cancel_all uses `async with client.pipeline(...) as pipe`. AsyncMock's
        # default makes pipeline() return a coroutine, which can't be entered.
        # Use MagicMock so the call returns the AsyncMock directly; AsyncMock
        # natively supports the async-context-manager protocol.
        mock_pipe = AsyncMock()
        mock_pipe.__aenter__.return_value = mock_pipe  # `async with ... as pipe` -> mock_pipe
        mock_pipe.execute.return_value = [0]  # zcard result -> 0 removed
        mock_client.pipeline = MagicMock(return_value=mock_pipe)
        connection = broker.config.broker_config.connection
        original_client = connection._client  # noqa: SLF001
        connection._client = mock_client  # noqa: SLF001
        try:
            with super()._patch_broker(broker):
                yield
        finally:
            connection._client = original_client  # noqa: SLF001

    async def _fake_connect(self, broker: TimersBroker, *args: typing.Any, **kwargs: typing.Any) -> None: ...


class FakeTimersProducer(TimersProducer):
    def __init__(self, broker: TimersBroker, scheduled_timers: list[ScheduledTimer] | None = None) -> None:
        self.broker = broker
        self.scheduled_timers = scheduled_timers if scheduled_timers is not None else []

    async def publish(self, cmd: TimerPublishCommand) -> None:
        payload = TimerMessageFormat.encode(
            message=cmd.body,
            reply_to=cmd.reply_to,
            headers=cmd.headers,
            correlation_id=cmd.correlation_id or "",
            serializer=self.broker.config.fd_config._serializer,  # noqa: SLF001
        )
        topic = cmd.destination
        timer_id = cmd.timer_id or ""

        self.scheduled_timers.append(
            ScheduledTimer(
                topic=topic,
                timer_id=timer_id,
                activate_at=cmd.activate_at,
                body=cmd.body,
                correlation_id=cmd.correlation_id or "",
                headers=cmd.headers,
            )
        )

        # In tests we deliver immediately regardless of activate_at
        msg = TimerMessage(
            type="timer",
            channel=topic,
            timer_id=timer_id,
            data=payload,
        )
        for handler in self.broker.subscribers:
            sub = typing.cast("TimersSubscriber", handler)
            if sub._config.full_topic == topic:  # noqa: SLF001
                await handler.process_message(msg)

    async def cancel(self, full_topic: str, timer_id: str) -> None:
        pass  # In tests, timers are delivered immediately, so cancel is always a no-op
