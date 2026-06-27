# Fake broker (TestTimersBroker)

`TestTimersBroker` lets a user test their handlers without a running Redis. It is
the FastStream test-broker pattern applied to timers: enter it as an async
context manager around a `TimersBroker`, publish, and assert on what the handler
did — synchronously, in-process, no containers.

```python
async with TestTimersBroker(broker) as br:
    await br.publish("payload", topic="jobs", timer_id="t1")
    # the handler for "jobs" has already run
```

## Immediate-delivery contract

Inside the fake, **every published Timer is delivered immediately, regardless of
its Activation time** — `activate_in` / `activate_at` are recorded but not waited
on. The fake producer encodes the message and dispatches it straight to the
matching subscriber's handler; the real poll loop, Claim, and Lease never run.
So a `publish` returns only after the handler has been invoked, which is what
makes fake tests deterministic and instant.

This is a deliberate contract, not a shortcut — see the decision to
[keep immediate delivery](../planning/decisions/2026-06-26-reject-fake-broker-inmemory-store.md).
It matches how FastStream fakes its own polling brokers (dispatch to the handler,
don't run the loop).

## Capturing what was scheduled

The broker exposes `scheduled_timers: list[ScheduledTimer]` — one record per
`publish` (topic, timer_id, resolved activate_at, body, correlation_id, headers).
Even though delivery is immediate, this captures the *scheduling intent*, so a
test can assert what would have been scheduled (including the future Activation
time it computed) independently of the handler running.

## No Redis, and what that means for inspection

The fake stubs the connection — nothing talks to Redis. Because every Timer fires
immediately and is then gone, the broker's inspection surface reports an empty
world: `has_pending` is `False`, `get_pending_timers` is `[]`, `cancel_all` is
`0`, and `cancel_timer` is a no-op. These are **truthful** under the
immediate-delivery contract (nothing is ever left Pending), not stubs that lie —
use `scheduled_timers` to assert on scheduling.

## The boundary

The fake deliberately does **not** exercise the lease-based mechanics from
[delivery](delivery.md): the poll/Claim loop, the Lease window, nack-retry, or
the at-least-once guarantee. Those depend on real Redis and real time, and are
covered by the integration suites (`test_delivery`, `test_at_least_once`,
`test_cancel`, …) which run against a Redis container. The split is intentional:
the fake is for testing *your handler's logic*; the integration suites prove the
*delivery semantics*.
