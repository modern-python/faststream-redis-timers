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

Use `broker.publish()` with `activate_in` to schedule delivery:

```python
from datetime import timedelta

@app.after_startup
async def schedule_reminder() -> None:
    await broker.publish(
        "Call dentist",
        topic="reminders",
        activate_in=timedelta(hours=24),
    )
```

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
| `client` | `None` | `redis.asyncio.Redis` client instance |
| `timeline_key` | `timers_timeline` | Sorted set key name |
| `payloads_key` | `timers_payloads` | Hash key name |
| `graceful_timeout` | `15.0` | Seconds to wait for in-flight timers on shutdown |

## Timer IDs

Each timer has a unique `timer_id`. If you don't provide one, a UUID is generated automatically. You can supply your own to make a timer idempotent — publishing the same `timer_id` twice will overwrite the first:

```python
await broker.publish(
    "INV-001",
    topic="invoices",
    timer_id="invoice-INV-001-due",
    activate_in=timedelta(days=30),
)
```

## Cancelling timers

Cancel a pending timer before it fires using `broker.cancel_timer(topic, timer_id)`. This is a no-op if the timer has already fired or does not exist:

```python
await broker.publish(
    "INV-001",
    topic="invoices",
    timer_id="invoice-INV-001-due",
    activate_in=timedelta(days=30),
)

# Later — invoice was paid early, cancel the reminder
await broker.cancel_timer("invoices", "invoice-INV-001-due")
```
