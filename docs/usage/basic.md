# Basic usage

## 1. Create a broker and app

```python
from faststream import FastStream
from faststream_redis_timers import TimersBroker
from redis.asyncio import Redis

client = Redis.from_url("redis://localhost:6379")
broker = TimersBroker(client)
app = FastStream(broker)
```

## 2. Define a subscriber

Subscribers work like any FastStream subscriber. Decorate a handler with `@broker.subscriber(topic)`:

```python
@broker.subscriber("reminders")
async def handle_reminder(message: str) -> None:
    print(f"Reminder fired: {message}")
```

## 3. Publish a timer

Use `broker.publish()` with `activate_in` (relative delay) or `activate_at` (absolute time) to schedule delivery. `publish()` returns the resolved `timer_id` — keep it for cancellation or inspection.

```python
from datetime import UTC, datetime, timedelta

@app.after_startup
async def schedule_reminder() -> None:
    # Relative — fire 24 hours from now
    await broker.publish(
        "Call dentist",
        topic="reminders",
        activate_in=timedelta(hours=24),
    )

    # Absolute — fire at a specific moment
    await broker.publish(
        "Quarterly review",
        topic="reminders",
        activate_at=datetime(2026, 6, 1, 9, tzinfo=UTC),
    )
```

`activate_at` must be timezone-aware. Passing both `activate_in` and `activate_at` raises `ValueError`.

The full example:

```python
from datetime import timedelta
from faststream import FastStream
from faststream_redis_timers import TimersBroker
from redis.asyncio import Redis

client = Redis.from_url("redis://localhost:6379")
broker = TimersBroker(client)
app = FastStream(broker)


@broker.subscriber("reminders")
async def handle_reminder(message: str) -> None:
    print(f"Reminder fired: {message}")


@app.after_startup
async def schedule_reminder() -> None:
    await broker.publish(
        "Call dentist",
        topic="reminders",
        activate_in=timedelta(hours=24),
    )
```

## Broker options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `client` | `None` | `redis.asyncio.Redis` client instance — the caller owns its lifecycle (the broker does not close it) |
| `timeline_key` | `timers_timeline` | Sorted set key name |
| `payloads_key` | `timers_payloads` | Hash key name |
| `start_timeout` | `3.0` | Seconds to wait for the subscriber's first Redis ping during startup |
| `graceful_timeout` | `15.0` | Seconds to wait for in-flight timers on shutdown |

`TimersBroker` does not call `.aclose()` on the supplied client — wrap it in
`async with Redis.from_url(...) as client:` (or your own `try/finally`) so the
connection is released when the application stops.

## Timer IDs

Each timer has a unique `timer_id`. If you don't provide one, a UUID is generated automatically. You can supply your own to make a timer idempotent — publishing the same `timer_id` twice will **overwrite the first** silently (no error, no warning). This is the right behavior for idempotent retry of `publish()` calls but a footgun if two unrelated callers pick the same ID. Namespace your IDs (e.g., `f"invoice-{invoice_id}-due"`) to avoid accidental collisions.

```python
await broker.publish(
    "INV-001",
    topic="invoices",
    timer_id="invoice-INV-001-due",
    activate_in=timedelta(days=30),
)
```

## Past activation times fire immediately

Both `activate_in=timedelta(seconds=-5)` and `activate_at=datetime.now(tz=UTC) - timedelta(seconds=5)` produce a timer scheduled in the past — the next subscriber poll picks it up and fires it immediately. No error is raised; this lets `activate_at` computations that take "marginally too long" still deliver instead of breaking. If you want strict scheduling, validate at the call site before publishing.

## Cancelling timers

Cancel a pending timer before it fires using `broker.cancel_timer(topic, timer_id)`. This is a no-op if the timer has already fired or does not exist. The `timer_id` returned from `publish()` is what you'd pass:

```python
timer_id = await broker.publish(
    "INV-001",
    topic="invoices",
    activate_in=timedelta(days=30),
)

# Later — invoice was paid early, cancel the reminder
await broker.cancel_timer("invoices", timer_id)
```

## Inspecting pending timers

Three broker methods let you inspect or bulk-cancel timers without poking Redis directly:

| Method | Returns | Use for |
|--------|---------|---------|
| `await broker.has_pending(topic, timer_id)` | `bool` | "is timer X still scheduled?" |
| `await broker.get_pending_timers(topic, before=None)` | `list[str]` | List pending IDs on *topic* — optionally filter to those due by *before* (a timezone-aware `datetime`) |
| `await broker.cancel_all(topic)` | `int` | Cancel every timer on *topic*; returns the number removed |

```python
from datetime import UTC, datetime, timedelta

# Quick existence check
if await broker.has_pending("invoices", "invoice-INV-001-due"):
    ...

# All pending timers on a topic
pending = await broker.get_pending_timers("invoices")

# Only those due in the next hour
soon = await broker.get_pending_timers(
    "invoices", before=datetime.now(tz=UTC) + timedelta(hours=1),
)

# Wipe a topic's queue (e.g., during a maintenance reset)
removed = await broker.cancel_all("invoices")
```

These methods only inspect/cancel timers in the queue — handlers that have already started running are unaffected.

## Debug logging

Set `log_level=logging.DEBUG` on `TimersBroker` to emit per-timer DEBUG lines: timers fetched per poll cycle, claim contested by another worker, and timer delivered to handler. Useful for diagnosing "my timer didn't fire".
