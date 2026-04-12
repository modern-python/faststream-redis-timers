from datetime import UTC, datetime

import pytest

from faststream_redis_timers import TestTimersBroker, TimersBroker


async def test_fake_broker_subscriber() -> None:
    broker = TimersBroker()
    result: list[str] = []

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        result.append(body)

    async with TestTimersBroker(broker) as tb:
        await tb.publish("hello", topic="topic")

    assert result == ["hello"]


async def test_fake_broker_publisher() -> None:
    broker = TimersBroker()
    result: list[str] = []

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        result.append(body)

    async with TestTimersBroker(broker):
        await broker.publisher("topic").publish("world")

    assert result == ["world"]


async def test_fake_broker_pre_registered_publisher_no_sub() -> None:
    """Publisher pre-registered before context: _fake_start creates a fake subscriber (is_real=False path)."""
    broker = TimersBroker()
    pub = broker.publisher("no-sub-topic")  # pre-registered, no matching subscriber

    async with TestTimersBroker(broker):
        await pub.publish("msg")


async def test_fake_broker_pre_registered_publisher_with_sub() -> None:
    """Publisher + subscriber both pre-registered: _fake_start finds real subscriber (is_real=True path)."""
    broker = TimersBroker()
    result: list[str] = []
    pub = broker.publisher("topic")  # pre-registered

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        result.append(body)

    async with TestTimersBroker(broker):
        await pub.publish("hi")

    assert result == ["hi"]


async def test_fake_broker_cancel_is_noop() -> None:
    broker = TimersBroker()
    async with TestTimersBroker(broker):
        await broker.cancel_timer("topic", "any-id")
        await broker.publisher("topic").cancel("any-id")


async def test_request_raises() -> None:
    broker = TimersBroker()
    async with TestTimersBroker(broker):
        with pytest.raises(NotImplementedError):
            await broker.request("x", "y")


async def test_publish_batch_raises() -> None:
    broker = TimersBroker()
    async with TestTimersBroker(broker):
        with pytest.raises(NotImplementedError):
            await broker.publish_batch()


async def test_fake_broker_fetch_redis_timers_returns_empty() -> None:
    broker = TimersBroker()
    pub = broker.publisher("topic")
    async with TestTimersBroker(broker):
        result = await pub.fetch_redis_timers(datetime.now(tz=UTC))
    assert result == []
