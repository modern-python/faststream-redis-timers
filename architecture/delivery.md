# Delivery & at-least-once

How a scheduled Timer reaches a handler, and the guarantee around it: every
Timer is delivered **at least once**. A Timer is removed only after the handler
accounts for it; a handler failure or a worker crash leads to redelivery, never
to silent loss. The Redis operations behind each step live in the
[TimerStore](timer-store.md); this page is the consumer side and the guarantee.

## The delivery loop

Each subscriber runs one poll loop per Topic. On every tick it asks the store
for the **Due** Timers — those whose Activation time has passed — up to the
number of free handler slots, then hands each off to be Claimed and consumed
concurrently. The loop never blocks on Redis pub/sub; it polls.

When a tick finds nothing Due it backs off (idle ramp); a fetch error backs off
harder; a busy tick loops immediately. That timing is owned by `PollSchedule`
and does not affect the guarantee — only how eagerly the loop polls.

## Claim, Lease, and the guarantee

Delivery hinges on the **Lease**. To deliver a Due Timer the worker **Claims**
it: a single atomic step that re-checks the Timer is still Due and pushes its
Activation time forward by `lease_ttl` seconds. While the handler runs, the
Timer therefore looks *not yet Due* to every other worker and every later poll —
it stays Pending but hidden. The Claim returns the payload, or nothing if the
Timer was already Claimed by another worker, Cancelled, or is not yet Due
(a contested Claim is simply skipped).

What happens next is the **Commit** decision:

- **Handler succeeds → ack → the Timer is removed.** Done; it will not be
  delivered again.
- **Handler raises → nack → nothing happens.** The Timer keeps its leased
  (future) Activation time. When the Lease expires it becomes Due again and is
  re-Claimed and redelivered. This is the retry path (the default ack policy is
  *nack on error*).
- **Handler rejects (`RejectMessage`) → reject → the Timer is removed.** A
  terminal decision: drop it, no retry.

A worker that crashes mid-handler never reaches ack, so its Lease simply expires
and another worker redelivers — the same path as nack. That is the at-least-once
guarantee: a Timer survives until a handler explicitly accounts for it with ack
or reject.

## Concurrency and back-pressure

A capacity limiter (`max_concurrent`, default 5) bounds both how many handlers
run at once and how many Due Timers a single tick fetches. When every slot is
busy the tick fetches nothing and yields briefly, so a slow handler cannot starve
the loop or pile up unbounded in-flight work.

## At-least-once, not exactly-once

The Lease is a time window, not a lock. If a handler runs longer than
`lease_ttl`, the Lease expires while it is still working and another worker may
redeliver the same Timer concurrently. Delivery is therefore **at least once**:
handlers must be idempotent, or `lease_ttl` must comfortably exceed the slowest
expected handler. Shorter `lease_ttl` means faster recovery after a crash but a
tighter deadline before duplicate delivery; longer means the opposite.

## Self-healing

The loop tolerates corrupt timeline state without stalling. A timeline entry
whose payload is missing is removed during the Claim (it can never be delivered);
a member whose id is not valid UTF-8 is removed during the Due scan. Either way
the poll recovers instead of looping on an undeliverable entry.

## Tuning

Per-Topic knobs, set when the subscriber is declared:

- `polling_interval` (default 0.05s) — how often an active loop polls.
- `max_polling_interval` (default 5.0s) — the ceiling the idle backoff ramps to.
- `max_concurrent` (default 5) — concurrent handlers and per-tick fetch size.
- `lease_ttl` (default 30s) — the redelivery window (see at-least-once above).
