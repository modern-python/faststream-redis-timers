import asyncio
from datetime import timedelta

from faststream.response.publish_type import PublishType

from faststream_redis_timers import TimersBroker
from faststream_redis_timers.response import TimerPublishCommand


async def test_subscriber_receives_string(broker: TimersBroker) -> None:
    received: list[str] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        event.set()

    async with broker:
        await broker.publish("hello", topic="topic")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert received == ["hello"]


async def test_subscriber_receives_dict(broker: TimersBroker) -> None:
    received: list[dict] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: dict) -> None:
        received.append(body)
        event.set()

    async with broker:
        await broker.publish({"order_id": 42, "status": "due"}, topic="topic")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert received == [{"order_id": 42, "status": "due"}]


async def test_publisher_sends_message(broker: TimersBroker) -> None:
    received: list[str] = []
    event = asyncio.Event()
    pub = broker.publisher("topic")

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        event.set()

    async with broker:
        await pub.publish("from publisher")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert received == ["from publisher"]


async def test_publisher_internal_publish(broker: TimersBroker) -> None:
    """Calls publisher._publish() directly to cover the internal publish path."""
    received: list[str] = []
    event = asyncio.Event()
    pub = broker.publisher("topic")

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        event.set()

    async with broker:
        cmd = TimerPublishCommand(
            "via-internal",
            _publish_type=PublishType.PUBLISH,
            destination=pub.config.full_topic,
            timer_id="internal-id",
            activate_in=timedelta(0),
            correlation_id="corr-id",
        )
        await pub._publish(cmd, _extra_middlewares=())  # noqa: SLF001
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert received == ["via-internal"]


async def test_custom_timer_id(broker: TimersBroker) -> None:
    received: list[str] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        event.set()

    async with broker:
        await broker.publish("payload", topic="topic", timer_id="my-fixed-id")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert received == ["payload"]


async def test_timer_id_is_idempotent(broker: TimersBroker) -> None:
    """Publishing with the same timer_id twice overwrites — handler fires exactly once."""
    received: list[str] = []
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        event.set()

    async with broker:
        await broker.publish("first", topic="topic", timer_id="idem", activate_in=timedelta(hours=1))
        await broker.publish("second", topic="topic", timer_id="idem")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert received == ["second"]


async def test_multiple_timers_all_fire(broker: TimersBroker) -> None:
    received: list[str] = []
    count = 3
    event = asyncio.Event()

    @broker.subscriber("topic")
    async def handler(body: str) -> None:
        received.append(body)
        if len(received) >= count:
            event.set()

    async with broker:
        for i in range(count):
            await broker.publish(f"msg-{i}", topic="topic")
        await asyncio.wait_for(event.wait(), timeout=5.0)

    assert sorted(received) == ["msg-0", "msg-1", "msg-2"]
