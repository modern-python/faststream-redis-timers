# Router

`TimersRouter` lets you define subscribers and publishers in separate modules and include them into the broker, the same as FastStream's built-in router pattern.

## Creating a router

```python
from faststream_redis_timers import TimersRouter

router = TimersRouter(prefix="my-service:")


@router.subscriber("invoices")
async def handle_invoice(invoice_id: str) -> None:
    print(f"Invoice due: {invoice_id}")
```

## How `prefix` works

The `prefix` you pass to `TimersRouter` is concatenated to every topic registered via that router — both subscribers and publishers. Given:

```python
router = TimersRouter(prefix="my-service:")

@router.subscriber("invoices")
async def handle_invoice(...): ...
```

…the subscriber listens on the full topic `my-service:invoices`, and Redis stores its timers under:

- `timers_timeline:my-service:invoices`
- `timers_payloads:my-service:invoices`

This is the recommended way to isolate multiple services or environments that share one Redis instance — give each its own `TimersRouter` prefix and they will never collide on keys.

### Publishing to a prefixed router

`broker.publish(...)` does **not** know about the router's prefix — it only applies the broker's own prefix (empty by default). To target a prefixed subscriber from `broker.publish`, pass the full topic:

```python
await broker.publish("INV-001", topic="my-service:invoices", activate_in=...)
```

Or define a publisher inside the same router and use it — the router's prefix is applied automatically:

```python
publisher = router.publisher("invoices")
await publisher.publish("INV-001", activate_in=...)  # lands on my-service:invoices
```

The same rule applies to `broker.cancel_timer`, `broker.has_pending`, `broker.get_pending_timers`, and `broker.cancel_all`: pass the prefixed topic, or call the equivalent methods through a router-scoped publisher.

## Including a router in the broker

```python
from faststream import FastStream
from faststream_redis_timers import TimersBroker
from redis.asyncio import Redis

from myapp.routers import router

client = Redis.from_url("redis://localhost:6379")
broker = TimersBroker(client)
broker.include_router(router)
app = FastStream(broker)
```

## Defining routes up-front with `TimersRoute`

`TimersRoute` lets you declare handler + topic together without using decorators, which can be useful for code-gen or plugin patterns:

```python
from faststream_redis_timers import TimersRoute, TimersRouter


async def handle_invoice(invoice_id: str) -> None:
    print(f"Invoice due: {invoice_id}")


router = TimersRouter(
    handlers=[
        TimersRoute(handle_invoice, topic="invoices"),
    ],
)
```

## Subscriber options per router

You can configure polling behaviour per subscriber:

```python
@router.subscriber(
    "high-priority",
    polling_interval=0.01,    # poll every 10ms when the queue has work
    max_polling_interval=0.5, # cap idle-backoff at 500ms (default 5s)
    max_concurrent=20,        # up to 20 handlers may run in parallel
    lease_ttl=60,             # hold lease for up to 60 seconds
)
async def handle_urgent(message: str) -> None: ...
```

All `@broker.subscriber` options are accepted by `@router.subscriber` and `TimersRoute` — see the [subscriber page](./subscriber.md) for the full list.
