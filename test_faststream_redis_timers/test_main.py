"""Unit tests for TimersBroker using TestTimersBroker (no real Redis)."""

import pytest

from faststream_redis_timers import TestTimersBroker, TimersBroker


@pytest.mark.asyncio
async def test_subscriber_receives_message() -> None:
    broker = TimersBroker()
    result: list[str] = []

    @broker.subscriber("my-topic")
    async def handler(body: str) -> None:
        result.append(body)

    async with TestTimersBroker(broker) as tb:
        await tb.publish("hello", topic="my-topic")

    assert result == ["hello"]


@pytest.mark.asyncio
async def test_publisher_sends_message() -> None:
    broker = TimersBroker()
    result: list[str] = []

    @broker.subscriber("pub-topic")
    async def handler(body: str) -> None:
        result.append(body)

    pub = broker.publisher("pub-topic")

    async with TestTimersBroker(broker) as _:
        await pub.publish("world")

    assert result == ["world"]


@pytest.mark.asyncio
async def test_publisher_with_timer_id() -> None:
    broker = TimersBroker()
    result: list[str] = []

    @broker.subscriber("timer-topic")
    async def handler(body: str) -> None:
        result.append(body)

    async with TestTimersBroker(broker) as tb:
        await tb.publish("payload", topic="timer-topic", timer_id="abc-123")

    assert result == ["payload"]


@pytest.mark.asyncio
async def test_request_raises() -> None:
    broker = TimersBroker()
    async with TestTimersBroker(broker):
        with pytest.raises(NotImplementedError):
            await broker.request("x", "y")


@pytest.mark.asyncio
async def test_publish_batch_raises() -> None:
    broker = TimersBroker()
    async with TestTimersBroker(broker):
        with pytest.raises(NotImplementedError):
            await broker.publish_batch()
