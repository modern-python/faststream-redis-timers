faststream-redis-timers
==

[![Supported versions](https://img.shields.io/pypi/pyversions/faststream-redis-timers.svg)](https://pypi.python.org/pypi/faststream-redis-timers)
[![downloads](https://img.shields.io/pypi/dm/faststream-redis-timers.svg)](https://pypistats.org/packages/faststream-redis-timers)

`faststream-redis-timers` is a [FastStream](https://faststream.airt.ai) broker integration for Redis-backed distributed timer scheduling.

Schedule messages to be delivered to subscribers at a future point in time, with **at-least-once** delivery across multiple workers.

```python
from datetime import timedelta
from faststream import FastStream
from faststream_redis_timers import TimersBroker
from redis.asyncio import Redis

client = Redis.from_url("redis://localhost:6379")
broker = TimersBroker(client)
app = FastStream(broker)

@broker.subscriber("invoices")
async def handle_invoice(invoice_id: str) -> None:
    print(f"Invoice {invoice_id} is due!")

@app.after_startup
async def schedule() -> None:
    await broker.publish(
        "INV-001",
        topic="invoices",
        activate_in=timedelta(days=30),
    )
```

## How it works

Timers are stored in Redis as two structures:

- A **sorted set** (`timers_timeline`) with the activation timestamp as score
- A **hash** (`timers_payloads`) with the serialized message body

A polling loop checks for due timers and atomically claims each one via a Lua
script that pushes its score forward by `lease_ttl` seconds — granting the
worker a lease. The timer is removed from Redis only **after** the handler
completes successfully. If the worker crashes mid-handler or the handler
raises, the lease eventually expires and another worker re-claims the timer.

This is the standard SQS-style **visibility-timeout** pattern: at-least-once
delivery with no data loss on crash, at the cost of requiring **idempotent
handlers**.

## Cancellation

```python
await broker.publish("INV-001", topic="invoices", timer_id="inv-1", activate_in=timedelta(days=30))
await broker.cancel_timer("invoices", "inv-1")
```

## Tuning

Per-subscriber knobs (passed to `@broker.subscriber("topic", ...)`):

- `lease_ttl` (default `30` seconds) — how long a worker holds the lease while
  processing. Handlers must complete within this window or another worker may
  re-deliver the timer (duplicate). Increase if your handlers are slow.
- `polling_interval` (default `0.05` s) — how often the subscriber checks
  Redis for due timers when the queue is empty. Increase to reduce idle load.
- `max_concurrent` (default `5`) — maximum number of timers fetched per poll
  cycle.

## Failure modes

- **Handlers must be idempotent.** A handler that ran successfully but whose
  ack failed to land in Redis (network blip) will be retried; a handler that
  takes longer than `lease_ttl` may be re-delivered to another worker.
- **Buggy handler retries forever.** If a handler always raises, the timer is
  retried indefinitely. Raise `faststream.exceptions.RejectMessage` from your
  handler to drop a poison-pill timer permanently. A built-in `max_attempts`
  counter is planned for a future release.

## High availability

Run multiple `TimersBroker` processes against the same Redis keys. The Lua
claim script ensures each due timer is leased by exactly one worker at a
time; failover is automatic via lease expiry.

```python
broker = TimersBroker(
    Redis.from_url("redis://..."),
    timeline_key="my_timeline",
    payloads_key="my_payloads",
)
```

## 📚 [Documentation](https://faststream-redis-timers.readthedocs.io)

## 📦 [PyPi](https://pypi.org/project/faststream-redis-timers)

## 📝 [License](LICENSE)
