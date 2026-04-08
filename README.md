faststream-redis-timers
==

[![Supported versions](https://img.shields.io/pypi/pyversions/faststream-redis-timers.svg)](https://pypi.python.org/pypi/faststream-redis-timers)
[![downloads](https://img.shields.io/pypi/dm/faststream-redis-timers.svg)](https://pypistats.org/packages/faststream-redis-timers)

`faststream-redis-timers` is a [FastStream](https://faststream.airt.ai) broker integration for Redis-backed distributed timer scheduling.

Schedule messages to be delivered to subscribers at a future point in time — reliably, with distributed locking so no timer fires twice.

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

A polling loop checks for due timers and delivers each one exactly once using a **distributed Redis lock**, making it safe to run multiple instances simultaneously.

## 📚 [Documentation](https://faststream-redis-timers.readthedocs.io)

## 📦 [PyPi](https://pypi.org/project/faststream-redis-timers)

## 📝 [License](LICENSE)
