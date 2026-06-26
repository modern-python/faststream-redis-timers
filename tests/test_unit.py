import asyncio
import inspect
import logging
import warnings
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import faststream.asgi.factories.asyncapi.try_it_out
import pytest
from faststream._internal.parser import DefaultCodec
from faststream.exceptions import IncorrectState
from redis.asyncio.cluster import RedisCluster
from redis.exceptions import NoScriptError

from faststream_redis_timers import TestTimersBroker, TimersBroker
from faststream_redis_timers.broker import TimersParamsStorage
from faststream_redis_timers.configs import ConnectionState
from faststream_redis_timers.message import TimerStreamMessage
from faststream_redis_timers.publisher.producer import TimersProducer
from faststream_redis_timers.router import TimersRoute, TimersRoutePublisher, TimersRouter
from faststream_redis_timers.store import TimerStore, _eval_cached
from faststream_redis_timers.subscriber.schedule import (
    _MAX_ERROR_DELAY,
    _MAX_EXPONENT,
    PollSchedule,
    _default_jitter,
)


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


def test_broker_rejects_redis_cluster_client() -> None:
    fake_cluster = MagicMock(spec=RedisCluster)
    with pytest.raises(TypeError, match="RedisCluster"):
        TimersBroker(fake_cluster)


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


async def test_timer_stream_message_ack_without_remove_is_noop() -> None:
    # _remove=None means ack/reject skip the store call (no thunk to call).
    msg = TimerStreamMessage(
        raw_message={"type": "timer", "channel": "topic", "timer_id": "id", "data": b""},
        body=b"data",
        headers={},
        content_type=None,
        message_id="id",
        correlation_id="id",
        _remove=None,
    )
    await msg.ack()  # must not raise; covers the `if self._remove is None: return` branch


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


# --- start_timeout (B6) ---


def test_broker_start_timeout_propagates_to_config() -> None:
    broker = TimersBroker(AsyncMock(), start_timeout=7.5)
    assert broker.config.broker_config.start_timeout == 7.5


def test_broker_start_timeout_default_is_three_seconds() -> None:
    broker = TimersBroker(AsyncMock())
    assert broker.config.broker_config.start_timeout == 3.0


# --- duplicate subscriber warning (U9) ---


def test_duplicate_subscriber_warns() -> None:
    broker = TimersBroker(AsyncMock())

    @broker.subscriber("same")
    async def first(body: str) -> None: ...

    with pytest.warns(UserWarning, match="Duplicate subscriber"):

        @broker.subscriber("same")
        async def second(body: str) -> None: ...


# --- _consume start_signal fallback (covers finally-branch) ---


async def test_consume_sets_start_signal_when_ping_returns_false() -> None:
    """If client.ping() returns falsy, start_signal is set by the finally branch on first poll."""
    client = AsyncMock()
    client.ping.return_value = False
    client.zrangebyscore.return_value = []
    broker = TimersBroker(client, start_timeout=2.0)

    @broker.subscriber("topic", polling_interval=0.05)
    async def handler(body: str) -> None: ...

    async with broker:
        await asyncio.sleep(0.05)


# --- topic must be non-empty (B8) ---


async def test_publish_rejects_empty_topic() -> None:
    broker = TimersBroker(AsyncMock())
    with pytest.raises(ValueError, match="topic must be a non-empty string"):
        await broker.publish("msg", topic="")


async def test_cancel_timer_rejects_empty_topic() -> None:
    broker = TimersBroker(AsyncMock())
    with pytest.raises(ValueError, match="topic must be a non-empty string"):
        await broker.cancel_timer("", "id")


async def test_has_pending_rejects_empty_topic() -> None:
    broker = TimersBroker(AsyncMock())
    with pytest.raises(ValueError, match="topic must be a non-empty string"):
        await broker.has_pending("", "id")


async def test_get_pending_timers_rejects_empty_topic() -> None:
    broker = TimersBroker(AsyncMock())
    with pytest.raises(ValueError, match="topic must be a non-empty string"):
        await broker.get_pending_timers("")


