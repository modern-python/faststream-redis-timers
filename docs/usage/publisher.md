# Publisher

Use `broker.publisher(topic)` to get a reusable publisher object. This is useful when you want to inject the publisher as a dependency or use it from inside a handler.

## Creating a publisher

```python
from faststream_redis_timers import TimersBroker
from redis.asyncio import Redis

client = Redis.from_url("redis://localhost:6379")
broker = TimersBroker(client)

reminder_publisher = broker.publisher("reminders")
```

## Publishing from a handler

```python
from datetime import timedelta
from faststream_redis_timers import TimersBroker
from redis.asyncio import Redis

client = Redis.from_url("redis://localhost:6379")
broker = TimersBroker(client)
reminder_publisher = broker.publisher("reminders")


@broker.subscriber("orders")
async def handle_order(order_id: str) -> None:
    # Schedule a follow-up reminder 7 days after the order
    await reminder_publisher.publish(
        f"Follow up on order {order_id}",
        activate_in=timedelta(days=7),
    )
```

## Publisher options

The `publish()` method on a publisher accepts the parameters below and returns the resolved `timer_id` (generated or provided):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `message` | — | The message body (any serializable value) |
| `timer_id` | auto UUID | Unique ID for the timer — use for idempotency |
| `activate_in` | `timedelta(0)` | Delay before delivery (fires immediately if 0) |
| `activate_at` | `None` | Absolute timezone-aware datetime to fire at. Mutually exclusive with `activate_in` |
| `correlation_id` | same as `timer_id` | Correlation ID for tracing — round-trips to the handler. Defaults to the resolved `timer_id` (which is itself an auto UUID when not supplied) |
| `headers` | `None` | `dict[str, Any]` of headers — round-trips to the handler |

!!! note "`correlation_id` defaults to `timer_id`"
    If you omit `correlation_id`, it falls back to the resolved `timer_id` —
    not a fresh UUID. When `timer_id` is also auto-generated, the two end up
    equal but each unique. When you supply your own `timer_id` (e.g.
    `"invoice-INV-001-due"`) for idempotent retries, omitting `correlation_id`
    means every retry of that timer carries the *same* correlation ID. Pass
    `correlation_id` explicitly if your tracing pipeline needs per-publish
    uniqueness.

!!! note "Past activation times fire immediately"
    `activate_in=timedelta(seconds=-5)` and `activate_at` set in the past both
    schedule the timer at a negative-relative score — the next subscriber poll
    picks it up and fires it. No error is raised; this lets `activate_at`
    computations that take "marginally too long" still deliver. If you want
    strict scheduling, validate at the call site before publishing.

### Tracing & headers example

```python
from faststream import Context
from faststream.message import StreamMessage

pub = broker.publisher("orders")

@broker.subscriber("orders")
async def handle(
    body: dict,
    correlation_id: str = Context("message.correlation_id"),
    tenant: str = Context("message.headers.x-tenant"),
) -> None:
    ...

await pub.publish(
    {"order_id": 42},
    correlation_id="trace-abc-123",
    headers={"x-tenant": "acme"},
)
```

## Cancelling timers via a publisher

Publishers expose a `cancel(timer_id)` method that cancels a pending timer on the same topic. This is a no-op if the timer has already fired or does not exist. Capture the `timer_id` from `publish()`:

```python
pub = broker.publisher("invoices")

timer_id = await pub.publish("INV-001", activate_in=timedelta(days=30))

# Later — cancel the timer via the publisher
await pub.cancel(timer_id)
```

## Inspecting pending timers

`fetch_redis_timers(dt)` returns all timers on this publisher's topic that are due by `dt` as a list of `(topic, timer_id)` tuples. This is useful in service tests to assert that timers were scheduled correctly without waiting for them to fire.

```python
from datetime import UTC, datetime, timedelta

pub = broker.publisher("invoices")
await pub.publish("INV-001", timer_id="invoice-INV-001-due", activate_in=timedelta(days=30))

# Assert the timer is scheduled
pending = await pub.fetch_redis_timers(datetime.now(tz=UTC) + timedelta(days=31))
assert ("invoices", "invoice-INV-001-due") in pending

# Timers not yet due are excluded
pending_now = await pub.fetch_redis_timers(datetime.now(tz=UTC))
assert pending_now == []
```

In `TestTimersBroker`, `fetch_redis_timers` always returns `[]` because messages are delivered immediately — there are no pending timers to inspect.
