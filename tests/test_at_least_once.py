import asyncio
import time
import uuid

from faststream.exceptions import RejectMessage
from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker
from faststream_redis_timers.subscriber.lua import CLAIM_LUA


async def test_handler_success_removes_timer(broker: TimersBroker, redis_client: Redis) -> None:
    """ZREM happens only after the handler returns successfully."""
    seen: list[str] = []
    delivered = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        seen.append(body)
        # While in-handler, the timer is leased (still in zset with future score)
        timeline_key = f"{broker.config.broker_config.timeline_key}:topic"
        score = await redis_client.zscore(timeline_key, "the-id")
        assert score is not None
        assert score > time.time(), "lease should push score into the future"
        delivered.set()

    async with broker:
        await broker.publish("hi", topic="topic", timer_id="the-id")
        await asyncio.wait_for(delivered.wait(), timeout=5.0)
        await asyncio.sleep(0.2)  # allow ack to land

    assert seen == ["hi"]
    timeline_key = f"{broker.config.broker_config.timeline_key}:topic"
    payloads_key = f"{broker.config.broker_config.payloads_key}:topic"
    assert await redis_client.zscore(timeline_key, "the-id") is None
    assert await redis_client.hget(payloads_key, "the-id") is None


async def test_at_least_once_on_handler_crash(redis_client: Redis) -> None:
    """If the handler raises, the timer is retried after the lease expires."""
    suffix = uuid.uuid4().hex
    fast_broker = TimersBroker(
        redis_client,
        timeline_key=f"alo_tl_{suffix}",
        payloads_key=f"alo_pl_{suffix}",
    )
    seen: list[str] = []
    second_attempt = asyncio.Event()

    @fast_broker.subscriber("topic", lease_ttl=1)
    async def handler(body: str) -> None:
        seen.append(body)
        if len(seen) == 1:
            msg = "boom"
            raise RuntimeError(msg)
        second_attempt.set()

    async with fast_broker:
        await fast_broker.publish("retry-me", topic="topic", timer_id="retry-id")
        await asyncio.wait_for(second_attempt.wait(), timeout=5.0)

    assert len(seen) >= 2
    assert seen[0] == "retry-me"

    timeline_key = f"alo_tl_{suffix}:topic"
    assert await redis_client.zscore(timeline_key, "retry-id") is None


async def test_concurrent_claim_only_one_succeeds(redis_client: Redis) -> None:
    """Two concurrent claim.lua calls on the same timer: exactly one returns the payload."""
    suffix = uuid.uuid4().hex
    timeline_key = f"cc_tl_{suffix}:topic"
    payloads_key = f"cc_pl_{suffix}:topic"
    now = time.time()
    await redis_client.zadd(timeline_key, {"id-1": now - 1})
    await redis_client.hset(payloads_key, "id-1", b"payload")

    async def claim() -> object:
        return await redis_client.eval(CLAIM_LUA, 2, timeline_key, payloads_key, "id-1", now, now + 30)

    a, b = await asyncio.gather(claim(), claim())
    results = [r for r in (a, b) if r is not None]
    assert len(results) == 1
    assert results[0] == b"payload"

    await redis_client.delete(timeline_key, payloads_key)


async def test_lease_expiry_allows_re_pickup(redis_client: Redis) -> None:
    """A timer leased in the past (lease expired) is re-claimable by a fresh call."""
    suffix = uuid.uuid4().hex
    timeline_key = f"le_tl_{suffix}:topic"
    payloads_key = f"le_pl_{suffix}:topic"
    now = time.time()
    # Score is in the past — lease expired
    await redis_client.zadd(timeline_key, {"id-1": now - 5})
    await redis_client.hset(payloads_key, "id-1", b"payload")
    result = await redis_client.eval(CLAIM_LUA, 2, timeline_key, payloads_key, "id-1", now, now + 30)
    assert result == b"payload"

    # Score should now be in the future (lease pushed forward)
    score = await redis_client.zscore(timeline_key, "id-1")
    assert score is not None
    assert score > now

    await redis_client.delete(timeline_key, payloads_key)


async def test_explicit_reject_drops_timer(broker: TimersBroker, redis_client: Redis) -> None:
    """Handler raising RejectMessage removes the timer without retry."""
    seen: list[str] = []
    fired = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        seen.append(body)
        fired.set()
        raise RejectMessage

    async with broker:
        await broker.publish("drop-me", topic="topic", timer_id="reject-id")
        await asyncio.wait_for(fired.wait(), timeout=5.0)
        await asyncio.sleep(0.3)  # allow reject() to commit

    assert seen == ["drop-me"]
    timeline_key = f"{broker.config.broker_config.timeline_key}:topic"
    assert await redis_client.zscore(timeline_key, "reject-id") is None


async def test_orphan_zset_entry_is_cleaned_up(redis_client: Redis) -> None:
    """A zset entry without a payload hash is removed by claim.lua and not delivered."""
    suffix = uuid.uuid4().hex
    timeline_key = f"orph_tl_{suffix}:topic"
    payloads_key = f"orph_pl_{suffix}:topic"
    now = time.time()
    await redis_client.zadd(timeline_key, {"ghost": now - 1})

    result = await redis_client.eval(CLAIM_LUA, 2, timeline_key, payloads_key, "ghost", now, now + 30)
    assert result is None
    assert await redis_client.zscore(timeline_key, "ghost") is None

    await redis_client.delete(timeline_key, payloads_key)