async def test_cancel_all_rejects_empty_topic() -> None:
    broker = TimersBroker(AsyncMock())
    with pytest.raises(ValueError, match="topic must be a non-empty string"):
        await broker.cancel_all("")


# --- error path log format (B6) ---


async def test_consume_logs_get_msgs_error_with_repr() -> None:
    """A Redis error during _get_msgs is logged at ERROR with `{e!r}` so the type and msg survive Sentry truncation."""
    client = AsyncMock()
    client.ping.return_value = True
    client.zrangebyscore.side_effect = ConnectionError("redis down")
    broker = TimersBroker(client, start_timeout=2.0)

    @broker.subscriber("topic", polling_interval=0.05)
    async def handler(body: str) -> None: ...

    sub = next(iter(broker._subscribers))  # noqa: SLF001
    log_calls: list[dict[str, object]] = []
    sub._log = MagicMock(side_effect=lambda **kwargs: log_calls.append(kwargs))  # noqa: SLF001

    async with broker:
        await asyncio.sleep(0.1)

    error_logs = [c for c in log_calls if c.get("log_level") == logging.ERROR]
    assert error_logs, "expected at least one ERROR log"
    msg = error_logs[0]["message"]
    assert isinstance(msg, str)
    assert "Message fetch error" in msg
    assert "ConnectionError('redis down')" in msg


async def test_claim_and_consume_logs_unhandled_error_with_repr() -> None:
    """An unhandled error inside the limiter block is logged with `{timer_id!r}` and `{e!r}`."""
    client = AsyncMock()
    broker = TimersBroker(client)
    sub = broker.subscriber("topic")
    await broker.connect()

    log_calls: list[dict[str, object]] = []
    sub._log = MagicMock(side_effect=lambda **kwargs: log_calls.append(kwargs))  # noqa: SLF001

    limiter = anyio.CapacityLimiter(1)
    timer_id = "timer-1"

    with patch.object(sub._outer_config.store, "claim", new=AsyncMock(side_effect=RuntimeError("boom"))):  # noqa: SLF001
        await sub._claim_and_consume(timer_id, 30, limiter, client)  # noqa: SLF001

    error_logs = [c for c in log_calls if c.get("log_level") == logging.ERROR]
    assert error_logs
    msg = error_logs[0]["message"]
    assert isinstance(msg, str)
    assert "'timer-1'" in msg
    assert "RuntimeError('boom')" in msg


# --- eval_cached NOSCRIPT fallback (O1) ---


async def test_eval_cached_falls_back_on_noscript() -> None:
    client = AsyncMock()
    client.execute_command.side_effect = [NoScriptError("NOSCRIPT"), b"ok"]
    client.script_load.return_value = "abc123"

    result = await _eval_cached(client, "return 1", "abc123", 0)

    assert result == b"ok"
    assert client.execute_command.await_count == 2
    client.script_load.assert_awaited_once_with("return 1")


def test_distinct_topics_do_not_warn() -> None:
    broker = TimersBroker(AsyncMock())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        @broker.subscriber("a")
        async def handler_a(body: str) -> None: ...

        @broker.subscriber("b")
        async def handler_b(body: str) -> None: ...

    assert not [w for w in caught if "Duplicate subscriber" in str(w.message)]


def test_timers_producer_satisfies_producer_proto_codec() -> None:
    """0.7's ProducerProto requires a `codec: CodecProto` attribute."""
    assert isinstance(TimersProducer.codec, DefaultCodec)


def test_create_publisher_fake_subscriber_is_instance_method() -> None:
    """0.7's TestBroker base declares the method as an instance method."""
    sig = inspect.signature(TestTimersBroker.create_publisher_fake_subscriber)
    assert next(iter(sig.parameters)) == "self"


# --- TimerStore ---


