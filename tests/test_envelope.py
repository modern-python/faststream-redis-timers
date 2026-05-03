import asyncio
import json
import time
import uuid

from faststream import Context
from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker
from faststream_redis_timers.envelope import TimerMessageFormat


async def test_correlation_id_propagates(broker: TimersBroker) -> None:
    seen: list[tuple[str, str]] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(
        body: str,
        correlation_id: str = Context("message.correlation_id"),
    ) -> None:
        seen.append((body, correlation_id))
        event.set()

    async with broker:
        await broker.publish("hi", topic="topic", correlation_id="trace-123")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert seen == [("hi", "trace-123")]


async def test_correlation_id_defaults_to_timer_id(broker: TimersBroker) -> None:
    seen: list[tuple[str, str, str]] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(
        body: str,
        message_id: str = Context("message.message_id"),
        correlation_id: str = Context("message.correlation_id"),
    ) -> None:
        seen.append((body, message_id, correlation_id))
        event.set()

    async with broker:
        await broker.publish("hi", topic="topic", timer_id="explicit-id")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert seen == [("hi", "explicit-id", "explicit-id")]


async def test_headers_propagate(broker: TimersBroker) -> None:
    seen: list[tuple[str, str]] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(
        body: str,
        x_tenant: str = Context("message.headers.x-tenant"),
    ) -> None:
        seen.append((body, x_tenant))
        event.set()

    async with broker:
        await broker.publish("hi", topic="topic", headers={"x-tenant": "acme"})
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert seen == [("hi", "acme")]


async def test_envelope_binary_safe(broker: TimersBroker) -> None:
    """Body containing null bytes, high bits, and a leading `{` round-trips intact."""
    nasty = b"{\x00\xff\x01\x02not-json\x7f\x80"
    seen: list[bytes] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: bytes) -> None:
        seen.append(body)
        event.set()

    async with broker:
        await broker.publish(nasty, topic="topic")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert seen == [nasty]


def test_envelope_size_smaller_than_legacy() -> None:
    body = b"x" * 1024
    new = TimerMessageFormat.encode(
        message=body,
        reply_to=None,
        headers=None,
        correlation_id="c-1",
    )
    legacy = json.dumps({"b": body.hex(), "ct": "application/octet-stream"}).encode()
    assert len(new) < len(legacy)
    # New format should be roughly body size (1024) + small header overhead
    assert len(new) < len(body) + 200


async def test_legacy_envelope_still_parses(redis_client: Redis) -> None:
    """A v0.x JSON-of-hex payload sitting in Redis is still delivered after upgrade."""
    suffix = uuid.uuid4().hex
    legacy_broker = TimersBroker(
        redis_client,
        timeline_key=f"legacy_tl_{suffix}",
        payloads_key=f"legacy_pl_{suffix}",
    )
    timeline_key = f"legacy_tl_{suffix}:topic"
    payloads_key = f"legacy_pl_{suffix}:topic"

    legacy_payload = json.dumps({"b": b'"hello"'.hex(), "ct": "application/json"}).encode()
    await redis_client.zadd(timeline_key, {"old-timer": time.time() - 1})
    await redis_client.hset(payloads_key, "old-timer", legacy_payload)

    seen: list[str] = []
    event = asyncio.Event()

    @legacy_broker.subscriber("topic")
    async def handler(body: str) -> None:
        seen.append(body)
        event.set()

    async with legacy_broker:
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert seen == ["hello"]
