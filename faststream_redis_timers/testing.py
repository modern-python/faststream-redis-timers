import typing
from contextlib import contextmanager
from unittest.mock import AsyncMock

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


class TestTimersBroker(TestBroker[TimersBroker]):
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
        with change_producer(broker.config.broker_config, FakeTimersProducer(broker)):
            yield

    @contextmanager
    def _patch_broker(self, broker: TimersBroker) -> "Iterator[None]":
        mock_client = AsyncMock()
        mock_client.zrangebyscore.return_value = []
        broker.config.broker_config.connection._client = mock_client  # noqa: SLF001
        with super()._patch_broker(broker):
            yield

    async def _fake_connect(self, broker: TimersBroker, *args: typing.Any, **kwargs: typing.Any) -> None: ...


class FakeTimersProducer(TimersProducer):
    def __init__(self, broker: TimersBroker) -> None:
        self.broker = broker

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

        # In tests we deliver immediately regardless of activate_in
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
