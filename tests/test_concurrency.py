import asyncio
import time
import uuid

from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker


async def test_handlers_run_concurrently(redis_client: Redis) -> None:
    """3 timers with max_concurrent=3 reach a shared barrier — proves true fan-out."""
    suffix = uuid.uuid4().hex
    broker = TimersBroker(
        redis_client,
        timeline_key=f"conc_tl_{suffix}",
        payloads_key=f"conc_pl_{suffix}",
    )

    arrived = 0
    barrier = asyncio.Event()
    all_done = asyncio.Event()

    @broker.subscriber("topic", max_concurrent=3)
    async def handler(body: str) -> None:
        nonlocal arrived
        assert body in {"a", "b", "c"}
        arrived += 1
        if arrived >= 3:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=2.0)
        if arrived == 3:
            all_done.set()

    async with broker:
        start = time.monotonic()
        await broker.publish("a", topic="topic")
        await broker.publish("b", topic="topic")
        await broker.publish("c", topic="topic")
        await asyncio.wait_for(all_done.wait(), timeout=5.0)
        elapsed = time.monotonic() - start

    assert arrived == 3
    # Handlers run in parallel, so total time is bounded by polling + barrier release,
    # NOT 3x barrier_timeout. Generous bound to keep CI stable.
    assert elapsed < 1.5


async def test_concurrency_bounded_by_max_concurrent(redis_client: Redis) -> None:
    """5 timers with max_concurrent=2 — at most 2 handlers ever run at once."""
    suffix = uuid.uuid4().hex
    broker = TimersBroker(
        redis_client,
        timeline_key=f"bound_tl_{suffix}",
        payloads_key=f"bound_pl_{suffix}",
    )

    in_flight = 0
    max_observed = 0
    completed = 0
    all_done = asyncio.Event()

    @broker.subscriber("topic", max_concurrent=2)
    async def handler(body: str) -> None:
        nonlocal in_flight, max_observed, completed
        assert body.startswith("msg-")
        in_flight += 1
        max_observed = max(max_observed, in_flight)
        await asyncio.sleep(0.1)
        in_flight -= 1
        completed += 1
        if completed >= 5:
            all_done.set()

    async with broker:
        for i in range(5):
            await broker.publish(f"msg-{i}", topic="topic")
        await asyncio.wait_for(all_done.wait(), timeout=5.0)

    assert completed == 5
    assert max_observed == 2