def test_timer_store_key_derivation() -> None:
    """Keys are f'{timeline_key}:{full_topic}' and f'{payloads_key}:{full_topic}'."""
    store = TimerStore(ConnectionState(), "tl", "pl")
    tl, pl = store._keys("my-topic")  # noqa: SLF001
    assert tl == "tl:my-topic"
    assert pl == "pl:my-topic"


async def test_timer_store_schedule() -> None:
    """schedule() writes timer_id→activation_ts in ZADD and timer_id→payload in HSET via pipeline."""
    client = AsyncMock()
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    pipe.execute = AsyncMock(return_value=[1, 1])
    client.pipeline = MagicMock(return_value=pipe)

    store = TimerStore(ConnectionState(client), "tl", "pl")
    await store.schedule("topic", "id-1", b"data", 1000.0)

    pipe.zadd.assert_called_once_with("tl:topic", {"id-1": 1000.0})
    pipe.hset.assert_called_once_with("pl:topic", "id-1", b"data")
    pipe.execute.assert_awaited_once()


async def test_timer_store_due_bytes_client() -> None:
    """due() decodes bytes IDs for a bytes-mode Redis client."""
    client = AsyncMock()
    client.zrangebyscore = AsyncMock(return_value=[b"timer-1", b"timer-2"])

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.due("topic", 1000.0, 10)

    assert result == ["timer-1", "timer-2"]
    client.zrangebyscore.assert_awaited_once_with("tl:topic", "-inf", 1000.0, start=0, num=10)


async def test_timer_store_due_str_client() -> None:
    """due() passes str IDs through unchanged for a str-mode Redis client."""
    client = AsyncMock()
    client.zrangebyscore = AsyncMock(return_value=["timer-1", "timer-2"])

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.due("topic", 1000.0, 10)

    assert result == ["timer-1", "timer-2"]


async def test_timer_store_due_empty() -> None:
    """due() returns an empty list when no timers are due."""
    client = AsyncMock()
    client.zrangebyscore = AsyncMock(return_value=[])

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.due("topic", 1000.0, 10)

    assert result == []


async def test_timer_store_due_non_utf8_self_heal() -> None:
    """due() removes non-UTF-8 members via COMMIT_LUA and excludes them from the result."""
    bad_id = b"\xff\xfe-broken"
    client = AsyncMock()
    client.zrangebyscore = AsyncMock(return_value=[bad_id, b"good-id"])

    store = TimerStore(ConnectionState(client), "tl", "pl")

    with patch("faststream_redis_timers.store._eval_cached", new=AsyncMock(return_value=None)) as mock_eval:
        result = await store.due("topic", 1000.0, 5)

    assert result == ["good-id"]
    mock_eval.assert_awaited_once()
    assert bad_id in mock_eval.call_args.args


async def test_timer_store_claim_found() -> None:
    """claim() returns the payload bytes when the timer is successfully claimed."""
    client = AsyncMock()
    payload = b"timer-payload"

    store = TimerStore(ConnectionState(client), "tl", "pl")

    with patch("faststream_redis_timers.store._eval_cached", new=AsyncMock(return_value=payload)) as mock_eval:
        result = await store.claim("topic", "id-1", 1000.0, 30)

    assert result == payload
    # claim_score = now + lease_ttl = 1000.0 + 30 = 1030.0
    assert 1030.0 in mock_eval.call_args.args


async def test_timer_store_claim_contested() -> None:
    """claim() returns None when the timer is already leased or canceled."""
    client = AsyncMock()

    store = TimerStore(ConnectionState(client), "tl", "pl")

    with patch("faststream_redis_timers.store._eval_cached", new=AsyncMock(return_value=None)):
        result = await store.claim("topic", "id-1", 1000.0, 30)

    assert result is None


async def test_timer_store_remove() -> None:
    """remove() calls COMMIT_LUA for both the timeline and payloads keys."""
    client = AsyncMock()

    store = TimerStore(ConnectionState(client), "tl", "pl")

    with patch("faststream_redis_timers.store._eval_cached", new=AsyncMock(return_value=None)) as mock_eval:
        await store.remove("topic", "id-1")

    mock_eval.assert_awaited_once()
    args = mock_eval.call_args.args
    assert "tl:topic" in args
    assert "pl:topic" in args
    assert "id-1" in args


