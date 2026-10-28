import asyncio
import contextlib
import typing
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from faststream_redis_timers import TimersBroker
from faststream_redis_timers.router import TimersRoute, TimersRouter


class _FreezableProxy:
    """TCP proxy to Redis; ``freeze()`` silences every open connection while new ones still pass."""

    def __init__(self, target_host: str, target_port: int) -> None:
        self._target = (target_host, target_port)
        self._generation = 0
        self._never = asyncio.Event()
        self._writers: list[asyncio.StreamWriter] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self._server: asyncio.Server | None = None
        self.port = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    def freeze(self) -> None:
        self._generation += 1

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        for task in self._tasks:
            task.cancel()
        for writer in self._writers:
            writer.close()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _accept(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        upstream_reader, upstream_writer = await asyncio.open_connection(*self._target)
        self._writers += [client_writer, upstream_writer]
        generation = self._generation
        for reader, writer in ((client_reader, upstream_writer), (upstream_reader, client_writer)):
            task = asyncio.create_task(self._pipe(reader, writer, generation))
            self._tasks.add(task)

    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, generation: int) -> None:
        while data := await reader.read(65536):
            if generation != self._generation:
                await self._never.wait()
            writer.write(data)
            await writer.drain()


@pytest.fixture
async def proxy(redis_client: Redis) -> AsyncIterator[_FreezableProxy]:
    kwargs = redis_client.connection_pool.connection_kwargs
    proxy = _FreezableProxy(kwargs["host"], kwargs["port"])
    await proxy.start()
    yield proxy
    await proxy.stop()


@pytest.fixture
async def proxied_client(proxy: _FreezableProxy, redis_client: Redis) -> AsyncIterator[Redis]:
    db = redis_client.connection_pool.connection_kwargs.get("db", 0)
    client = Redis(host="127.0.0.1", port=proxy.port, db=db, socket_timeout=None, socket_connect_timeout=None)
    yield client
    with contextlib.suppress(Exception):
        async with asyncio.timeout(1):
            await client.aclose()  # ty: ignore[unresolved-attribute]


def _brokers(proxied_client: Redis, redis_client: Redis) -> tuple[TimersBroker, TimersBroker]:
    """Return a broker on the proxied client and a publisher on a direct one, sharing keys."""
    suffix = uuid.uuid4().hex
    timeline_key, payloads_key = f"ct_tl_{suffix}", f"ct_pl_{suffix}"
    return (
        TimersBroker(proxied_client, timeline_key=timeline_key, payloads_key=payloads_key),
        TimersBroker(redis_client, timeline_key=timeline_key, payloads_key=payloads_key),
    )


async def test_a_fetch_hung_on_a_silent_connection_is_abandoned(
    proxy: _FreezableProxy, proxied_client: Redis, redis_client: Redis
) -> None:
    broker, publisher = _brokers(proxied_client, redis_client)
    seen: list[str] = []
    delivered: dict[str, asyncio.Event] = {"before": asyncio.Event(), "after": asyncio.Event()}

    @broker.subscriber("topic", lease_ttl=1, max_polling_interval=0.1)
    async def handler(body: str) -> None:
        seen.append(body)
        delivered[body].set()

    async with broker, publisher:
        await publisher.publish("before", topic="topic")
        await asyncio.wait_for(delivered["before"].wait(), timeout=5)
        proxy.freeze()
        await asyncio.sleep(0.5)
        await publisher.publish("after", topic="topic")
        await asyncio.wait_for(delivered["after"].wait(), timeout=10)


async def test_an_ack_hung_on_a_silent_connection_frees_its_handler_slot(
    proxy: _FreezableProxy, proxied_client: Redis, redis_client: Redis
) -> None:
    broker, publisher = _brokers(proxied_client, redis_client)
    entered = asyncio.Event()
    release = asyncio.Event()
    after = asyncio.Event()

    @broker.subscriber("topic", lease_ttl=1, max_concurrent=1, max_polling_interval=0.1)
    async def handler(body: str) -> None:
        if body == "after":
            after.set()
            return
        entered.set()
        await release.wait()

    async with broker, publisher:
        await publisher.publish("before", topic="topic")
        await asyncio.wait_for(entered.wait(), timeout=5)
        proxy.freeze()
        release.set()
        await asyncio.sleep(0.2)
        await publisher.publish("after", topic="topic")
        await asyncio.wait_for(after.wait(), timeout=15)


def test_command_timeout_defaults_to_the_lease(broker: TimersBroker) -> None:
    subscriber = broker.subscriber("topic", lease_ttl=7)
    assert subscriber._config.timer_sub.effective_command_timeout == 7  # noqa: SLF001


def test_command_timeout_overrides_the_lease(broker: TimersBroker) -> None:
    subscriber = broker.subscriber("topic", lease_ttl=7, command_timeout=0.5)
    assert subscriber._config.timer_sub.effective_command_timeout == 0.5  # noqa: SLF001


def test_a_route_passes_command_timeout_through(broker: TimersBroker) -> None:
    async def handler(body: str) -> None: ...

    broker.include_router(TimersRouter(handlers=[TimersRoute(handler, "topic", lease_ttl=7, command_timeout=0.5)]))
    assert broker.subscribers[0]._config.timer_sub.effective_command_timeout == 0.5  # noqa: SLF001


@pytest.mark.parametrize(
    ("command_timeout", "match"),
    [
        (0, "must be > 0"),
        (-1, "must be > 0"),
        (float("inf"), "must be finite"),
        (float("nan"), "must be finite"),
        (8, "must be <= lease_ttl"),
    ],
)
def test_command_timeout_is_validated(broker: TimersBroker, command_timeout: typing.Any, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        broker.subscriber("topic", lease_ttl=7, command_timeout=command_timeout)
