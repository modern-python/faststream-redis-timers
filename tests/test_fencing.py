import asyncio
from datetime import UTC, datetime
from typing import Annotated

import pytest
from faststream import Context
from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker
from faststream_redis_timers.configs import ConnectionState
from faststream_redis_timers.message import TimerMessage, TimerStreamMessage
from faststream_redis_timers.parser.parser import TimerParser
from faststream_redis_timers.store import TimerStore
from .conftest import REDIS_URL


@pytest.mark.parametrize("completion", ["ack", "reject"])
async def test_claimed_timer_completion_preserves_replacement(broker: TimersBroker, completion: str) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()
    deadline = datetime(2100, 1, 1, tzinfo=UTC)

    @broker.subscriber("topic")
    async def handler(body: str, message: Annotated[TimerStreamMessage, Context("message")]) -> None:
        assert body == "same payload"
        entered.set()
        await release.wait()
        await getattr(message, completion)()
        completed.set()

    try:
        async with broker:
            await broker.publish("same payload", topic="topic", timer_id="K")
            await asyncio.wait_for(entered.wait(), 5)
            await broker.publish("same payload", topic="topic", timer_id="K", activate_at=deadline)
            release.set()
            await asyncio.wait_for(completed.wait(), 5)
            assert await broker.has_pending("topic", "K")
            store = broker.config.broker_config.store
            assert await store.pending("topic", before=deadline.timestamp() - 1) == []
            assert await store.pending("topic", before=deadline.timestamp()) == ["K"]
    finally:
        release.set()
        await broker.cancel_all("topic")


@pytest.mark.parametrize("completion", ["ack", "reject", "decode"])
@pytest.mark.parametrize("change", ["replacement", "takeover", "cancel_recreate", "cancel_all_recreate"])
async def test_stale_completion_preserves_current_timer(
    broker: TimersBroker,
    redis_client: Redis,
    completion: str,
    change: str,
) -> None:
    sub = broker.subscriber("topic")
    await broker.connect()
    store = broker.config.broker_config.store
    payload = b'{"b": "zz"}' if completion == "decode" else b"\x00\xffsame"
    tl_key = f"{store.timeline_key}:topic"
    pl_key = f"{store.payloads_key}:topic"
    try:
        await store.schedule("topic", "K", payload, 100)
        first = await store.claim("topic", "K", 100, 10)
        assert first is not None
        message = await TimerParser(sub._config).parse_message(  # noqa: SLF001
            TimerMessage(type="timer", channel="topic", timer_id="K", data=first.payload, claim_token=first.token)
        )
        if change == "takeover":
            current = await store.claim("topic", "K", 111, 10)
            assert current is not None
            deadline = 121
        else:
            if change == "cancel_recreate":
                await store.remove("topic", "K")
            elif change == "cancel_all_recreate":
                assert await store.cancel_all("topic") == 1
            await store.schedule("topic", "K", payload, 200)
            deadline = 200
        if completion == "decode":
            with pytest.raises(ValueError, match="legacy timer envelope"):
                await message.decode()
        else:
            await getattr(message, completion)()
        assert await redis_client.zscore(tl_key, "K") == deadline
        assert await redis_client.hget(pl_key, "K") == payload
        assert await store.claim("topic", "K", deadline - 1, 10) is None
        retry = await store.claim("topic", "K", deadline, 10)
        assert retry is not None
        assert retry.payload == payload
        await store.commit("topic", "K", first.token)
        assert await store.is_pending("topic", "K")
        await store.commit("topic", "K", retry.token)
        assert not await store.is_pending("topic", "K")
        await store.commit("topic", "K", retry.token)
        assert await redis_client.hget(pl_key, "K") is None
    finally:
        await store.cancel_all("topic")
        await broker.stop()


async def test_claims_survive_store_restart_and_adopt_legacy_records(broker: TimersBroker, redis_client: Redis) -> None:
    store = broker.config.broker_config.store
    tl = f"{store.timeline_key}:topic"
    pl = f"{store.payloads_key}:topic"
    claims = b"\xfffaststream-redis-timers:claims:" + tl.encode()
    try:
        await redis_client.zadd(tl, {"K": 100, "orphan": 100})
        await redis_client.hset(pl, "K", b"legacy")
        assert await store.claim("topic", "orphan", 100, 10) is None
        first, contested = await asyncio.gather(
            store.claim("topic", "K", 100, 10),
            store.claim("topic", "K", 100, 10),
        )
        owner = first or contested
        assert owner is not None
        assert (first is None) != (contested is None)
        restarted = TimerStore(ConnectionState(redis_client), store.timeline_key, store.payloads_key)
        await restarted.commit("topic", "K", owner.token)
        assert await redis_client.exists(tl, pl, claims) == 0
        assert await restarted.claim("topic", "missing", 100, 10) is None
        await restarted.schedule("topic", "K", b"new", 100)
        current = await restarted.claim("topic", "K", 100, 10)
        assert current is not None
        await restarted.remove("topic", "K")
        await restarted.commit("topic", "K", current.token)
        assert await redis_client.exists(tl, pl, claims) == 0
        await restarted.schedule("topic", "K", b"new", 100)
        assert await restarted.claim("topic", "K", 100, 10) is not None
        assert await restarted.cancel_all("topic") == 1
        assert await redis_client.exists(tl, pl, claims) == 0
    finally:
        await store.cancel_all("topic")


