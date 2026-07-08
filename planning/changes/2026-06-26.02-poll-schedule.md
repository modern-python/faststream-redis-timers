---
summary: Extracted the subscriber's poll-loop backoff into a pure, table-tested PollSchedule (subscriber/schedule.py); _consume now holds only I/O and control flow. Behavior-preserving.
---

# Poll schedule — design

## Goal

Lift the backoff state machine out of `TimersSubscriber._consume`
(`subscriber/usecase.py:86-119`) into a pure `PollSchedule`. Today idle backoff,
error backoff, jitter, two counters, and two caps are interwoven inline in an
async loop, so the only way to test the backoff math is to drive the whole loop.
After this change the math is a deterministic object the loop calls; `_consume`
keeps only I/O and control flow.

This is **candidate 3** of the architecture review. It is an internal,
behavior-preserving refactor — no public API or observable-timing change.

## Background

`_consume` interleaves three concerns: (1) the poll/claim loop (I/O), (2)
concurrency control (the `CapacityLimiter`), and (3) backoff timing. The timing
piece (`usecase.py:91-116`) carries:

- two counters, `idle_count` and `error_attempt`, each capped at
  `_BACKOFF_EXP_CAP = 30` so `2**n` cannot overflow;
- **two different** delay formulas — idle is `base * 2**(n-1) * jitter` capped at
  `max_idle` (5.0s); error is `2**(n-1) * jitter` (no `base` factor) capped at a
  hardcoded `30.0`;
- shared jitter `random.uniform(0.5, 1.5)`;
- reset rules: any non-exception fetch clears `error_attempt`; only a busy fetch
  (`count > 0`) clears `idle_count`.

The two `30`s mean different things (one is an exponent cap, one a seconds cap)
but read as a confusing coincidence inline. The whole block is reachable only by
running the loop.

## Design

A stateful, I/O-free `PollSchedule` in a new module
`faststream_redis_timers/subscriber/schedule.py`. Seven decisions, settled in
review:

1. **Stateful object, two methods.** It holds the two counters + config + an
   injected jitter source, and exposes `delay_after_fetch(count)` and
   `delay_after_error()`. The loop does the `anyio.sleep`; the schedule never
   does I/O. ("Pure" = no I/O + deterministic given the jitter, not stateless.)

2. **Jitter injected.** Constructor param `jitter: Callable[[], float] =
   _default_jitter`, where `_default_jitter()` returns `random.uniform(0.5, 1.5)`.
   The schedule just calls `self._jitter()` for a multiplier; the `(0.5, 1.5)`
   range stays encapsulated in the default. Tests inject `lambda: 1.0` (midpoint
   → un-jittered base) or `0.5`/`1.5` for the bounds.

3. **Explicit config + named caps.** `PollSchedule(*, base, max_idle, jitter=…)`
   takes the two floats directly (decoupled from `TimerSub`, trivial to construct
   in tests). The two constants move into `schedule.py` with distinct names that
   end the "two 30s" confusion: `_MAX_EXPONENT = 30` (counter cap) and
   `_MAX_ERROR_DELAY = 30.0` (seconds cap). No new `TimerSub` field — the error
   cap stays internal (this is a refactor, not a feature).

4. **Faithful semantics.**
   - `delay_after_fetch(count)`: resets `error_attempt = 0` every call, then —
     `count > 0` → `idle_count = 0`, return `0.0`; `count == 0` →
     `idle_count = min(idle_count+1, _MAX_EXPONENT)`, return
     `min(base * 2**(idle_count-1) * jitter(), max_idle)`; `count < 0` → return
     `base`, leave `idle_count` unchanged.
   - `delay_after_error()`: `error_attempt = min(error_attempt+1, _MAX_EXPONENT)`,
     return `min(2**(error_attempt-1) * jitter(), _MAX_ERROR_DELAY)`; leaves
     `idle_count` untouched.
   - The loop guards `if delay: await anyio.sleep(delay)` so the busy case
     (`0.0`) does **no** sleep, exactly as today.

