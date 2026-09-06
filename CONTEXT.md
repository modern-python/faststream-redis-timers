# faststream-redis-timers

A [FastStream](https://faststream.airt.ai) broker integration for Redis-backed distributed timer
scheduling: publish a message now, have it delivered to a subscriber at a future instant, with
at-least-once delivery across a fleet of workers sharing one Redis.

## Language

A term is listed only when there is a synonym to reject, or a meaning subtle enough that code and
docs must agree on it. General programming vocabulary does not belong here, however heavily this
package uses it. Class and method names that mean what they say (`TimerStore`, `cancel_timer`) are
not listed — read the module.

FastStream owns the framing vocabulary this package plugs into — broker, subscriber, publisher,
router, message, handler, `ack`/`nack`/`reject`. Nothing here redefines one of those.

**Timer**:
A scheduled future delivery: a message bound to a Topic that becomes deliverable at its Activation
time, identified by a `timer_id`. The Timer is the *record*, not the message it carries — a Timer
has a lifecycle (Scheduled → Due → Claimed → Committed) that its payload does not.

**Topic**:
The named channel a Timer is Scheduled on and that a subscriber consumes from. Two Redis keys are
derived per Topic; a Timer only ever exists on one.
_Avoid_: queue — a Topic is not a work queue, and the difference matters: Timers on a Topic are
ordered by Activation time, not arrival, and a Claimed Timer stays on the Topic rather than leaving
it. `channel` survives only where FastStream owns the spelling: the `raw_message` field and the
log-context key. In our own prose it is Topic.

**Activation time**:
The single absolute UTC instant at which a Timer becomes Due. Exactly one of `activate_in` (a
`timedelta` from now) or `activate_at` (a timezone-aware `datetime`) sets it; passing both, or a
naive `datetime`, is a `ValueError`. This one number is also the Lease marker: Claiming a Timer
advances its Activation time rather than moving the Timer anywhere, so "Activation time" reads
differently before and after a Claim.

**Schedule**:
To register a new Timer to become Due at its Activation time. The method is `publish()` — FastStream
names every producer entry point that way and this package keeps the parity — but the domain verb is
Schedule, and prose should use it. There is no separate publish concept.

**Due**:
Describes a Timer whose Activation time has passed, and which is therefore eligible to be Claimed.
Due is derived, never stored: it is a comparison against the current time, which is why the same
Timer is Due to a poll one moment and not the next.

**Pending**:
Describes a Timer that has been Scheduled and neither Committed nor cancelled — *including* one
currently Claimed, whose Activation time sits in the future under its Lease. `has_pending` is
therefore true for a Timer whose handler is already running; `get_pending_timers(before=now)`
excludes those.

**Claim**:
To take a Due Timer for processing by advancing its Activation time by the Lease, in one atomic
step, so no other worker sees it as Due. A Claim is not a lock: there is no lock key, no owner
recorded, and nothing to release. A contested Claim returns nothing and is simply skipped.

**Lease**:
The time window a Claim buys, `lease_ttl` seconds wide. It expires on its own; a worker that dies
mid-handler releases nothing, the Timer simply becomes Due again. A handler that outruns its Lease
can be redelivered while still running — that is what makes delivery at-least-once rather than
exactly-once.

**Commit**:
To remove a Timer permanently once a handler has accounted for it, via `ack` or `reject`. `nack` is
not a Commit: it does nothing, and the Lease expiring is what causes redelivery. Cancellation
performs the identical removal, which is why the store exposes one `remove` and not two.
