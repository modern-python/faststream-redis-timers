# How it works

## Redis data structures

`faststream-redis-timers` uses three Redis keys **per topic** to store scheduled timers:

| Key pattern | Type | Purpose |
|-------------|------|---------|
| `timers_timeline:{topic}` | Sorted set | Maps each `timer_id` to its activation Unix timestamp (score) |
| `timers_payloads:{topic}` | Hash | Maps each `timer_id` to its serialized message body |
| `timers_claims:{digest}` by default | Hash | Maps each claimed `timer_id` to its current ownership token |

When you publish a timer for topic `invoices` with `timer_id` `abc-123`, the timer is written and any previous claim is invalidated atomically using a Redis pipeline:

```
ZADD timers_timeline:invoices <activation_ts> abc-123
HSET timers_payloads:invoices abc-123 <encoded_envelope>
HDEL <ownership_key> abc-123
```

The envelope is FastStream's `BinaryMessageFormatV1`, a binary-safe wire format that carries the message body alongside `correlation_id`, `content-type`, `reply_to`, and any user-supplied headers. The same format is used by FastStream's built-in Redis broker.

## Polling loop

Each subscriber runs a background polling loop that:

1. Calls `ZRANGEBYSCORE timers_timeline:{topic} -inf <now> LIMIT 0 <free>` (where `<free>` is the unused capacity from the per-subscriber concurrency limiter) to find due timers
2. For each due timer, spawns a task (bounded by the `max_concurrent` capacity limiter) that runs an atomic Lua **claim** script that:
    - Verifies the timer is still due (score ≤ now)
    - Pushes its score forward by `lease_ttl` seconds, which grants the worker a lease
    - Records a fresh unique ownership token and returns the payload
3. Delivers the payload to the user handler
4. On handler success, runs an atomic Lua **commit** script that removes the timer and its claim token only if the captured token still matches
5. On handler exception, leaves the timer in place; the lease eventually expires and another worker re-claims it

This is the standard SQS-style **visibility-timeout** pattern. The timer's own score in the sorted set is the lease deadline; there is no separate lock primitive.

## At-least-once delivery

An atomic claim gives one worker ownership until another successful claim or a replacement invalidates it. Lease expiry permits another worker to claim while the original handler may still be running. Because the timer is removed from Redis only after the handler completes successfully, **no timer is lost on crash**: if the worker dies mid-handler, the lease expires and the timer is re-delivered.

The trade-off: handlers that take longer than `lease_ttl`, or workers that crash after the handler ran but before the commit landed, may see the timer delivered more than once. Handlers must therefore be **idempotent**.

## Ack / Nack / Reject

| Action | Effect |
|--------|--------|
| `ack` | Removes the timer and claim metadata only if this delivery still owns the claim |
| `nack` | No-op; the lease expires and another worker re-claims the timer |
| `reject` | Same conditional removal as `ack` (use for poison-pill messages) |

Replacement, cancel/recreate, and lease takeover make a previous delivery's completion a successful no-op. Corrupt-payload cleanup uses the same ownership check. Explicit cancellation remains unconditional. Successful commits, cancellation, and bulk cancellation remove claim metadata.

The default ack policy is `NACK_ON_ERROR`: the timer is acknowledged on success, and left for retry on any unhandled exception.

## Key configuration

### Broker constructor (`TimersBroker(...)`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `timeline_key` | `timers_timeline` | Prefix for sorted set keys (`{timeline_key}:{topic}`) |
| `payloads_key` | `timers_payloads` | Prefix for hash keys (`{payloads_key}:{topic}`) |
| `claims_key` | `None` | Optional ownership hash prefix (`{claims_key}:{topic}`); by default the key is derived from the timeline and payload keys |
| `start_timeout` | `3.0` s | Max wait for the first Redis ping during startup |

### Per-subscriber (`@broker.subscriber("topic", ...)`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `polling_interval` | `0.05` s | Base poll interval used when the topic has due timers or just transitioned from idle |
| `max_polling_interval` | `5.0` s | Ceiling for the adaptive idle backoff: `polling_interval` doubles up to this value on consecutive empty polls. Jitter is applied before the cap, so worst-case delivery latency on a previously-idle topic is `max_polling_interval` |
| `max_concurrent` | `5` | Max handlers running concurrently per subscriber; also bounds fetch batch size |
| `lease_ttl` | `30` s | How long a worker holds the lease before another worker may re-claim. Set to ~3–5× the P99 handler runtime: lower values speed up recovery from worker death, higher values tolerate handler GC pauses and clock skew |
| `command_timeout` | `None` (`lease_ttl`) | Most time the subscriber waits on one Redis command (fetch, claim, ack). A primary that goes silent without closing its connections otherwise stalls the subscriber; redis-py before 8.0 sets no socket timeout by default. Must be > 0 and <= `lease_ttl` |

Redis client encoding, encoding error handling, and `decode_responses` settings are preserved. Timer IDs use the client's encoder for storage and inspection; binary message envelopes remain raw bytes during claims.

By default, ownership keys are `timers_claims:{digest}`. The digest is SHA-256 of the full timeline and payload key bytes as encoded by the client, each preceded by its eight-byte big-endian length. This gives independently configured stores separate ownership metadata, remains stable across restarts, and requires no reserved binary namespace. An explicit `claims_key` instead uses `{claims_key}:{topic}`, including any topic prefix.

Timeline, payload, and ownership keys for a topic must be distinct after Redis encoding. Mutating operations reject overlapping keys with `ValueError` before issuing Redis commands. Use `claims_key` to select another namespace when needed. Across independently configured brokers, keep all key namespaces non-overlapping; workers sharing timers must use the same ownership configuration. Changing ownership configuration while workers are active is unsafe.

## Upgrading existing timers

Existing timer payloads and scores need no rewrite. Their first successful claim records a fresh ownership token; existing leases remain unavailable until their stored deadline.

Stop every old process that writes to the namespace before starting fenced workers. This includes consumers and their in-flight handlers, publishing-only processes, and cancellation clients. Upgrade all these writers before resuming them. Old consumers delete unconditionally; old publishers replace payloads and deadlines without invalidating claim ownership, allowing a fenced worker's stale completion to delete the replacement. Old cancellation clients also leave claim metadata behind. Stopping only old consumers is insufficient.

Persisted records may stay in Redis during this coordinated transition; new workers adopt them on claim. If old writers must remain active, use a separate namespace for fenced writers and workers. Downgrading any writer to the unfenced protocol restores the compatibility risk.

Fencing protects Redis timer state. It cannot retract external effects from a handler whose lease expired. Keep handlers idempotent; this provides at-least-once delivery and does not guarantee exactly-once publication to Kafka or other systems. Leases are not renewed automatically.

## Operational requirements

`faststream-redis-timers` is designed for a **single-primary Redis** (Sentinel-managed primary/replica setups are supported; Redis Cluster is not: constructing `TimersBroker` with a `RedisCluster` client raises `TypeError`).

Multiple brokers polling the same Redis derive timer due-times and lease deadlines from each broker's local wall clock. Keep all broker hosts NTP-synchronised: clock skew larger than `lease_ttl` between brokers can cause a clock-fast broker to re-lease a timer that another broker is still actively processing, producing duplicate delivery to handlers. The default `lease_ttl=30s` tolerates seconds of NTP drift; tune `lease_ttl` upward if your environment cannot guarantee sub-second sync.
