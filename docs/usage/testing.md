# Testing

`faststream-redis-timers` provides `TestTimersBroker` — a test context manager that replaces the Redis producer with an in-memory fake that delivers messages synchronously. No Redis connection required.

## Basic test

```python
import pytest
from faststream_redis_timers import TestTimersBroker, TimersBroker


@pytest.mark.asyncio
async def test_reminder_handler() -> None:
    broker = TimersBroker()
    received: list[str] = []

    @broker.subscriber("reminders")
    async def handler(body: str) -> None:
        received.append(body)

    async with TestTimersBroker(broker) as tb:
        await tb.publish("hello", topic="reminders")

    assert received == ["hello"]
```

## Testing publishers

```python
import pytest
from faststream_redis_timers import TestTimersBroker, TimersBroker


@pytest.mark.asyncio
async def test_publisher() -> None:
    broker = TimersBroker()
    received: list[str] = []

    @broker.subscriber("reminders")
    async def handler(body: str) -> None:
        received.append(body)

    pub = broker.publisher("reminders")

    async with TestTimersBroker(broker):
        await pub.publish("world")

    assert received == ["world"]
```

## Inspecting scheduled timers

`TestTimersBroker.scheduled_timers` records every `publish()` call as a `ScheduledTimer` — useful for asserting that a unit of work scheduled the right follow-up without actually waiting for it.

```python
from datetime import UTC, datetime, timedelta
from faststream_redis_timers import TestTimersBroker, TimersBroker


async def test_order_schedules_reminder() -> None:
    broker = TimersBroker()

    @broker.subscriber("reminders")
    async def reminder_handler(body: str) -> None: ...

    test_broker = TestTimersBroker(broker)
    async with test_broker:
        await broker.publish(
            "follow up on order 42",
            topic="reminders",
            timer_id="order-42-followup",
            activate_at=datetime.now(tz=UTC) + timedelta(days=7),
        )

    assert len(test_broker.scheduled_timers) == 1
    record = test_broker.scheduled_timers[0]
    assert record.topic == "reminders"
    assert record.timer_id == "order-42-followup"
    assert record.body == "follow up on order 42"
```

Each `ScheduledTimer` has `topic`, `timer_id`, `activate_at`, `body`, `correlation_id`, and `headers`. Hold a reference to the `TestTimersBroker` outside the `async with` so the recorded list survives context exit.

## Notes

- `activate_at` / `activate_in` are **ignored** in tests — messages are delivered immediately. The intended firing time is preserved on `scheduled_timers[i].activate_at` for assertions.
- `timer_id` is passed through normally and available in the handler via the message.
- `cancel_timer` / `publisher.cancel()` are no-ops in tests — since messages are delivered immediately, by the time you'd cancel, the handler has already run.
- `publisher.fetch_redis_timers()` always returns `[]` in tests — timers are delivered instantly, so there are never any pending entries.
- The fake producer uses the same envelope format as the real one, so all serialization paths are exercised.

## pytest-asyncio configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```
