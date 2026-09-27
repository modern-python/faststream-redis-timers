import asyncio
import json
import logging
import os
import time
import uuid

import pytest
from faststream import Context
from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker
from faststream_redis_timers.envelope import TimerMessageFormat


REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


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


async def test_envelope_size_smaller_than_legacy() -> None:
    body = b"x" * 1024
    new = await TimerMessageFormat.encode(
        message=body,
        reply_to=None,
        headers=None,
        correlation_id="c-1",
    )
    legacy = json.dumps({"b": body.hex(), "ct": "application/octet-stream"}).encode()
    assert len(new) < len(legacy)
    # New format should be roughly body size (1024) + small header overhead
    assert len(new) < len(body) + 200


def test_non_json_payload_starting_with_brace_parses_as_raw_body() -> None:
    assert TimerMessageFormat.parse(b"{not json") == (b"{not json", {})


@pytest.mark.parametrize("envelope", [b'{"b": "zz"}', b'{"b": 12}', b'{"b": null}'])
def test_legacy_envelope_with_non_hex_body_is_rejected(envelope: bytes) -> None:
    with pytest.raises(ValueError, match="legacy timer envelope"):
        TimerMessageFormat.parse(envelope)


async def test_works_with_decode_responses_true() -> None:
    """A Redis client created with decode_responses=True must not break payload parsing."""
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception:  # noqa: BLE001  # pragma: no cover - runs only when Redis is unreachable
        await client.aclose()  # ty: ignore[unresolved-attribute]
        return

    suffix = uuid.uuid4().hex
    broker = TimersBroker(
        client,
        timeline_key=f"decstr_tl_{suffix}",
        payloads_key=f"decstr_pl_{suffix}",
    )

    seen: list[dict] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: dict) -> None:
        seen.append(body)
        event.set()

    payload = {"chat_id": "abc", "message_text": "Ок", "message_id": 3056}
    try:
        async with broker:
            await broker.publish(payload, topic="topic", timer_id="3056")
            await asyncio.wait_for(event.wait(), timeout=5.0)
    finally:
        await client.aclose()  # ty: ignore[unresolved-attribute]

    assert seen == [payload]


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


async def test_legacy_envelope_with_non_hex_body_is_removed_and_logged_once(
    redis_client: Redis, caplog: pytest.LogCaptureFixture
) -> None:
    suffix = uuid.uuid4().hex
    broker = TimersBroker(
        redis_client,
        timeline_key=f"corrupt_tl_{suffix}",
        payloads_key=f"corrupt_pl_{suffix}",
        logger=logging.getLogger(f"corrupt-{suffix}"),
    )
    timeline_key = f"corrupt_tl_{suffix}:topic"
    payloads_key = f"corrupt_pl_{suffix}:topic"

    await redis_client.zadd(timeline_key, {"old-timer": time.time() - 1})
    await redis_client.hset(payloads_key, "old-timer", b'{"b": "zz"}')

    seen: list[bytes] = []

    @broker.subscriber("topic")
    async def handler(body: bytes) -> None:  # pragma: no cover - never invoked; the parser rejects the timer
        seen.append(body)

    with caplog.at_level(logging.ERROR, logger=f"corrupt-{suffix}"):
        async with broker:
            await asyncio.sleep(0.3)

    assert seen == []
    assert await redis_client.zscore(timeline_key, "old-timer") is None
    assert not await redis_client.hexists(payloads_key, "old-timer")
    removals = [record for record in caplog.records if "removed" in record.getMessage()]
    assert len(removals) == 1
    assert "'old-timer'" in removals[0].getMessage()
