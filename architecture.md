# faststream-redis-timers Architecture

## Overview

`faststream-redis-timers` is a FastStream broker integration that provides distributed timer scheduling backed by Redis. The timer logic (sorted-set storage, distributed locking, polling loop) is implemented natively in this package, inspired by FastStream's own Redis stream subscriber pattern. No dependency on `redis-timers`.

---

## User-Facing API

```python
from redis.asyncio import Redis
from faststream_redis_timers import TimersBroker, TimersRouter, TestTimersBroker
from pydantic import BaseModel
from datetime import timedelta

redis = Redis.from_url("redis://localhost:6379")
broker = TimersBroker(redis)

class EmailPayload(BaseModel):
    email: str
    subject: str

@broker.subscriber(topic="send_email")
async def handle_email_timer(data: EmailPayload) -> None:
    await send_email(data.email, data.subject)

email_publisher = broker.publisher(topic="send_email")

# Schedule a timer:
await email_publisher.publish(
    EmailPayload(email="user@example.com", subject="Welcome"),
    timer_id="user-123",
    activate_in=timedelta(hours=1),
)

# Cancel a timer:
await broker.remove_timer(topic="send_email", timer_id="user-123")
```

### Router

```python
router = TimersRouter(prefix="notifications.")

@router.subscriber(topic="send_email")  # → full topic: "notifications.send_email"
async def handle(data: EmailPayload) -> None: ...

broker.include_router(router)
```

### Testing

```python
async with TestTimersBroker(broker) as tb:
    await tb.publish(
        EmailPayload(email="test@example.com", subject="Test"),
        topic="send_email",
        timer_id="test-1",
        activate_in=timedelta(seconds=0),
    )
    broker.subscribers[0].mock.assert_called_once()
```

---

## Package Structure

```
faststream_redis_timers/
├── __init__.py              # Public API
├── broker.py                # TimersBroker
├── registrator.py           # TimersRegistrator (subscriber/publisher factories)
├── schemas.py               # TimerSub schema (topic, polling_interval, max_concurrent, lock_ttl)
├── message.py               # TimerMessage TypedDict + TimerStreamMessage
├── response.py              # TimerPublishCommand + TimerResponse
├── parser/
│   └── parser.py            # Timer message parser & decoder
├── subscriber/
│   ├── config.py            # TimersSubscriberUsecaseConfig + Specification config
│   ├── usecase.py           # TimersSubscriber + TimersSubscriberSpecification
│   └── factory.py           # create_subscriber()
├── publisher/
│   ├── config.py            # TimersPublisherUsecaseConfig + Specification config
│   ├── usecase.py           # TimersPublisher + TimersPublisherSpecification
│   ├── producer.py          # TimersProducer (ProducerProto impl)
│   └── factory.py           # create_publisher()
├── router.py                # TimersRouter + TimersRoute + TimersRoutePublisher
└── testing.py               # TestTimersBroker + FakeTimersProducer

test_faststream_redis_timers/
├── __init__.py
├── test_main.py             # Unit tests (TestTimersBroker, no Redis)
└── test_integration.py      # Integration tests (real Redis via docker-compose)

pyproject.toml
Justfile
Dockerfile
docker-compose.yml
CLAUDE.md
README.md
```

---

## Redis Key Layout

| Key | Type | Content |
|-----|------|---------|
| `timers_timeline` | Sorted Set | `{topic}--{timer_id} → Unix timestamp (score)` |
| `timers_payloads` | Hash | `{topic}--{timer_id} → raw JSON bytes` |
| `timers_lock:{topic}--{timer_id}` | String | Ephemeral distributed lock (30s TTL by default) |

Timer key format: `{topic}{SEPARATOR}{timer_id}` where `SEPARATOR = "--"`.

All three key names are configurable via constructor parameter (default values match redis-timers for drop-in compatibility).

---

## Component Architecture

### Message Flow (consume path)

```
TimersSubscriber._get_msgs()
    → ZRANGEBYSCORE timers_timeline 0 {now}   [get ready timers]
    → for each timer_key (up to max_concurrent):
        → acquire non-blocking Redis lock (30s TTL)
        → HGET timers_payloads timer_key       [fetch raw JSON payload]
        → yield TimerMessage{topic, timer_id, body, timer_key}
        → (lock held during yield / message processing)

FastStream middleware stack
    → parser: TimerMessage → TimerStreamMessage
    → decoder: bytes → dict (JSON)
    → FastDepends DI: dict → user's type-hinted param (e.g. EmailPayload)
    → user handler(data: EmailPayload)

TimerStreamMessage.ack()       [called by AcknowledgementMiddleware on success]
    → PIPELINE: ZREM timers_timeline + HDEL timers_payloads

generator resumes (finally block)
    → release Redis lock
```

