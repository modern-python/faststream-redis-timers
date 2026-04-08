import asyncio
import time
import uuid

import pytest
from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker
from .conftest import REDIS_URL


async def test_key_without_payload_is_cleaned_up(broker: TimersBroker, redis_client: Redis) -> None:
    """Key in sorted set with no matching hash entry is removed (covers raw_payload is None branch)."""

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        event.set()

    timeline_key = broker.config.broker_config.timeline_key
    topic_timeline_key = f"{timeline_key}:topic"
    # Insert a ghost timer ID into the topic's sorted set only — no payload in the hash
    await redis_client.zadd(topic_timeline_key, {"ghost-id": time.time() - 1})

    received: list[str] = []
    event = asyncio.Event()

    async with broker:
        await broker.publish("real", topic="topic")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    # Ghost key should be removed
    remaining = await redis_client.zrange(topic_timeline_key, 0, -1)
    assert b"ghost-id" not in remaining
    assert received == ["real"]


async def test_separate_topics_do_not_cross(broker: TimersBroker) -> None:
    received_a: list[str] = []
    received_b: list[str] = []
    event = asyncio.Event()

    @broker.subscriber("topic-a")
    async def handler_a(body: str) -> None:
        received_a.append(body)
        event.set()

    @broker.subscriber("topic-b")
    async def handler_b(body: str) -> None:  # pragma: no cover
        pytest.fail(f"topic-b handler should not fire, got: {body!r}")

    async with broker:
        await broker.publish("for-a", topic="topic-a")
        await asyncio.wait_for(event.wait(), timeout=5.0)
        await asyncio.sleep(0.1)

    assert received_a == ["for-a"]
    assert received_b == []


async def test_max_concurrent_limits_batch(redis_client: Redis) -> None:
    """Covers the break when count >= max_concurrent within a single poll cycle."""
    suffix = uuid.uuid4().hex
    tight_broker = TimersBroker(
        redis_client,
        timeline_key=f"tight_tl_{suffix}",
        payloads_key=f"tight_pl_{suffix}",
        lock_prefix=f"tight_lk_{suffix}:",
    )
    received: list[str] = []
    all_done = asyncio.Event()

    @tight_broker.subscriber("topic", max_concurrent=1)
    async def handler(body: str) -> None:
        received.append(body)
        if len(received) >= 2:
            all_done.set()

    async with tight_broker:
        await tight_broker.publish("msg-1", topic="topic")
        await tight_broker.publish("msg-2", topic="topic")
        await asyncio.wait_for(all_done.wait(), timeout=5.0)

    assert sorted(received) == ["msg-1", "msg-2"]


async def test_subscriber_no_handlers(redis_client: Redis) -> None:
    """Subscriber with no handlers registered starts cleanly (covers else: start_signal.set())."""
    suffix = uuid.uuid4().hex
    broker = TimersBroker(
        redis_client,
        timeline_key=f"noh_tl_{suffix}",
        payloads_key=f"noh_pl_{suffix}",
        lock_prefix=f"noh_lk_{suffix}:",
    )
    _ = broker.subscriber("topic")  # no handler applied

    async with broker:
        await asyncio.sleep(0.05)  # just verify it doesn't hang


async def test_two_brokers_same_keys_deliver_once(redis_client: Redis) -> None:
    """Two broker instances sharing keys process each timer exactly once."""
    suffix = uuid.uuid4().hex
    kwargs = {
        "timeline_key": f"shared_tl_{suffix}",
        "payloads_key": f"shared_pl_{suffix}",
        "lock_prefix": f"shared_lk_{suffix}:",
    }
    client_a = redis_client
    client_b = Redis.from_url(REDIS_URL)
    broker_a = TimersBroker(client_a, **kwargs)  # ty: ignore[invalid-argument-type]
    broker_b = TimersBroker(client_b, **kwargs)  # ty: ignore[invalid-argument-type]

    received: list[str] = []
    event = asyncio.Event()

    @broker_a.subscriber("topic")
    async def handler_a(body: str) -> None:  # pragma: no cover
        received.append(body)
        event.set()

    @broker_b.subscriber("topic")
    async def handler_b(body: str) -> None:  # pragma: no cover
        received.append(body)
        event.set()

    async with broker_a, broker_b:
        await broker_a.publish("once", topic="topic")
        await asyncio.wait_for(event.wait(), timeout=5.0)
        await asyncio.sleep(0.3)  # give the second broker a chance to double-deliver

    await client_b.aclose()  # ty: ignore[unresolved-attribute]
    assert received == ["once"]