@pytest.mark.parametrize("replace_after_read", [False, True])
async def test_malformed_id_cleanup_preserves_newer_schedule(
    broker: TimersBroker,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    replace_after_read: bool,
) -> None:
    store = broker.config.broker_config.store
    tl = f"{store.timeline_key}:topic"
    pl = f"{store.payloads_key}:topic"
    claims = b"\xfffaststream-redis-timers:claims:" + tl.encode()
    bad_id = b"\xff"
    original = redis_client.zrangebyscore

    async def read_then_replace(*args, **kwargs):
        result = await original(*args, **kwargs)
        if replace_after_read:
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.zadd(tl, {bad_id: 200})
                pipe.hset(pl, bad_id, b"replacement")
                await pipe.execute()
        return result

    try:
        await redis_client.zadd(tl, {bad_id: 100})
        await redis_client.hset(pl, bad_id, b"invalid ID")
        monkeypatch.setattr(redis_client, "zrangebyscore", read_then_replace)
        assert await store.due("topic", 100, 1) == []
        if replace_after_read:
            assert await redis_client.zscore(tl, bad_id) == 200
            assert await redis_client.hget(pl, bad_id) == b"replacement"
        else:
            assert await redis_client.exists(tl, pl, claims) == 0
    finally:
        await store.cancel_all("topic")


async def test_payload_prefix_can_end_with_claims(broker: TimersBroker, redis_client: Redis) -> None:
    timeline = broker.config.broker_config.store.timeline_key
    configured = TimersBroker(redis_client, timeline_key=timeline, payloads_key=f"{timeline}_claims")
    store = configured.config.broker_config.store
    try:
        await store.schedule("app:topic", "K", b"\x00\xffpayload", 100)
        claim = await store.claim("app:topic", "K", 100, 10)
        assert claim is not None
        assert claim.payload == b"\x00\xffpayload"
        await store.commit("app:topic", "K", claim.token)
        assert not await store.is_pending("app:topic", "K")
    finally:
        await store.cancel_all("app:topic")


async def test_claim_metadata_cannot_alias_another_broker_timeline(broker: TimersBroker, redis_client: Redis) -> None:
    first = broker.config.broker_config.store
    second = TimerStore(ConnectionState(redis_client), f"{first.timeline_key}_claims", f"{first.payloads_key}_other")
    try:
        await second.schedule("app:topic", "K", b"other broker", 100)
        await first.schedule("app:topic", "K", b"first broker", 100)
        owner = await first.claim("app:topic", "K", 100, 10)
        assert owner is not None
        await first.commit("app:topic", "K", owner.token)
        await first.cancel_all("app:topic")
        other = await second.claim("app:topic", "K", 100, 10)
        assert other is not None
        assert other.payload == b"other broker"
        await second.commit("app:topic", "K", other.token)
    finally:
        await first.cancel_all("app:topic")
        await second.cancel_all("app:topic")


@pytest.mark.parametrize("completion", ["ack", "reject", "decode"])
async def test_valid_replacement_is_delivered_after_stale_completion(broker: TimersBroker, completion: str) -> None:
    delivered = asyncio.Event()
    received: list[bytes] = []
    sub = broker.subscriber("topic")

    @sub
    async def handler(body: bytes) -> None:
        received.append(body)
        delivered.set()

    await broker.connect()
    store = broker.config.broker_config.store
    try:
        await store.schedule("topic", "K", b'{"b": "zz"}' if completion == "decode" else b"old", 100)
        claim = await store.claim("topic", "K", 100, 10)
        assert claim is not None
        stale = await TimerParser(sub._config).parse_message(  # noqa: SLF001
            TimerMessage(type="timer", channel="topic", timer_id="K", data=claim.payload, claim_token=claim.token)
        )
        replacement = b"\x00\xffvalid replacement"
        await broker.publish(replacement, topic="topic", timer_id="K")
        if completion == "decode":
            with pytest.raises(ValueError, match="legacy timer envelope"):
                await stale.decode()
        else:
            await getattr(stale, completion)()
        async with broker:
            await asyncio.wait_for(delivered.wait(), 2)
        assert received == [replacement]
        assert not await store.is_pending("topic", "K")
    finally:
        await store.cancel_all("topic")
        await broker.stop()