5. **Home + name.** `subscriber/schedule.py`, class `PollSchedule` — beside its
   only caller (not top-level like `store.py`, which is shared). `_consume`
   constructs it once from config; `usecase.py` loses `import random` and
   `_BACKOFF_EXP_CAP`.

6. **Testing.** Pure table unit tests for `PollSchedule` (midpoint jitter) cover
   every branch and cap to 100%. The loop wiring rides on existing tests
   (delivery → busy; start-signal test → idle; error-log test → error). No
   existing test is coupled to backoff internals, so none change.

7. **Scope.** `PollSchedule` owns only the delay math. The `CapacityLimiter`,
   ping/`start_signal`, task group, `while self.running`, and error logging stay
   in `_consume`. `_get_msgs`/`_claim_and_consume` are untouched. The vestigial
   `client` param (a deferred Minor from candidate 1) stays. No `architecture/`
   promotion (no capability page documents poll scheduling; behavior unchanged).

The loop after the change:

```python
schedule = PollSchedule(
    base=self._config.timer_sub.polling_interval,
    max_idle=self._config.timer_sub.max_polling_interval,
)
async with anyio.create_task_group() as tg:
    while self.running:
        try:
            fetched = await self._get_msgs(client, tg, limiter)
        except Exception as e:  # noqa: BLE001
            self._log(log_level=logging.ERROR, message=f"Message fetch error: {e!r}", exc_info=e)
            delay = schedule.delay_after_error()
        else:
            delay = schedule.delay_after_fetch(fetched)
        finally:
            if not start_signal.is_set():
                start_signal.set()
        if delay:
            await anyio.sleep(delay)
```

(Note: the `if delay:` sleep moves *after* the `finally` so `start_signal` is set
before any wait — same ordering as today, where the `finally` runs before the
loop re-enters.)

## Scope

### In scope
- New `faststream_redis_timers/subscriber/schedule.py` (`PollSchedule` +
  `_default_jitter`, `_MAX_EXPONENT`, `_MAX_ERROR_DELAY`).
- Rewire `_consume` in `subscriber/usecase.py` to construct and call it; drop the
  inline counters/jitter/caps, `import random`, and `_BACKOFF_EXP_CAP`.
- New pure unit tests for `PollSchedule`.

### Out of scope
- `_get_msgs` / `_claim_and_consume` / the limiter / ping / start-signal logic.
- The vestigial `client` parameter cleanup (separate deferred item).
- Any public-API, config, or observable-timing change.

## Testing

- **Unit (no Redis):** table-driven `PollSchedule` tests with injected midpoint
  jitter — idle ramp + `max_idle` cap, error ramp + `_MAX_ERROR_DELAY` cap, the
  `_MAX_EXPONENT` counter cap, busy/back-pressure cases, and both reset rules;
  plus a `0.5`/`1.5` jitter-bounds check. To 100%.
- **Integration/loop:** existing suites are the behavior-preserving net
  (`test_delivery`, the `_consume` start-signal + error-log unit tests,
  `test_concurrency` for back-pressure). Confirm 100% via `term-missing`; add a
  focused loop test only if a branch (e.g. the `if delay:` guard) is uncovered.
- `just lint` (ruff + `ty`) and `just test`.

## Risk

- **Behavior drift in the backoff.** Mitigated by faithful reproduction
  (decision 4) and the untouched loop tests; the new unit tests pin the exact
  formulas.
- **`start_signal` ordering.** The sleep moves after the `finally`; the design
  preserves "set start_signal before waiting." Covered by
  `test_consume_sets_start_signal_when_ping_returns_false`.

## Rollout

- Single implementing PR on `feat/poll-schedule` (this branch may carry both the
  bundle and the implementation). Behavior-preserving; no doc promotion.
- Workflow: this spec → plan → subagent-driven-development (TDD) →
  requesting-code-review → finishing-a-development-branch.
