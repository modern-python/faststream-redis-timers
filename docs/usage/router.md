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
