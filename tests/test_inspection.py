from datetime import UTC, datetime, timedelta

from faststream_redis_timers import TimersBroker


async def test_has_pending_true_for_scheduled_timer(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with broker:
        await broker.publish("hi", topic="topic", timer_id="t-1", activate_in=timedelta(hours=1))
        assert await broker.has_pending("topic", "t-1") is True


async def test_has_pending_false_for_unknown_timer(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with broker:
        assert await broker.has_pending("topic", "never-scheduled") is False


async def test_has_pending_false_after_cancel(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with broker:
        await broker.publish("hi", topic="topic", timer_id="t-1", activate_in=timedelta(hours=1))
        await broker.cancel_timer("topic", "t-1")
        assert await broker.has_pending("topic", "t-1") is False


async def test_get_pending_timers_lists_scheduled(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with broker:
        await broker.publish("a", topic="topic", timer_id="t-a", activate_in=timedelta(hours=1))
        await broker.publish("b", topic="topic", timer_id="t-b", activate_in=timedelta(hours=2))
        ids = await broker.get_pending_timers("topic")
    assert set(ids) == {"t-a", "t-b"}


async def test_get_pending_timers_before_filter(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with broker:
        await broker.publish("a", topic="topic", timer_id="t-a", activate_in=timedelta(hours=1))
        await broker.publish("b", topic="topic", timer_id="t-b", activate_in=timedelta(hours=10))
        cutoff = datetime.now(tz=UTC) + timedelta(hours=2)
        ids = await broker.get_pending_timers("topic", before=cutoff)
    assert ids == ["t-a"]


async def test_get_pending_timers_empty_topic(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with broker:
        assert await broker.get_pending_timers("topic") == []


async def test_cancel_all_removes_pending(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with broker:
        await broker.publish("a", topic="topic", timer_id="t-a", activate_in=timedelta(hours=1))
        await broker.publish("b", topic="topic", timer_id="t-b", activate_in=timedelta(hours=2))
        removed = await broker.cancel_all("topic")
        assert removed == 2
        assert await broker.get_pending_timers("topic") == []


async def test_cancel_all_empty_topic_returns_zero(broker: TimersBroker) -> None:
    @broker.subscriber("topic")
    async def handler(body: str) -> None: ...

    async with broker:
        assert await broker.cancel_all("topic") == 0


async def test_cancel_all_isolates_topics(broker: TimersBroker) -> None:
    @broker.subscriber("a")
    async def handler_a(body: str) -> None: ...

    @broker.subscriber("b")
    async def handler_b(body: str) -> None: ...

    async with broker:
        await broker.publish("x", topic="a", timer_id="ta-1", activate_in=timedelta(hours=1))
        await broker.publish("y", topic="b", timer_id="tb-1", activate_in=timedelta(hours=1))
        removed_a = await broker.cancel_all("a")
        assert removed_a == 1
        assert await broker.has_pending("b", "tb-1") is True
