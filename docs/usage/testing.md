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

## Notes

- `activate_in` is **ignored** in tests — messages are delivered immediately.
- `timer_id` is passed through normally and available in the handler via the message.
- `cancel_timer` / `publisher.cancel()` are no-ops in tests — since messages are delivered immediately, by the time you'd cancel, the handler has already run.
- `publisher.fetch_redis_timers()` always returns `[]` in tests — timers are delivered instantly, so there are never any pending entries.
- The fake producer uses the same JSON envelope format as the real one, so all serialization paths are exercised.

## pytest-asyncio configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```