### Message Flow (publish path)

```
TimersPublisher.publish(payload, timer_id=..., activate_in=timedelta(...))
    → TimerPublishCommand(body=payload, destination=topic, timer_id=..., activate_in=...)
    → _basic_publish(cmd, producer, middlewares)
    → TimersProducer.publish(cmd)
    → encode_message(cmd.body) → raw bytes
    → PIPELINE:
        ZADD timers_timeline {timer_key: now + activate_in}
        HSET timers_payloads timer_key raw_bytes
```

---

## Class Definitions

### `schemas.py`

```python
@dataclass(kw_only=True, slots=True, frozen=True)
class TimerSub:
    """Configuration for a timer subscriber (analogous to redis ListSub/StreamSub)."""
    topic: str                       # Full topic name (with prefix applied)
    polling_interval: float = 0.05  # Seconds between polls when no timers ready
    max_concurrent: int = 5          # Max timers processed per poll cycle
    lock_ttl: int = 30               # Distributed lock TTL in seconds
```

### `message.py`

```python
class TimerMessage(TypedDict):
    """Raw message TypedDict — what flows through FastStream's bus."""
    type: Literal["timer"]
    channel: str        # full topic name (for compatibility with FastStream log context)
    timer_id: str
    data: bytes         # raw JSON payload

class TimerStreamMessage(BrokerStreamMessage[TimerMessage]):
    """FastStream StreamMessage wrapper for a timer."""
    _redis_client: Redis
    _timer_key: str
    _timeline_key: str
    _payloads_key: str

    async def ack(self) -> None:
        """Remove timer from Redis (success path)."""
        async with self._redis_client.pipeline(transaction=True) as pipe:
            pipe.zrem(self._timeline_key, self._timer_key)
            pipe.hdel(self._payloads_key, self._timer_key)
            await pipe.execute()

    async def nack(self) -> None:
        """Keep timer in Redis — will be retried on next poll cycle."""
        pass

    async def reject(self) -> None:
        """Remove timer permanently without retry."""
        async with self._redis_client.pipeline(transaction=True) as pipe:
            pipe.zrem(self._timeline_key, self._timer_key)
            pipe.hdel(self._payloads_key, self._timer_key)
            await pipe.execute()

    @classmethod
    def from_timer_message(
        cls,
        raw: TimerMessage,
        redis_client: Redis,
        timer_key: str,
        timeline_key: str,
        payloads_key: str,
    ) -> "TimerStreamMessage": ...
```

### `response.py`

```python
class TimerPublishCommand(PublishCommand):
    """Publish command for scheduling a timer."""
    timer_id: str
    activate_in: timedelta

    @classmethod
    def from_cmd(cls, cmd: PublishCommand, *, timer_id: str, activate_in: timedelta) -> "TimerPublishCommand": ...

class TimerResponse(Response):
    """Response type for timer publish."""
    def as_publish_command(self) -> TimerPublishCommand: ...
```

### `subscriber/usecase.py`

```python
class TimersSubscriber(LogicSubscriber[TimerMessage]):
    """
    Timer subscriber. Polls Redis sorted set for ready timers,
    acquires distributed locks, and dispatches via FastStream consume pipeline.

    Pattern follows FastStream's redis.subscriber.usecases.list_subscriber.ListSubscriber.
    """

    def __init__(self, *, config: TimersSubscriberUsecaseConfig, ...): ...

    async def _get_msgs(self, client: Redis) -> AsyncGenerator[TimerMessage, None]:
        """
        Core polling logic. Called in a loop by the base class _consume() method.

        1. ZRANGEBYSCORE to find ready timers
        2. For each timer (up to max_concurrent):
           a. Try non-blocking lock acquire
           b. HGET payload
           c. yield TimerMessage (lock held during yield)
           d. finally: release lock
        3. Sleep polling_interval if no timers ready
        """
        import time
        now = time.time()
        timer_keys: list[bytes] = await client.zrangebyscore(
            self._config.timeline_key, 0, now
        )

        if not timer_keys:
            await anyio.sleep(self._config.timer_sub.polling_interval)
            return

        count = 0
        for raw_key in timer_keys:
            if count >= self._config.timer_sub.max_concurrent:
                break

            key_str = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            lock = Lock(
                client,
                f"{self._config.lock_prefix}{key_str}",
                timeout=self._config.timer_sub.lock_ttl,
                blocking=False,
            )

            if await lock.locked():
                continue

            acquired = await lock.acquire()
            if not acquired:
                continue  # Race condition — another worker got it

            try:
                raw_payload: bytes | None = await client.hget(
                    self._config.payloads_key, key_str
                )
                if raw_payload is None:
                    # Orphan key in timeline — clean up
                    await client.zrem(self._config.timeline_key, key_str)
                    continue

                topic, timer_id = key_str.split(SEPARATOR, 1)
                yield TimerMessage(
                    type="timer",
                    channel=topic,
                    timer_id=timer_id,
                    data=raw_payload,
                )
                count += 1
            finally:
                await lock.release()

    async def get_one(self, *, timeout: float = 5) -> Optional[TimerStreamMessage]:
        raise NotImplementedError("TimersBroker does not support get_one()")

    def _make_response_publisher(self, message: TimerStreamMessage) -> Iterable[PublisherProto]:
        return ()  # No reply-to for timers

    def get_log_context(self, message: TimerStreamMessage | None) -> dict[str, str]:
        if message:
            return {"topic": message.raw_message["channel"], "timer_id": message.raw_message["timer_id"]}
        return {"topic": self._config.timer_sub.topic}
```

