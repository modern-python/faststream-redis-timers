---
status: accepted
summary: Keep TestTimersBroker's immediate-delivery fake; reject an in-memory TimerStore adapter for it (architecture-review candidate 2).
supersedes: null
superseded_by: null
---

# Keep the immediate-delivery fake broker; no in-memory TimerStore adapter

**Decision:** `TestTimersBroker` keeps its current model — the fake producer
encodes and dispatches every published timer immediately to the handler via
`process_message`, regardless of `activate_at`. We do **not** add an
`InMemoryTimerStore` adapter or a `TimerStore` Protocol for testing.

## Context

The architecture review proposed candidate 2, "the fake fakes the wrong layer":
put a real `InMemoryTimerStore` behind the (now-real) `TimerStore` seam so the
fake broker exercises real claim/lease/commit and truthful inspection, instead
of mocking the Redis client and dispatching immediately. Three defects were
claimed: (1) the fake duplicates the envelope encode; (2) `has_pending` /
`get_pending_timers` / `cancel_all` are stubbed to canned empties ("lies"); (3)
at-least-once / lease semantics can't be tested through the fake. The options
weighed were: A — drive the *real* subscriber poll loop against an in-memory
store; B — real in-memory store for state with deterministic delivery; or drop
it.

## Decision & rationale

Researching FastStream's own Redis broker (`faststream/redis/testing.py`)
dismantled the premises:

- **The encode is not duplicated.** FastStream's `FakeProducer.publish` also
  encodes via `build_message`/`message_format.encode` — encoding is inherent to
  the fake-producer pattern, not a smell. Our `FakeTimersProducer` mirrors it.
- **The inspection stubs are not lies.** FastStream fakes *every* subscriber —
  including the polling list subscriber, our closest analog — by bypassing the
  poll loop and calling `handler.process_message` directly from the fake
  producer; it never runs the real loop in tests. Under an immediate-delivery
  contract, a published timer has already fired and been removed, so
  `has_pending → False`, `get_pending_timers → []`, `cancel_all → 0` are all
  *truthful*, not stubbed lies.
- **Model A is non-idiomatic and fragile.** Running the real `_consume` loop
  under FastStream's `TestBroker` means skipping `_fake_start` (forfeiting the
  handler-mock wiring every FastStream test broker relies on) and driving an
  infinite 50 ms poll loop inside a unit test; a spike doing so hung at teardown.

That leaves only one way to make inspection report *pending* future timers:
stop delivering future timers immediately. That is a **breaking change** to a
public testing API — existing user tests publish a future timer and expect their
handler to fire without waiting — so it is rejected. With immediate delivery
retained, the inspection methods are already correct, and candidate 2 has no
remaining defect to fix. `scheduled_timers` already lets users assert what was
scheduled.

## Revisit trigger

A concrete need to test *scheduling/pending/cancel* semantics (a future timer
observed as pending before it fires) through the fake. If that arises, prefer an
**opt-in** `TestTimersBroker(..., respect_activation=True)` (default off, so
non-breaking) that withholds not-yet-due timers — not a change to the default
immediate-delivery contract, and not a real subscriber loop in tests.
