# Subscriber

Use `@broker.subscriber(topic)` to register a handler for a topic.

## Basic example

```python
from faststream import FastStream
from faststream_redis_timers import TimersBroker
from redis.asyncio import Redis

client = Redis.from_url("redis://localhost:6379")
broker = TimersBroker(client)
app = FastStream(broker)


@broker.subscriber("reminders")
async def handle_reminder(body: str) -> None:
    print(f"Reminder fired: {body}")
```

## Body types

FastStream deserializes the message body into the annotated type. Any JSON-serializable type works:

```python
from dataclasses import dataclass


@dataclass
class Order:
    order_id: str
    amount: float


@broker.subscriber("orders")
async def handle_order(body: Order) -> None:
    print(f"Order {body.order_id} for {body.amount} is due")
```

## Accessing the timer ID

The `timer_id` is available as the message's `message_id`. Inject it via `Context`:

```python
from faststream import Context
from faststream_redis_timers import TimersBroker

broker = TimersBroker()


@broker.subscriber("invoices")
async def handle_invoice(
    body: str,
    timer_id: str = Context("message.message_id"),
) -> None:
    print(f"Timer {timer_id} fired: {body}")
```

## Subscriber options

Configure polling behaviour per subscriber:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `polling_interval` | `0.05` s | Base poll interval; the floor used when the queue has work |
| `max_polling_interval` | `5.0` s | Cap for adaptive idle backoff (doubles per empty cycle, ±50% jitter) |
| `max_concurrent` | `5` | Max handlers running in parallel; also caps fetch batch size per poll |
| `lease_ttl` | `30` s | How long a worker holds the lease before another worker may re-claim |

```python
@broker.subscriber(
    "high-priority",
    polling_interval=0.01,        # poll every 10ms when busy
    max_polling_interval=0.5,     # never sleep longer than 500ms when idle
    max_concurrent=20,            # up to 20 handlers may run in parallel
    lease_ttl=60,                 # hold lease for up to 60 seconds
)
async def handle_urgent(body: str) -> None: ...
```

The poll loop uses adaptive backoff: when there are no due timers, the next sleep doubles from `polling_interval` up to `max_polling_interval` and is multiplied by a random factor in `[0.5, 1.5]` to avoid thundering-herd bursts across worker fleets. The counter resets the moment a poll returns work. Worst-case delivery latency for a newly-published timer in a previously-idle queue is `max_polling_interval × 1.5`.

!!! warning "Handlers must be idempotent and concurrency-safe"
    A handler that runs longer than `lease_ttl`, or a worker that crashes after the handler ran but before the commit landed, may cause the timer to be delivered more than once. Design handlers to be safe under retry. Because `max_concurrent` invocations run in parallel, handlers must also be safe under concurrent execution (no unsynchronized shared state).

## Ack policy

The default ack policy is `NACK_ON_ERROR`: the timer is acknowledged (removed from Redis) on success, and left for retry on any unhandled exception.

| Outcome | Effect |
|---------|--------|
| Handler returns normally | Timer removed from Redis |
| Handler raises an exception | Timer left in Redis for retry on next poll |

To manually control acknowledgement, inject the `NoCast`-typed message:

```python
from faststream.message import StreamMessage
from faststream_redis_timers.message import TimerMessage


@broker.subscriber("invoices")
async def handle_invoice(
    body: str,
    msg: StreamMessage[TimerMessage],
) -> None:
    try:
        process(body)
        await msg.ack()
    except TransientError:
        await msg.nack()   # retry later
    except PermanentError:
        await msg.reject() # discard permanently
```
