"""Sentinel failover drills. Run via ``just test-dr``, one fresh cluster per scenario."""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel

from faststream_redis_timers import TimersBroker


SENTINELS = [
    (host, int(port)) for host, port in (s.split(":") for s in os.environ.get("SENTINELS", "").split(",") if s)
]
SERVICE = "mymaster"
DOCKER_SOCKET = "/var/run/docker.sock"
PRIMARY_CONTAINER = "timers-dr-primary"
PRIMARY_HOST = "redis-primary"
TOPIC = "dr"
BEFORE = 50
DURING = 50
AFTER = 50
DURING_SPREAD_SECONDS = 10.0
LEASE_TTL_SECONDS = 5
RECOVERY_BUDGET_SECONDS = 90.0
PUBLISH_ATTEMPT_TIMEOUT_SECONDS = 5.0
TEST_BUDGET_SECONDS = 240.0

pytestmark = pytest.mark.skipif(not SENTINELS, reason="needs the docker-compose.dr.yml cluster")


async def _docker(method: str, path: str) -> None:
    reader, writer = await asyncio.open_unix_connection(DOCKER_SOCKET)
    writer.write(f"{method} {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode())
    await writer.drain()
    status_line = await reader.readline()
    writer.close()
    assert int(status_line.split(b" ", 2)[1]) < 300, status_line.decode(errors="replace")


async def _kill_primary() -> None:
    await _docker("POST", f"/containers/{PRIMARY_CONTAINER}/kill")


async def _pause_primary() -> None:
    """Freeze the primary: its name resolves and the kernel accepts connects, but nothing ever answers."""
    await _docker("POST", f"/containers/{PRIMARY_CONTAINER}/pause")


async def _wait_until(predicate: Callable[[], bool], *, deadline: float, what: str) -> None:
    while not predicate():
        if time.monotonic() > deadline:
            msg = f"timed out waiting for {what}"
            raise AssertionError(msg)
        await asyncio.sleep(0.1)


async def _wait_sentinels_see_replica() -> None:
    deadline = time.monotonic() + 30
    for host, port in SENTINELS:
        sentinel = Redis(host=host, port=port, decode_responses=True)
        try:
            while not await sentinel.sentinel_slaves(SERVICE):
                assert time.monotonic() < deadline, f"{host} never discovered the replica"
                await asyncio.sleep(0.5)
        finally:
            await sentinel.aclose()  # ty: ignore[unresolved-attribute]


async def _wait_failed_over(deadline: float) -> None:
    while True:
        sentinel_client = Redis(host=SENTINELS[0][0], port=SENTINELS[0][1], decode_responses=True)
        try:
            address = await sentinel_client.sentinel_get_master_addr_by_name(SERVICE)
        finally:
            await sentinel_client.aclose()  # ty: ignore[unresolved-attribute]
        if address and address[0] != PRIMARY_HOST:
            return
        assert time.monotonic() < deadline, "sentinels never promoted the replica"
        await asyncio.sleep(0.2)


async def _publish(broker: TimersBroker, n: int, activate_in: timedelta = timedelta(0)) -> None:
    await broker.publish({"n": n}, topic=TOPIC, timer_id=f"t-{n}", activate_in=activate_in)


async def _publish_until_accepted(broker: TimersBroker, n: int, deadline: float) -> None:
    while True:
        try:
            async with asyncio.timeout(PUBLISH_ATTEMPT_TIMEOUT_SECONDS):
                await _publish(broker, n)
        except Exception:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(0.5)
        else:
            return


@pytest.mark.parametrize("fail_primary", [_kill_primary, _pause_primary], ids=["kill", "pause"])
async def test_timers_survive_failover(fail_primary: Callable[[], Awaitable[None]]) -> None:
    sentinel = Sentinel(SENTINELS)
    client = sentinel.master_for(SERVICE)
    broker = TimersBroker(client)
    handled_at: dict[int, float] = {}
    deliveries: list[int] = []

    @broker.subscriber(TOPIC, lease_ttl=LEASE_TTL_SECONDS)
    async def handle(body: dict[str, int]) -> None:
        deliveries.append(body["n"])
        handled_at.setdefault(body["n"], time.monotonic())

    await _wait_sentinels_see_replica()
    async with asyncio.timeout(TEST_BUDGET_SECONDS), broker:
        for n in range(BEFORE):
            await _publish(broker, n)
        await _wait_until(
            lambda: len(handled_at) == BEFORE,
            deadline=time.monotonic() + 30,
            what="pre-failover timers",
        )
        step = DURING_SPREAD_SECONDS / DURING
        for i, n in enumerate(range(BEFORE, BEFORE + DURING)):
            await _publish(broker, n, activate_in=timedelta(seconds=1 + i * step))
        assert await client.execute_command("WAIT", 1, 5000) == 1, "replica did not acknowledge the writes"

        failed_at = time.monotonic()
        await fail_primary()
        deadline = failed_at + RECOVERY_BUDGET_SECONDS
        await _wait_failed_over(deadline)
        promoted = time.monotonic() - failed_at
        total = BEFORE + DURING + AFTER
        for n in range(BEFORE + DURING, total):
            await _publish_until_accepted(broker, n, deadline)
        publish_recovered = time.monotonic() - failed_at
        await _wait_until(
            lambda: len(handled_at) == total,
            deadline=deadline,
            what="post-failover timers",
        )
        subscriber_recovered = max(handled_at[n] for n in range(BEFORE, total)) - failed_at

        while leftover := await broker.get_pending_timers(TOPIC):
            assert time.monotonic() < deadline, f"timers never acked: {leftover}"
            await asyncio.sleep(0.5)

    print(  # noqa: T201
        f"\npromoted {promoted:.1f}s, publish recovered {publish_recovered:.1f}s, "
        f"subscriber recovered {subscriber_recovered:.1f}s, redeliveries {len(deliveries) - len(handled_at)}",
    )
    await client.aclose()  # ty: ignore[unresolved-attribute]