async def test_upgrade_preserves_legacy_lease_until_expiry(broker: TimersBroker, redis_client: Redis) -> None:
    store = broker.config.broker_config.store
    tl = f"{store.timeline_key}:topic"
    pl = f"{store.payloads_key}:topic"
    try:
        await redis_client.zadd(tl, {"K": 200})
        await redis_client.hset(pl, "K", b"legacy leased payload")
        restarted = TimerStore(ConnectionState(redis_client), store.timeline_key, store.payloads_key)
        assert await restarted.due("topic", 199, 1) == []
        assert await restarted.claim("topic", "K", 199, 10) is None
        assert await redis_client.zscore(tl, "K") == 200
        assert await redis_client.hget(pl, "K") == b"legacy leased payload"
        assert await restarted.due("topic", 200, 1) == ["K"]
        claim = await restarted.claim("topic", "K", 200, 10)
        assert claim is not None
        assert claim.payload == b"legacy leased payload"
        assert await redis_client.zscore(tl, "K") == 210
        await restarted.commit("topic", "K", claim.token)
        assert not await restarted.is_pending("topic", "K")
        assert await redis_client.hget(pl, "K") is None
    finally:
        await store.cancel_all("topic")


@pytest.mark.parametrize(("writer", "survives"), [("legacy", False), ("fenced", True)])
async def test_only_fenced_publishers_protect_replacements(
    broker: TimersBroker,
    redis_client: Redis,
    writer: str,
    survives: bool,
) -> None:
    """Compatibility probe: legacy writers are unsafe during fenced processing."""
    store = broker.config.broker_config.store
    tl = f"{store.timeline_key}:topic"
    pl = f"{store.payloads_key}:topic"
    try:
        await store.schedule("topic", "K", b"old", 100)
        claim = await store.claim("topic", "K", 100, 10)
        assert claim is not None
        if writer == "legacy":
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.zadd(tl, {"K": 200})
                pipe.hset(pl, "K", b"replacement")
                await pipe.execute()
        else:
            await store.schedule("topic", "K", b"replacement", 200)
        assert await redis_client.zscore(tl, "K") == 200
        assert await redis_client.hget(pl, "K") == b"replacement"
        await store.commit("topic", "K", claim.token)
        assert await store.is_pending("topic", "K") is survives
        assert await redis_client.hget(pl, "K") == (b"replacement" if survives else None)
    finally:
        await store.cancel_all("topic")


@pytest.mark.parametrize(
    ("encoding", "encoding_errors", "leading_character"),
    [("latin-1", "strict", "\xff"), ("utf-8", "surrogateescape", "\udcff")],
)
async def test_incompatible_encoder_is_rejected_before_writing(
    broker: TimersBroker,
    redis_client: Redis,
    encoding: str,
    encoding_errors: str,
    leading_character: str,
) -> None:
    timeline = broker.config.broker_config.store.timeline_key
    payloads = leading_character + "faststream-redis-timers:claims:" + timeline
    client = Redis.from_url(REDIS_URL, encoding=encoding, encoding_errors=encoding_errors)
    try:
        await client.ping()
        with pytest.raises(ValueError, match=r"UTF-8.*strict"):
            TimersBroker(client, timeline_key=timeline, payloads_key=payloads)
        assert await redis_client.exists(f"{timeline}:topic") == 0
        assert await redis_client.exists(b"\xfffaststream-redis-timers:claims:" + f"{timeline}:topic".encode()) == 0
    finally:
        await client.delete(f"{timeline}:topic", b"\xfffaststream-redis-timers:claims:" + f"{timeline}:topic".encode())
        await client.aclose()  # ty: ignore[missing-attribute]


async def test_orphan_cleanup_removes_existing_ownership(broker: TimersBroker, redis_client: Redis) -> None:
    store = broker.config.broker_config.store
    tl = f"{store.timeline_key}:topic"
    pl = f"{store.payloads_key}:topic"
    claims = b"\xfffaststream-redis-timers:claims:" + tl.encode()
    try:
        await store.schedule("topic", "K", b"payload", 100)
        owner = await store.claim("topic", "K", 100, 10)
        assert owner is not None
        assert await redis_client.hget(claims, "K") == owner.token.encode()
        assert await redis_client.hdel(pl, "K") == 1
        assert await store.claim("topic", "K", 109, 10) is None
        assert await redis_client.hget(claims, "K") == owner.token.encode()
        assert await store.claim("topic", "K", 110, 10) is None
        assert await redis_client.exists(tl, pl, claims) == 0
        await store.commit("topic", "K", owner.token)
        assert await redis_client.exists(tl, pl, claims) == 0
    finally:
        await store.cancel_all("topic")


@pytest.mark.parametrize("encoding", ["utf-8", "UTF8", "utf_8"])
@pytest.mark.parametrize("decode_responses", [False, True])
async def test_utf8_encoder_aliases_support_fenced_binary_payloads(
    broker: TimersBroker,
    encoding: str,
    decode_responses: bool,
) -> None:
    client = Redis.from_url(REDIS_URL, encoding=encoding, decode_responses=decode_responses)
    original = broker.config.broker_config.store
    try:
        await client.ping()
        configured = TimersBroker(client, timeline_key=original.timeline_key, payloads_key=original.payloads_key)
        store = configured.config.broker_config.store
        await store.schedule("topic", "K", b"\x00\xffpayload", 100)
        claim = await store.claim("topic", "K", 100, 10)
        assert claim is not None
        assert claim.payload == b"\x00\xffpayload"
        await store.commit("topic", "K", claim.token)
        assert not await store.is_pending("topic", "K")
    finally:
        await original.cancel_all("topic")
        await client.aclose()  # ty: ignore[missing-attribute]
