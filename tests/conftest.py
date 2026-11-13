import os
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker


REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - runs only when Redis is unreachable
        await client.aclose()  # ty: ignore[missing-attribute]
        pytest.skip(f"Redis not available at {REDIS_URL}: {exc}")
    yield client
    await client.aclose()  # ty: ignore[missing-attribute]


@pytest.fixture
def broker(redis_client: Redis) -> TimersBroker:
    suffix = uuid.uuid4().hex
    return TimersBroker(
        redis_client,
        timeline_key=f"test_timeline_{suffix}",
        payloads_key=f"test_payloads_{suffix}",
    )
