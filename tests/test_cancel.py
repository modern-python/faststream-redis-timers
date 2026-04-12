import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from faststream_redis_timers import TimersBroker


async def test_cancel_timer_via_broker(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None:  # pragma: no cover
        pytest.fail(f"Handler should not be called, got: {body!r}")

    async with broker:
        await broker.publish("should-not-arrive", topic="topic", timer_id="cancel-me", activate_in=timedelta(hours=1))
        await broker.cancel_timer("topic", "cancel-me")
        await asyncio.sleep(0.3)


async def test_cancel_timer_via_publisher(broker: TimersBroker) -> None:
    pub = broker.publisher("topic")

    @broker.subscriber("topic")
    async def handler(body: str) -> None:  # pragma: no cover
        pytest.fail(f"Handler should not be called, got: {body!r}")

    async with broker:
        await pub.publish("should-not-arrive", timer_id="cancel-me", activate_in=timedelta(hours=1))
        await pub.cancel("cancel-me")
        await asyncio.sleep(0.3)


async def test_cancel_nonexistent_timer_is_noop(broker: TimersBroker) -> None:
    async with broker:
        await broker.cancel_timer("topic", "does-not-exist")


async def test_future_timer_does_not_fire_immediately(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None:  # pragma: no cover
        pytest.fail(f"Handler should not be called, got: {body!r}")

    async with broker:
        await broker.publish("future", topic="topic", activate_in=timedelta(hours=1))
        await asyncio.sleep(0.3)


async def test_fetch_redis_timers_returns_pending_timers(broker: TimersBroker) -> None:
    pub = broker.publisher("topic")
    async with broker:
        await pub.publish("msg", timer_id="timer-1", activate_in=timedelta(hours=1))
        result = await pub.fetch_redis_timers(datetime.now(tz=UTC) + timedelta(hours=2))
    assert ("topic", "timer-1") in result


async def test_fetch_redis_timers_excludes_not_yet_due(broker: TimersBroker) -> None:
    pub = broker.publisher("topic")
    async with broker:
        await pub.publish("msg", timer_id="timer-1", activate_in=timedelta(hours=1))
        result = await pub.fetch_redis_timers(datetime.now(tz=UTC))
    assert result == []


async def test_fetch_redis_timers_multiple_timers(broker: TimersBroker) -> None:
    pub = broker.publisher("topic")
    async with broker:
        await pub.publish("a", timer_id="t1", activate_in=timedelta(hours=1))
        await pub.publish("b", timer_id="t2", activate_in=timedelta(hours=2))
        result = await pub.fetch_redis_timers(datetime.now(tz=UTC) + timedelta(hours=3))
    timer_ids = {tid for _, tid in result}
    assert timer_ids == {"t1", "t2"}