async def test_timer_store_pending_no_before() -> None:
    """pending() with no before= uses '+inf' as the score ceiling (all pending timers)."""
    client = AsyncMock()
    client.zrangebyscore = AsyncMock(return_value=["id-1", "id-2"])

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.pending("topic")

    assert result == ["id-1", "id-2"]
    client.zrangebyscore.assert_awaited_once_with("tl:topic", "-inf", "+inf")


async def test_timer_store_pending_with_before() -> None:
    """pending() with before=float restricts results to timers due by that timestamp."""
    client = AsyncMock()
    client.zrangebyscore = AsyncMock(return_value=[])

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.pending("topic", before=500.0)

    assert result == []
    client.zrangebyscore.assert_awaited_once_with("tl:topic", "-inf", 500.0)


async def test_timer_store_pending_bytes_client() -> None:
    """pending() decodes bytes IDs for a bytes-mode Redis client."""
    client = AsyncMock()
    client.zrangebyscore = AsyncMock(return_value=[b"id-1", b"id-2"])

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.pending("topic")

    assert result == ["id-1", "id-2"]


async def test_timer_store_is_pending_true() -> None:
    """is_pending() returns True when ZSCORE returns a score (timer exists)."""
    client = AsyncMock()
    client.zscore = AsyncMock(return_value=1000.0)

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.is_pending("topic", "id-1")

    assert result is True
    client.zscore.assert_awaited_once_with("tl:topic", "id-1")


async def test_timer_store_is_pending_false() -> None:
    """is_pending() returns False when ZSCORE returns None (timer absent)."""
    client = AsyncMock()
    client.zscore = AsyncMock(return_value=None)

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.is_pending("topic", "id-1")

    assert result is False


async def test_timer_store_cancel_all() -> None:
    """cancel_all() UNLINKs both keys and returns the pre-removal ZCARD count."""
    client = AsyncMock()
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    pipe.execute = AsyncMock(return_value=[7, 1, 1])
    client.pipeline = MagicMock(return_value=pipe)

    store = TimerStore(ConnectionState(client), "tl", "pl")
    result = await store.cancel_all("topic")

    assert result == 7
    pipe.zcard.assert_called_once_with("tl:topic")
    pipe.unlink.assert_any_call("tl:topic")
    pipe.unlink.assert_any_call("pl:topic")
    pipe.execute.assert_awaited_once()


# --- PollSchedule ---


def test_poll_schedule_busy_returns_zero() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    assert sched.delay_after_fetch(1) == 0.0


def test_poll_schedule_busy_resets_idle_count() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    # ramp idle counter to 3
    sched.delay_after_fetch(0)
    sched.delay_after_fetch(0)
    sched.delay_after_fetch(0)
    # busy resets idle_count to 0
    sched.delay_after_fetch(1)
    # next idle call: idle_count becomes 1, returns base * 2**0 = 0.05
    result: float = sched.delay_after_fetch(0)
    assert result == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("call_count", "expected"),
    [
        (1, 0.05),
        (2, 0.10),
        (3, 0.20),
        (4, 0.40),
        (5, 0.80),
    ],
)
def test_poll_schedule_idle_ramp(call_count: int, expected: float) -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    result: float = 0.0
    for _ in range(call_count):
        result = sched.delay_after_fetch(0)
    assert result == pytest.approx(expected)


def test_poll_schedule_idle_caps_at_max_idle() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    # drive enough idle calls to saturate the counter and the cap
    for _ in range(200):
        sched.delay_after_fetch(0)
    result: float = sched.delay_after_fetch(0)
    assert result == 5.0


def test_poll_schedule_back_pressure_returns_base() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    result: float = sched.delay_after_fetch(-1)
    assert result == pytest.approx(0.05)


