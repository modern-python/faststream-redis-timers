import asyncio
from datetime import timedelta

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
