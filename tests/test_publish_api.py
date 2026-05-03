import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest
from faststream import Context

from faststream_redis_timers import TimersBroker


async def test_publish_returns_generated_timer_id(broker: TimersBroker) -> None:
    seen_ids: list[str] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(
        body: str,
        message_id: str = Context("message.message_id"),
    ) -> None:
        del body
        seen_ids.append(message_id)
        event.set()

    async with broker:
        tid = await broker.publish("hi", topic="topic")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert tid
    assert seen_ids == [tid]


async def test_publish_returns_provided_timer_id(broker: TimersBroker) -> None:
    received: list[str] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        event.set()

    async with broker:
        tid = await broker.publish("hi", topic="topic", timer_id="my-id")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert tid == "my-id"
    assert received == ["hi"]


async def test_publisher_publish_returns_timer_id(broker: TimersBroker) -> None:
    pub = broker.publisher("topic")
    received: list[str] = []
    seen_two = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        if len(received) >= 2:
            seen_two.set()

    async with broker:
        tid_generated = await pub.publish("hi")
        tid_provided = await pub.publish("hi", timer_id="custom-id")
        await asyncio.wait_for(seen_two.wait(), timeout=5.0)

    assert tid_generated
    assert tid_generated != "custom-id"
    assert tid_provided == "custom-id"


async def test_activate_at_schedules_at_absolute_time(broker: TimersBroker) -> None:
    delivered_at: list[float] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        del body
        delivered_at.append(time.monotonic())
        event.set()

    target = datetime.now(tz=UTC) + timedelta(seconds=0.3)
    async with broker:
        published_at = time.monotonic()
        await broker.publish("hi", topic="topic", activate_at=target)
        await asyncio.wait_for(event.wait(), timeout=5.0)

    elapsed = delivered_at[0] - published_at
    assert 0.2 < elapsed < 1.5, f"expected ~0.3s, got {elapsed:.3f}s"


async def test_activate_at_in_past_fires_immediately(broker: TimersBroker) -> None:
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        del body
        event.set()

    past = datetime.now(tz=UTC) - timedelta(seconds=10)
    async with broker:
        await broker.publish("hi", topic="topic", activate_at=past)
        await asyncio.wait_for(event.wait(), timeout=5.0)


async def test_activate_at_naive_raises_value_error(broker: TimersBroker) -> None:
    async with broker:
        with pytest.raises(ValueError, match="timezone-aware"):
            await broker.publish("hi", topic="topic", activate_at=datetime(2026, 6, 1))  # noqa: DTZ001


async def test_activate_in_and_activate_at_together_raises(broker: TimersBroker) -> None:
    async with broker:
        with pytest.raises(ValueError, match="not both"):
            await broker.publish(
                "hi",
                topic="topic",
                activate_in=timedelta(seconds=5),
                activate_at=datetime.now(tz=UTC),
            )
