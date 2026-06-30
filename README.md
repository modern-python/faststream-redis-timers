<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)"  srcset="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/faststream-redis-timers/lockup-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/faststream-redis-timers/lockup-light.svg">
    <img alt="faststream-redis-timers" src="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/faststream-redis-timers/lockup.png" width="420">
  </picture>
</p>

[![PyPI version](https://img.shields.io/pypi/v/faststream-redis-timers.svg)](https://pypi.org/project/faststream-redis-timers/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/faststream-redis-timers.svg)](https://pypi.org/project/faststream-redis-timers/)
[![Downloads](https://img.shields.io/pypi/dm/faststream-redis-timers.svg)](https://pypistats.org/packages/faststream-redis-timers)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/faststream-redis-timers/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/faststream-redis-timers/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/faststream-redis-timers/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/faststream-redis-timers.svg)](https://github.com/modern-python/faststream-redis-timers/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/faststream-redis-timers)](https://github.com/modern-python/faststream-redis-timers/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/faststream-redis-timers)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

`faststream-redis-timers` is a [FastStream](https://faststream.airt.ai) broker integration for Redis-backed distributed timer scheduling.

Schedule messages to be delivered to subscribers at a future point in time, with **at-least-once** delivery across multiple workers.

> **Already using Postgres?** Prefer [`faststream-outbox`](https://github.com/modern-python/faststream-outbox), which also supports
> [timers](https://faststream-outbox.readthedocs.io/en/latest/usage/timers/) and lets you schedule a timer in the **same SQLAlchemy
> transaction** as the domain write — no dual-write between your DB and Redis. Reach for `faststream-redis-timers` when your stack
> doesn't include Postgres, or when you want timer scheduling decoupled from your relational store.

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

Schedule at an absolute time with `activate_at` instead. `publish()` returns the
resolved `timer_id` so you can keep it for cancellation:

```python
from datetime import UTC, datetime

timer_id = await broker.publish(
    "INV-001",
    topic="invoices",
    activate_at=datetime(2026, 6, 1, 9, tzinfo=UTC),
)
```

## How it works

Timers are stored in Redis as two keys **per topic**:

- A **sorted set** (`timers_timeline:{topic}`) with the activation timestamp as score
- A **hash** (`timers_payloads:{topic}`) with the serialized message body

So a timer on the `invoices` topic lives under `timers_timeline:invoices` and `timers_payloads:invoices` — handy when poking around in `redis-cli`. A `TimersRouter(prefix="my-service:")` extends the suffix to `my-service:invoices`.

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
timer_id = await broker.publish("INV-001", topic="invoices", activate_in=timedelta(days=30))
await broker.cancel_timer("invoices", timer_id)
```

## Tracing & headers

`publish()` accepts `correlation_id` and `headers` — both round-trip to the handler via the standard FastStream `StreamMessage`:

```python
await broker.publish(
    {"order_id": 42},
    topic="orders",
    correlation_id="trace-abc-123",
    headers={"x-tenant": "acme", "x-priority": "high"},
)
```

Inside the handler:

```python
from faststream import Context

@broker.subscriber("orders")
async def handle(
    body: dict,
    correlation_id: str = Context("message.correlation_id"),
    tenant: str = Context("message.headers.x-tenant"),
) -> None:
    ...
```

## Connection ownership

`TimersBroker` does **not** close the Redis client you pass in — the caller owns
its lifecycle. The same client can be shared across multiple brokers, so closing
it from one broker would surprise the others. Manage the client with `async with`
or a `try/finally`:

```python
async with Redis.from_url("redis://localhost:6379") as client:
    broker = TimersBroker(client)
    app = FastStream(broker)
    await app.run()
```

## Tuning

Per-subscriber knobs (passed to `@broker.subscriber("topic", ...)`):

- `lease_ttl` (default `30` seconds) — how long a worker holds the lease while
  processing. Handlers must complete within this window or another worker may
  re-deliver the timer (duplicate). Increase if your handlers are slow.
- `polling_interval` (default `0.05` s) — base poll interval used when the queue
  has work or just transitioned from idle. Doubles on each consecutive empty
  cycle, capped at `max_polling_interval`, with ±50% jitter applied each sleep.
- `max_polling_interval` (default `5.0` s) — ceiling for the adaptive idle
  backoff. Lower it for tighter delivery latency on idle queues; raise it to
  reduce Redis load on workloads with long idle stretches.
- `max_concurrent` (default `5`) — maximum number of handlers running in
  parallel per subscriber. Also caps the fetch batch size per poll cycle.
  Handlers must be safe under concurrency in addition to being idempotent.

## Failure modes

- **Handlers must be idempotent.** A handler that ran successfully but whose
  ack failed to land in Redis (network blip) will be retried; a handler that
  takes longer than `lease_ttl` may be re-delivered to another worker.
- **Buggy handler retries forever.** If a handler always raises, the timer is
  retried every `lease_ttl` seconds indefinitely — there is no built-in
  attempt counter. Raise `faststream.exceptions.RejectMessage` from your
  handler to drop a poison-pill timer permanently, or track attempts in your
  own state if you need a hard cap.

## High availability

Run multiple `TimersBroker` processes against the same Redis keys. The Lua
claim script ensures each due timer is leased by exactly one worker at a
time; failover is automatic via lease expiry.

Supports single-primary Redis, including Sentinel-managed primary/replica
setups. Redis Cluster is **not** supported: each topic's timeline and
payload keys must live on the same node, and the broker raises a
`TypeError` if constructed with a `RedisCluster` client.

```python
broker = TimersBroker(
    Redis.from_url("redis://..."),
    timeline_key="my_timeline",
    payloads_key="my_payloads",
)
```

## 📚 [Documentation](https://faststream-redis-timers.modern-python.org)

## 📦 [PyPI](https://pypi.org/project/faststream-redis-timers)

## 📝 [License](LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.
