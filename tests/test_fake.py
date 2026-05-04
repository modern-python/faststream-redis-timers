from datetime import UTC, datetime, timedelta

import pytest

from faststream_redis_timers import ScheduledTimer, TestTimersBroker, TimersBroker


async def test_fake_broker_subscriber() -> None:
    broker = TimersBroker()
    result: list[str] = []

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        result.append(body)

    async with TestTimersBroker(broker) as tb:
        await tb.publish("hello", topic="topic")

    assert result == ["hello"]


async def test_fake_broker_publisher() -> None:
    broker = TimersBroker()
    result: list[str] = []

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        result.append(body)

    async with TestTimersBroker(broker):
        await broker.publisher("topic").publish("world")

    assert result == ["world"]


async def test_fake_broker_pre_registered_publisher_no_sub() -> None:
    """Publisher pre-registered before context: _fake_start creates a fake subscriber (is_real=False path)."""
    broker = TimersBroker()
    pub = broker.publisher("no-sub-topic")  # pre-registered, no matching subscriber

    async with TestTimersBroker(broker):
        await pub.publish("msg")


async def test_fake_broker_pre_registered_publisher_with_sub() -> None:
    """Publisher + subscriber both pre-registered: _fake_start finds real subscriber (is_real=True path)."""
    broker = TimersBroker()
    result: list[str] = []
    pub = broker.publisher("topic")  # pre-registered

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        result.append(body)

    async with TestTimersBroker(broker):
        await pub.publish("hi")

    assert result == ["hi"]


async def test_fake_broker_cancel_is_noop() -> None:
    broker = TimersBroker()
    async with TestTimersBroker(broker):
        await broker.cancel_timer("topic", "any-id")
        await broker.publisher("topic").cancel("any-id")


async def test_request_raises() -> None:
    broker = TimersBroker()
    async with TestTimersBroker(broker):
        with pytest.raises(NotImplementedError):
            await broker.request("x", "y")


async def test_publish_batch_raises() -> None:
    broker = TimersBroker()
    async with TestTimersBroker(broker):
        with pytest.raises(NotImplementedError):
            await broker.publish_batch()


async def test_fake_broker_fetch_redis_timers_returns_empty() -> None:
    broker = TimersBroker()
    pub = broker.publisher("topic")
    async with TestTimersBroker(broker):
        result = await pub.fetch_redis_timers(datetime.now(tz=UTC))
    assert result == []


async def test_fake_broker_inspection_methods_report_no_pending() -> None:
    """Inside TestTimersBroker, messages deliver immediately, so the inspection
    methods must report "nothing pending" — not lie via unstubbed AsyncMock."""
    broker = TimersBroker()

    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with TestTimersBroker(broker):
        await broker.publish("hi", topic="topic", timer_id="t-1")
        assert await broker.has_pending("topic", "t-1") is False
        assert await broker.get_pending_timers("topic") == []
        assert await broker.cancel_all("topic") == 0


# --- scheduled_timers inspection (U8) ---


async def test_scheduled_timers_records_publish() -> None:
    broker = TimersBroker()

    @broker.subscriber("reminders")
    async def handler(body: str) -> None: ...

    test_broker = TestTimersBroker(broker)
    async with test_broker:
        await broker.publish("hi", topic="reminders", timer_id="t-1")

    assert len(test_broker.scheduled_timers) == 1
    record = test_broker.scheduled_timers[0]
    assert record.topic == "reminders"
    assert record.timer_id == "t-1"
    assert record.body == "hi"


async def test_scheduled_timers_captures_activate_at() -> None:
    broker = TimersBroker()

    @broker.subscriber("reminders")
    async def handler(body: str) -> None: ...

    target = datetime.now(tz=UTC) + timedelta(days=7)
    test_broker = TestTimersBroker(broker)
    async with test_broker:
        await broker.publish("call dentist", topic="reminders", timer_id="t-1", activate_at=target)

    assert test_broker.scheduled_timers[0].activate_at == target


async def test_scheduled_timers_captures_correlation_and_headers() -> None:
    broker = TimersBroker()

    @broker.subscriber("orders")
    async def handler(body: dict) -> None: ...

    test_broker = TestTimersBroker(broker)
    async with test_broker:
        await broker.publish(
            {"order_id": 1},
            topic="orders",
            timer_id="t-1",
            correlation_id="trace-abc",
            headers={"x-tenant": "acme"},
        )

    assert test_broker.scheduled_timers == [
        ScheduledTimer(
            topic="orders",
            timer_id="t-1",
            activate_at=test_broker.scheduled_timers[0].activate_at,
            body={"order_id": 1},
            correlation_id="trace-abc",
            headers={"x-tenant": "acme"},
        )
    ]


async def test_scheduled_timers_records_multiple_in_order() -> None:
    broker = TimersBroker()

    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    test_broker = TestTimersBroker(broker)
    async with test_broker:
        await broker.publish("a", topic="topic", timer_id="ta")
        await broker.publish("b", topic="topic", timer_id="tb")
        await broker.publish("c", topic="topic", timer_id="tc")

    assert [s.timer_id for s in test_broker.scheduled_timers] == ["ta", "tb", "tc"]


async def test_scheduled_timers_empty_initially() -> None:
    broker = TimersBroker()
    test_broker = TestTimersBroker(broker)
    async with test_broker:
        pass
    assert test_broker.scheduled_timers == []