**Note on base class:** FastStream's Redis subscriber uses `LogicSubscriber` as the base. Timers subscriber follows the same pattern. The base `LogicSubscriber` provides:
- `_consume()` loop (calls `_get_msgs()` in a loop via `async for`)
- `start()` / `stop()` lifecycle
- Task management via `TasksMixin`
- `consume_one()` → `consume()` → middleware → handler

### `publisher/producer.py`

```python
SEPARATOR = "--"

class TimersProducer:
    """
    Writes timers to Redis sorted set + hash.
    Implements ProducerProto[TimerPublishCommand].
    Analogous to RedisFastProducer but for timer scheduling semantics.
    """

    def __init__(
        self,
        *,
        parser: Callable,
        decoder: Callable,
        timeline_key: str = "timers_timeline",
        payloads_key: str = "timers_payloads",
    ): ...

    async def publish(self, cmd: TimerPublishCommand) -> None:
        body = encode_message(cmd.body, self._serializer)
        if isinstance(body, str):
            body = body.encode()
        timer_key = f"{cmd.destination}{SEPARATOR}{cmd.timer_id}"
        from datetime import timezone
        activation_ts = (datetime.now(tz=timezone.utc) + cmd.activate_in).timestamp()
        client = cmd.client  # passed from broker config
        async with client.pipeline(transaction=True) as pipe:
            pipe.zadd(self._timeline_key, {timer_key: activation_ts})
            pipe.hset(self._payloads_key, timer_key, body)
            await pipe.execute()

    async def request(self, cmd: TimerPublishCommand) -> NoReturn:
        raise NotImplementedError("Timers do not support request-reply")

    async def publish_batch(self, cmd: TimerPublishCommand) -> NoReturn:
        raise NotImplementedError("Use multiple publish() calls for multiple timers")
```

### `broker.py`