def test_poll_schedule_back_pressure_does_not_change_idle_count() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    # ramp idle_count to 3
    sched.delay_after_fetch(0)
    sched.delay_after_fetch(0)
    sched.delay_after_fetch(0)
    # back-pressure: idle_count stays at 3
    sched.delay_after_fetch(-1)
    # next idle: idle_count becomes 4 → 0.05 * 2**(4-1) = 0.05 * 8 = 0.40
    result: float = sched.delay_after_fetch(0)
    assert result == pytest.approx(0.05 * 2**3)


@pytest.mark.parametrize(
    ("call_count", "expected"),
    [
        (1, 1.0),
        (2, 2.0),
        (3, 4.0),
        (4, 8.0),
        (5, 16.0),
    ],
)
def test_poll_schedule_error_ramp(call_count: int, expected: float) -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    result: float = 0.0
    for _ in range(call_count):
        result = sched.delay_after_error()
    assert result == pytest.approx(expected)


def test_poll_schedule_error_caps_at_max_error_delay() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    for _ in range(200):
        sched.delay_after_error()
    result: float = sched.delay_after_error()
    assert result == _MAX_ERROR_DELAY


def test_poll_schedule_error_exponent_cap_no_overflow() -> None:
    # Drive well past _MAX_EXPONENT — counter caps, no OverflowError, delay stays at cap.
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    for _ in range(_MAX_EXPONENT + 50):
        sched.delay_after_error()
    result: float = sched.delay_after_error()
    assert result == _MAX_ERROR_DELAY


def test_poll_schedule_any_fetch_resets_error_attempt_idle_zero() -> None:
    # delay_after_fetch(0) resets error_attempt; next error() restarts at 1.0
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    sched.delay_after_error()
    sched.delay_after_error()
    sched.delay_after_error()
    sched.delay_after_fetch(0)
    result: float = sched.delay_after_error()
    assert result == pytest.approx(1.0)


def test_poll_schedule_any_fetch_resets_error_attempt_busy() -> None:
    # delay_after_fetch(1) resets error_attempt; next error() restarts at 1.0
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    sched.delay_after_error()
    sched.delay_after_error()
    sched.delay_after_fetch(1)
    result: float = sched.delay_after_error()
    assert result == pytest.approx(1.0)


def test_poll_schedule_any_fetch_resets_error_attempt_back_pressure() -> None:
    # delay_after_fetch(-1) resets error_attempt; next error() restarts at 1.0
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.0)
    sched.delay_after_error()
    sched.delay_after_error()
    sched.delay_after_fetch(-1)
    result: float = sched.delay_after_error()
    assert result == pytest.approx(1.0)


def test_poll_schedule_idle_jitter_low_bound() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 0.5)
    result: float = sched.delay_after_fetch(0)
    # idle_count=1 → base * 2**0 * 0.5 = 0.05 * 0.5 = 0.025
    assert result == pytest.approx(0.05 * 0.5)


def test_poll_schedule_idle_jitter_high_bound() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.5)
    result: float = sched.delay_after_fetch(0)
    # idle_count=1 → base * 2**0 * 1.5 = 0.05 * 1.5 = 0.075
    assert result == pytest.approx(0.05 * 1.5)


def test_poll_schedule_error_jitter_low_bound() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 0.5)
    result: float = sched.delay_after_error()
    # error_attempt=1 → 2**0 * 0.5 = 0.5
    assert result == pytest.approx(0.5)


def test_poll_schedule_error_jitter_high_bound() -> None:
    sched = PollSchedule(base=0.05, max_idle=5.0, jitter=lambda: 1.5)
    result: float = sched.delay_after_error()
    # error_attempt=1 → 2**0 * 1.5 = 1.5
    assert result == pytest.approx(1.5)


def test_poll_schedule_default_jitter_is_in_bounds() -> None:
    # Exercise _default_jitter (covers the random.uniform branch).
    for _ in range(20):
        value: float = _default_jitter()
        assert 0.5 <= value <= 1.5
