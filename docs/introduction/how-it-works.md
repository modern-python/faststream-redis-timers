# How it works

## Redis data structures

`faststream-redis-timers` uses two Redis keys to store scheduled timers:

| Key | Type | Purpose |
|-----|------|---------|
| `timers_timeline` | Sorted set | Maps each timer key to its activation Unix timestamp (score) |
| `timers_payloads` | Hash | Maps each timer key to its serialized message body |

A **timer key** has the form `{topic}--{timer_id}`, e.g. `invoices--abc-123`.

When you publish a timer, both keys are written atomically using a Redis pipeline:

```
ZADD timers_timeline <activation_ts> invoices--abc-123
HSET timers_payloads invoices--abc-123 <encoded_body>
```

## Polling loop

Each subscriber runs a background polling loop that:

1. Calls `ZRANGEBYSCORE timers_timeline -inf <now>` to find due timers
2. For each due timer, attempts to acquire a **distributed Redis lock** (`timers_lock:{timer_key}`) with `blocking=False`
3. If the lock is acquired, reads the payload from `timers_payloads` and delivers the message
4. On successful processing, atomically removes the timer from both keys (`ZREM` + `HDEL`)
5. On error, releases the lock and leaves the timer in place for retry

## Exactly-once delivery

The distributed lock ensures that even if multiple instances of your service are running, each timer is delivered by exactly one instance. If a worker crashes while holding the lock, the lock TTL (`lock_ttl`, default 30 seconds) ensures another instance can pick it up.

## Ack / Nack / Reject

| Action | Effect |
|--------|--------|
| `ack` | Atomically removes the timer from `timers_timeline` and `timers_payloads` |
| `nack` | No-op — timer remains in Redis for retry on the next poll cycle |
| `reject` | Same as `ack` — permanently removes the timer |

The default ack policy is `NACK_ON_ERROR`: the timer is acknowledged on success, and left for retry on any unhandled exception.

## Key configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `timeline_key` | `timers_timeline` | Sorted set key for the timer schedule |
| `payloads_key` | `timers_payloads` | Hash key for timer payloads |
| `lock_prefix` | `timers_lock:` | Prefix for distributed lock keys |
| `polling_interval` | `0.05` s | How often to poll when no timers are due |
| `max_concurrent` | `5` | Max timers processed per poll cycle per subscriber |
| `lock_ttl` | `30` s | Lock expiry — protects against crashed workers |
