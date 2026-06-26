# Timer store

`TimerStore` is the one module that owns the Redis timer protocol across every
topic. All callers — the producer, the subscriber poll loop, the delivered
message, and broker inspection — cross its interface; no caller touches the
Redis sorted-set, hash, or Lua scripts directly.

## What it owns

Two Redis keys back every topic: a sorted-set (the timeline, keyed by Activation
time) and a hash (payloads, keyed by timer id). Both keys are derived from the
store's base keys as `{base_key}:{full_topic}` — that derivation lives only
here. Every caller passes a `full_topic` (prefix already applied); the store
derives the topic-specific key pair. There is one `TimerStore` instance per
broker, not one per topic.

The Lua scripts for atomic Claim and remove, their pre-computed SHAs, and the
`EVALSHA`-with-NOSCRIPT-fallback helper are module-private. Callers see only the
seven methods below.

## Operations

**Schedule** adds a Timer to the timeline at its Activation time and stores its
payload in the hash, atomically via a Redis pipeline. The payload is opaque
bytes; the store never inspects it.

**Due** polls the timeline for Timers whose Activation time has passed, returning
up to a requested limit of timer ids. If the Redis client operates in bytes mode,
the store decodes each member; a member that cannot be decoded as UTF-8 is
self-healed — removed atomically from both keys — and excluded from the result.
The subscriber never sees that branch.

**Claim** atomically leases a Due timer, returning its payload bytes, or `None`
if the timer is no longer Due (already Leased, Cancelled, or scheduled for the
future). The Lease is implemented by pushing the timer's timeline score forward
by `lease_ttl` seconds; other workers will not see it as Due until the Lease
expires. The check-fetch-advance sequence is a single Lua round-trip.

**Remove** deletes a timer from both the timeline and the payloads hash in one
atomic Lua round-trip. It is the shared implementation for three caller intents:
Commit (handler success via ack/reject), Cancel (producer-initiated removal
before the timer fires), and the orphan self-heal inside Due. Public intent is
expressed at each call site; all three paths funnel here.

**Pending** returns all Pending timer ids for a topic, optionally restricted to
those Due by a given timestamp. Leased timers appear in the default (no upper
bound) result because their score is pushed forward, not removed; passing the
current wall time as the upper bound excludes them.

**`is_pending`** checks whether a specific timer remains in the timeline — a
`ZSCORE` presence test.

**`cancel_all`** atomically removes every Pending timer on a topic and returns
the count removed. It unlinks both topic keys in a single pipeline.

## At-least-once delivery and lease semantics

A Claimed timer stays in the timeline with its score advanced by `lease_ttl`.
It is not removed until a handler acknowledges it.

- **`ack()`** and **`reject()`** on the delivered message both trigger Remove
  (Commit), atomically deleting the timer from both keys.
- **`nack()`** is a no-op: the Lease expires naturally, the timer's score falls
  back into the Due window, and another worker Claims it on the next poll.

If a worker crashes after Claiming but before Committing, the Lease expires and
the timer is re-delivered. Delivery is at-least-once: a successfully processed
timer is Committed exactly once via ack/reject, but a crashed or nacked handler
causes re-delivery.

## Seam crossings

Four callers cross the `TimerStore` seam:

- **Producer** — Schedules a timer and Cancels it on demand. It encodes the
  payload before calling the store; the store receives opaque bytes.
- **Subscriber poll loop** — Polls Due timers, then Claims each one concurrently.
  A `None` claim result means another worker won the race; the subscriber
  discards it silently.
- **Delivered message** (`TimerStreamMessage`) — Removes itself on ack/reject via
  a bound thunk (`partial(store.remove, full_topic, timer_id)`) installed by
  `TimerParser` at parse time. The message holds no Redis client and no key
  names; its internal guard checks only whether the thunk is set.
- **Broker inspection** — Calls `is_pending`, `pending`, and `cancel_all` to
  back the broker's public `has_pending`, `get_pending_timers`, and `cancel_all`
  methods.

Payloads cross the seam as opaque bytes in both directions. Timer ids surface as
`str` everywhere; the store absorbs all bytes↔str normalization regardless of
the Redis client's `decode_responses` mode.
