# How it works

## Redis data structures

`faststream-redis-timers` uses two Redis keys **per topic** to store scheduled timers:

| Key pattern | Type | Purpose |
|-------------|------|---------|
| `timers_timeline:{topic}` | Sorted set | Maps each `timer_id` to its activation Unix timestamp (score) |
| `timers_payloads:{topic}` | Hash | Maps each `timer_id` to its serialized message body |

When you publish a timer for topic `invoices` with `timer_id` `abc-123`, both keys are written atomically using a Redis pipeline:

```
ZADD timers_timeline:invoices <activation_ts> abc-123
HSET timers_payloads:invoices abc-123 <encoded_envelope>
```

The envelope is FastStream's `BinaryMessageFormatV1` — a binary-safe wire format that carries the message body alongside `correlation_id`, `content-type`, `reply_to`, and any user-supplied headers. The same format is used by FastStream's built-in Redis broker.

## Polling loop

Each subscriber runs a background polling loop that:

1. Calls `ZRANGEBYSCORE timers_timeline:{topic} -inf <now> LIMIT 0 <free>` (where `<free>` is the unused capacity from the per-subscriber concurrency limiter) to find due timers
2. For each due timer, spawns a task that — bounded by the `max_concurrent` capacity limiter — runs an atomic Lua **claim** script that:
    - Verifies the timer is still due (score ≤ now)
    - Pushes its score forward by `lease_ttl` seconds — granting the worker a lease
    - Returns the payload
3. Delivers the payload to the user handler
4. On handler success, runs an atomic Lua **commit** script (`ZREM` + `HDEL`) to remove the timer from Redis
5. On handler exception, leaves the timer in place — the lease eventually expires and another worker re-claims it

This is the standard SQS-style **visibility-timeout** pattern. The timer's own score in the sorted set acts as the lease deadline — there is no separate lock primitive.

## At-least-once delivery

The lease ensures each due timer is processed by exactly one worker at a time. Because the timer is removed from Redis only after the handler completes successfully, **no timer is lost on crash** — if the worker dies mid-handler, the lease expires and the timer is re-delivered.

The trade-off: handlers that take longer than `lease_ttl`, or workers that crash after the handler ran but before the commit landed, may see the timer delivered more than once. Handlers must therefore be **idempotent**.

## Ack / Nack / Reject

| Action | Effect |
|--------|--------|
| `ack` | Atomically removes the timer from `timers_timeline` and `timers_payloads` |
| `nack` | No-op — the lease expires and another worker re-claims the timer |
| `reject` | Same as `ack` — permanently removes the timer (use for poison-pill messages) |

The default ack policy is `NACK_ON_ERROR`: the timer is acknowledged on success, and left for retry on any unhandled exception.

## Key configuration

### Broker constructor (`TimersBroker(...)`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `timeline_key` | `timers_timeline` | Prefix for sorted set keys (`{timeline_key}:{topic}`) |
| `payloads_key` | `timers_payloads` | Prefix for hash keys (`{payloads_key}:{topic}`) |
| `start_timeout` | `3.0` s | Max wait for the first Redis ping during startup |

### Per-subscriber (`@broker.subscriber("topic", ...)`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `polling_interval` | `0.05` s | Base poll interval used when the queue has work or just transitioned from idle |
| `max_polling_interval` | `5.0` s | Ceiling for the adaptive idle backoff — `polling_interval` doubles up to this value on consecutive empty polls. Worst-case delivery latency on a previously-idle queue is `max_polling_interval × 1.5` (with ±50% jitter) |
| `max_concurrent` | `5` | Max handlers running concurrently per subscriber; also bounds fetch batch size |
| `lease_ttl` | `30` s | How long a worker holds the lease before another worker may re-claim |