```python
class TimersBroker(TimersRegistrator, BrokerUsecase[TimerMessage, Redis, BrokerConfig]):
    """
    FastStream broker for Redis timer scheduling.

    Analogous to RedisBroker but with timer semantics:
    - subscribe = register a handler for a timer topic
    - publish = schedule a timer (ZADD + HSET)
    - polling loop = sorted-set poll, lock, dispatch, ack=remove
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379",
        *,
        # Timer config
        timeline_key: str = "timers_timeline",
        payloads_key: str = "timers_payloads",
        lock_prefix: str = "timers_lock:",
        # FastStream standard params
        parser: Optional[CustomCallable] = None,
        decoder: Optional[CustomCallable] = None,
        middlewares: Sequence[BrokerMiddleware] = (),
        broker_dependencies: Iterable[Dependant] = (),
        graceful_timeout: float | None = None,
        logger: logging.Logger | None = ...,
        log_level: int = logging.INFO,
        apply_types: bool = True,
        routers: Sequence[TimersRouter] = (),
        # AsyncAPI
        description: str | None = None,
        tags: Sequence[Tag] | None = None,
    ): ...

    async def _connect(self, url: str) -> Redis:
        """Create Redis connection (mirrors RedisBroker._connect)."""
        from redis.asyncio import Redis as AsyncRedis
        return AsyncRedis.from_url(url)

    async def ping(self, timeout: float | None = None) -> bool:
        return await self._connection.ping()

    async def remove_timer(self, topic: str, timer_id: str) -> None:
        """Cancel a scheduled timer. Removes from both timeline and payloads."""
        timer_key = f"{topic}{SEPARATOR}{timer_id}"
        async with self._connection.pipeline(transaction=True) as pipe:
            pipe.zrem(self._timeline_key, timer_key)
            pipe.hdel(self._payloads_key, timer_key)
            await pipe.execute()
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| No `redis-timers` dependency | Implement timer logic natively | User requirement; avoids coupling to a specific library version |
| Follow FastStream Redis subscriber pattern | `_get_msgs()` async generator, `LogicSubscriber` base | Internal consistency; same lifecycle, task management, error handling |
| Ack = remove timer | `TimerStreamMessage.ack()` does ZREM+HDEL | Natural mapping: ack means "handled successfully, remove job" |
| Nack = keep timer for retry | No-op in `nack()` | Timer stays in timeline; next poll picks it up |
| Reject = remove without retry | Same Redis ops as ack | Discard timer permanently |
| Lock held during `yield` | `try/finally` around yield in generator | Prevents double-processing by concurrent workers during handler execution |
| `timer_id` in `TimerStreamMessage` | `message_id` and `correlation_id` fields | Natural place; accessible from handler via `context["message"]` |
| Direct Redis write for publish | `TimersProducer` writes ZADD+HSET | Same pattern as `RedisFastProducer` for lists/streams |
| `request()` not supported | Raises `NotImplementedError` | Timers are fire-and-forget |
| `get_one()` not supported | Raises `NotImplementedError` | Timer delivery is push-based via polling |
| Single `TimerSub` schema | No channel/list/stream variants | Timers have one delivery mechanism; no variants needed |
| Configurable Redis key names | `timeline_key`, `payloads_key`, `lock_prefix` in constructor | Same keys as redis-timers by default (drop-in) |

---

## Ack Policy

`TimerStreamMessage` ack policy maps to FastStream's acknowledgement middleware:

| Event | Action | Redis Effect |
|-------|--------|--------------|
| Handler succeeds | `ack()` | ZREM + HDEL (timer removed) |
| Handler raises `NackMessage` | `nack()` | No-op (timer stays for retry) |
| Handler raises `AckMessage` | `ack()` | ZREM + HDEL |
| Handler raises `RejectMessage` | `reject()` | ZREM + HDEL (discarded) |
| Unhandled exception | `nack()` | No-op (default: retry) |

---

## Parser / Decoder

### Default Parser (`parser/parser.py`)

```python
async def _timer_parser(msg: TimerMessage, *, redis_client: Redis, ...) -> TimerStreamMessage:
    timer_key = f"{msg['channel']}{SEPARATOR}{msg['timer_id']}"
    return TimerStreamMessage(
        raw_message=msg,
        body=msg["data"],
        headers={},
        path={},
        content_type="application/json",
        message_id=msg["timer_id"],
        correlation_id=msg["timer_id"],
        # inject Redis client for ack/nack
        _redis_client=redis_client,
        _timer_key=timer_key,
        ...
    )
```

### Default Decoder

```python
async def _timer_decoder(msg: TimerStreamMessage) -> Any:
    return json.loads(msg.body)
```

FastDepends handles Pydantic validation from dict → user's type-hinted handler argument.

---

## Testing Support

`TestTimersBroker` wraps `TimersBroker` and patches the producer with `FakeTimersProducer`:

```python
class FakeTimersProducer(TimersProducer):
    """
    Instead of writing to Redis, directly calls matching subscriber's process_message().
    Enables testing without a real Redis connection.
    """

    async def publish(self, cmd: TimerPublishCommand) -> None:
        body = encode_message(cmd.body, None)
        if isinstance(body, str):
            body = body.encode()
        raw_msg = TimerMessage(
            type="timer",
            channel=cmd.destination,
            timer_id=cmd.timer_id,
            data=body,
        )
        for subscriber in self._broker.subscribers:
            if subscriber._config.timer_sub.topic == cmd.destination:
                await subscriber.process_message(raw_msg)
                return
```

---

## Dependencies

```toml
[project.dependencies]
faststream = "~=0.6"
redis = {version = ">=5.0", extras = ["hiredis"]}
redis-py-lock = "*"  # OR use redis.asyncio.lock.Lock directly
```

Note: `redis.asyncio.lock.Lock` is included in the `redis` package — no separate lock library needed.

---

## Configuration

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `timeline_key` | `"timers_timeline"` | Redis sorted set key |
| `payloads_key` | `"timers_payloads"` | Redis hash key |
| `lock_prefix` | `"timers_lock:"` | Prefix for lock keys |
| `polling_interval` | `0.05` | Per-subscriber: seconds between polls when idle |
| `max_concurrent` | `5` | Per-subscriber: max timers processed per poll |
| `lock_ttl` | `30` | Per-subscriber: lock TTL in seconds |
