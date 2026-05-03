from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import faststream.asgi.factories.asyncapi.try_it_out
import pytest
from faststream.exceptions import IncorrectState

from faststream_redis_timers import TestTimersBroker, TimersBroker
from faststream_redis_timers.broker import TimersParamsStorage
from faststream_redis_timers.configs import ConnectionState
from faststream_redis_timers.message import TimerStreamMessage
from faststream_redis_timers.router import TimersRoute, TimersRoutePublisher, TimersRouter


# --- AsyncAPI try_it_out registry ---


def test_timers_broker_registered_in_try_it_out_registry() -> None:
    registry = faststream.asgi.factories.asyncapi.try_it_out._get_broker_registry()  # noqa: SLF001
    assert registry[TimersBroker] is TestTimersBroker


# --- ConnectionState ---


def test_connection_state_client_not_set_raises() -> None:
    state = ConnectionState()
    with pytest.raises(IncorrectState):
        _ = state.client


async def test_connection_state_connect_returns_client() -> None:
    client = AsyncMock()
    state = ConnectionState(client)
    result = await state.connect()
    assert result is client


async def test_connection_state_disconnect_is_noop() -> None:
    state = ConnectionState()
    await state.disconnect()  # must not raise


# --- TimersBrokerConfig ---


async def test_broker_config_connect_and_disconnect() -> None:
    client = AsyncMock()
    broker = TimersBroker(client)
    config = broker.config.broker_config
    await config.connect()
    await config.disconnect()


# --- TimersBroker.ping ---


async def test_broker_ping_without_client_returns_false() -> None:
    broker = TimersBroker()  # no client set
    assert await broker.ping() is False


async def test_broker_ping_when_redis_raises_returns_false() -> None:
    client = AsyncMock()
    client.ping.side_effect = ConnectionError("timeout")
    broker = TimersBroker(client)
    assert await broker.ping() is False


async def test_broker_ping_when_redis_returns_false() -> None:
    client = AsyncMock()
    client.ping.return_value = False
    broker = TimersBroker(client)
    assert await broker.ping() is False


async def test_broker_ping_success() -> None:
    client = AsyncMock()
    client.ping.return_value = True
    broker = TimersBroker(client)
    assert await broker.ping() is True


async def test_broker_ping_dead_task_returns_false() -> None:
    client = AsyncMock()
    client.ping.return_value = True
    broker = TimersBroker(client)
    sub = broker.subscriber("topic")
    dead_task = MagicMock()
    dead_task.done.return_value = True
    sub.tasks = [dead_task]
    assert await broker.ping() is False


async def test_broker_ping_live_task_returns_true() -> None:
    client = AsyncMock()
    client.ping.return_value = True
    broker = TimersBroker(client)
    sub = broker.subscriber("topic")
    live_task = MagicMock()
    live_task.done.return_value = False
    sub.tasks = [live_task]
    assert await broker.ping() is True


# --- TimersParamsStorage.get_logger (cache hit) ---


def test_params_storage_get_logger_is_cached() -> None:
    storage = TimersParamsStorage()
    context = MagicMock()
    logger1 = storage.get_logger(context=context)
    logger2 = storage.get_logger(context=context)  # cache hit → line 43
    assert logger1 is logger2


# --- Subscriber.get_one raises ---


async def test_subscriber_get_one_raises() -> None:
    broker = TimersBroker()
    sub = broker.subscriber("topic")
    with pytest.raises(NotImplementedError):
        await sub.get_one()


# --- Publisher.request raises ---


async def test_publisher_request_raises() -> None:
    broker = TimersBroker()
    pub = broker.publisher("topic")
    with pytest.raises(NotImplementedError):
        await pub.request("x")


# --- TimersSubscriberSpecification.name / get_schema ---


def test_subscriber_specification_name_and_schema() -> None:
    broker = TimersBroker()
    sub = broker.subscriber("my-topic")
    spec = sub.specification
    name = spec.name
    assert "my-topic" in name
    schema = spec.get_schema()
    assert schema  # non-empty dict


# --- TimersPublisherSpecification.name / get_schema ---


def test_publisher_specification_name_and_schema() -> None:
    broker = TimersBroker()
    pub = broker.publisher("my-topic")
    spec = pub.specification
    name = spec.name
    assert "my-topic" in name
    schema = spec.get_schema()
    assert schema  # non-empty dict


# --- TimerStreamMessage.nack ---


async def test_timer_stream_message_nack() -> None:
    # Timer cleanup happens in _get_msgs() before consume(); ack/nack/reject are no-ops.
    msg = TimerStreamMessage(
        raw_message={"type": "timer", "channel": "topic", "timer_id": "id", "data": b""},
        body=b"data",
        headers={},
        content_type=None,
        message_id="id",
        correlation_id="id",
    )
    await msg.nack()  # must not raise


# --- Subscriber._make_response_publisher ---


def test_subscriber_make_response_publisher() -> None:
    broker = TimersBroker()
    sub = broker.subscriber("topic")
    result = sub._make_response_publisher(MagicMock())  # noqa: SLF001
    assert result == ()


# --- TimersRouter, TimersRoute, TimersRoutePublisher ---


def test_timers_router_instantiation() -> None:
    router = TimersRouter(prefix="timers/")
    assert router is not None


def test_timers_route_and_route_publisher() -> None:
    async def handler(body: str) -> None: ...

    route = TimersRoute(handler, "my-topic")
    pub = TimersRoutePublisher("my-topic")
    assert route is not None
    assert pub is not None


# --- TimersPublisher.fetch_redis_timers ---


async def test_publisher_fetch_redis_timers_returns_matching() -> None:
    client = AsyncMock()
    client.zrangebyscore.return_value = [b"timer-1", b"timer-2"]
    broker = TimersBroker(client)
    pub = broker.publisher("my-topic")
    dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

    result = await pub.fetch_redis_timers(dt)

    assert result == [("my-topic", "timer-1"), ("my-topic", "timer-2")]
    client.zrangebyscore.assert_awaited_once()


async def test_publisher_fetch_redis_timers_empty() -> None:
    client = AsyncMock()
    client.zrangebyscore.return_value = []
    broker = TimersBroker(client)
    pub = broker.publisher("my-topic")
    dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

    result = await pub.fetch_redis_timers(dt)

    assert result == []


async def test_publisher_fetch_redis_timers_uses_correct_key() -> None:
    client = AsyncMock()
    client.zrangebyscore.return_value = []
    broker = TimersBroker(client, timeline_key="custom_timeline")
    pub = broker.publisher("orders")
    dt = datetime(2025, 6, 1, tzinfo=UTC)

    await pub.fetch_redis_timers(dt)

    key_used = client.zrangebyscore.call_args[0][0]
    assert key_used == "custom_timeline:orders"
