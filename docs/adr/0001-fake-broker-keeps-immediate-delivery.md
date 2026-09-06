# The fake broker keeps immediate delivery; no in-memory `TimerStore`

**Decision:** `TestTimersBroker` keeps its current model — the fake producer encodes and dispatches
every published Timer immediately to the handler via `process_message`, regardless of its Activation
time. We do **not** add an `InMemoryTimerStore` adapter or a `TimerStore` `Protocol` for testing.

## Context

An architecture review proposed that "the fake fakes the wrong layer": put a real
`InMemoryTimerStore` behind the `TimerStore` seam so the fake broker exercises real Claim / Lease /
Commit and truthful inspection, instead of stubbing the Redis client and dispatching immediately.
Three defects were claimed: (1) the fake duplicates the envelope encode; (2) `has_pending`,
`get_pending_timers` and `cancel_all` are stubbed to canned empties ("lies"); (3) at-least-once and
Lease semantics cannot be tested through the fake. The options weighed were: A — drive the *real*
subscriber poll loop against an in-memory store; B — a real in-memory store for state with
deterministic delivery; or drop it.

## Decision & rationale

Researching FastStream's own Redis broker (`faststream/redis/testing.py`) dismantled the premises:

- **The encode is not duplicated.** FastStream's `FakeProducer.publish` also encodes via
  `build_message` / `message_format.encode` — encoding is inherent to the fake-producer pattern, not
  a smell. `FakeTimersProducer` mirrors it.
- **The inspection stubs are not lies.** FastStream fakes *every* subscriber — including the polling
  list subscriber, our closest analog — by bypassing the poll loop and calling
  `handler.process_message` directly from the fake producer; it never runs the real loop in tests.
  Under an immediate-delivery contract a published Timer has already fired and been removed, so
  `has_pending → False`, `get_pending_timers → []` and `cancel_all → 0` are *truthful*, not stubbed
  lies.
- **Option A is non-idiomatic and fragile.** Running the real `_consume` loop under FastStream's
  `TestBroker` means skipping `_fake_start` — forfeiting the handler-mock wiring every FastStream
  test broker relies on — and driving an infinite 50 ms poll loop inside a unit test; a spike doing
  so hung at teardown.

That leaves only one way to make inspection report *pending* future Timers: stop delivering future
Timers immediately. That is a **breaking change** to a public testing API — existing user tests
publish a future Timer and expect their handler to fire without waiting — so it is rejected. With
immediate delivery retained the inspection methods are already correct, and the proposal has no
remaining defect to fix. `scheduled_timers` already lets users assert what was Scheduled.

**Revisit trigger:** a concrete need to test Schedule / Pending / cancel semantics — a future Timer
observed as Pending before it fires — through the fake. If that arises, prefer an **opt-in**
`TestTimersBroker(..., respect_activation=True)` (default off, so non-breaking) that withholds
not-yet-Due Timers; not a change to the default immediate-delivery contract, and not a real
subscriber loop in tests.
