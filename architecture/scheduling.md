# Scheduling & cancellation

The producer side: how a Timer is created, cancelled, and inspected. Scheduling a
Timer records it in the [TimerStore](timer-store.md); what happens when it comes
Due is [delivery](delivery.md).

## Scheduling a Timer

`broker.publish(message, topic, *, timer_id="", activate_in=…, activate_at=…,
correlation_id=…, headers=…)` **Schedules** a Timer: it encodes the message and
records it on *topic* with an Activation time. It returns the Timer's id — keep it
to Cancel or inspect the Timer later.

The Topic must be non-empty. The message is encoded once at publish time (see the
wire format) and stored as an opaque payload until delivery.

## The Activation model

When the Timer becomes Due is set by exactly one of two arguments, resolved to a
single absolute UTC instant:

- **`activate_in`** (a `timedelta`, default `0`) — relative: the Activation time
  is *now + activate_in*. The default (`timedelta(0)`) and any negative delta
  mean "Due immediately."
- **`activate_at`** (a `datetime`) — absolute. It must be **timezone-aware**
  (a naive datetime is a `ValueError`); a past instant is kept as-is, so it fires
  immediately.

Passing **both** is a `ValueError` — pick one. Everything is normalized to UTC,
so Activation times are unambiguous across clocks.

## Timer identity

`timer_id` is the handle for a Timer's whole lifecycle (Schedule → Cancel /
inspect). Supply your own to make a Timer addressable and idempotent to
re-Schedule; omit it and one is generated. Either way `publish` returns it. The
`correlation_id` defaults to the `timer_id` when not given, so a Timer is
traceable by default.

## Cancellation

- **`cancel_timer(topic, timer_id)`** — remove one Pending Timer. A no-op if it
  has already fired or never existed.
- **`cancel_all(topic) -> int`** — remove every Pending Timer on *topic* and
  return how many were removed. A handler already running for a Timer whose Lease
  is held runs to completion; its Commit afterwards is a harmless no-op because
  the keys are already gone.

Cancellation is the same removal the store uses for Commit — a cancelled Timer is
simply gone, never delivered.

## Inspecting Pending Timers

- **`has_pending(topic, timer_id) -> bool`** — is this Timer still Pending?
- **`get_pending_timers(topic, before=None) -> list[str]`** — the Pending Timer
  ids, optionally only those Due by *before*.

A Timer currently being delivered has its Activation time pushed `lease_ttl` into
the future (its Lease), so it still counts as Pending in the default result but
is excluded once *before* is the current time — the difference between "scheduled
or in-flight" and "actually Due right now."
