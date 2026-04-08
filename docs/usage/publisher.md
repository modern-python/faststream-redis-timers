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

The `publish()` method on a publisher accepts:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `message` | — | The message body (any serializable value) |
| `timer_id` | auto UUID | Unique ID for the timer — use for idempotency |
| `activate_in` | `timedelta(0)` | Delay before delivery (fires immediately if 0) |
| `correlation_id` | auto UUID | Correlation ID for tracing |

## Cancelling timers via a publisher

Publishers expose a `cancel(timer_id)` method that cancels a pending timer on the same topic. This is a no-op if the timer has already fired or does not exist:

```python
pub = broker.publisher("invoices")

await pub.publish("INV-001", timer_id="invoice-INV-001-due", activate_in=timedelta(days=30))

# Later — cancel the timer via the publisher
await pub.cancel("invoice-INV-001-due")
```
