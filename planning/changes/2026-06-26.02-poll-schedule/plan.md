# Poll schedule — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the inline poll-loop backoff from `TimersSubscriber._consume`
into a pure, table-testable `PollSchedule`, leaving `_consume` with only I/O and
control flow — no public-API or observable-timing change.

**Architecture:** New `faststream_redis_timers/subscriber/schedule.py` with a
stateful `PollSchedule` (two counters + injected jitter; methods
`delay_after_fetch(count)` / `delay_after_error()`; named caps `_MAX_EXPONENT`,
`_MAX_ERROR_DELAY`). `_consume` constructs it from config and sleeps for what it
returns. See the spec ([`design.md`](./design.md)) for the seven decisions and
the exact formulas.

**Tech Stack:** Python 3.13, anyio, `uv`, `ruff`, `ty`, `pytest` (the
`PollSchedule` unit tests need no Redis; the loop suites run under docker compose).

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/poll-schedule`

**Commit strategy:** Per-task commits. Behavior-preserving — existing loop tests
(`test_delivery`, `_consume` start-signal + error-log unit tests,
`test_concurrency`) stay UNEDITED and green at every step.

---

### Task 1: Create `PollSchedule` with pure unit tests

**Files:**
- Create: `faststream_redis_timers/subscriber/schedule.py`
- Modify: `tests/test_unit.py` (add `PollSchedule` tests)

- [ ] **Step 1 (RED): Table tests first**

  In `tests/test_unit.py`, add `PollSchedule` tests with injected midpoint jitter
  (`lambda: 1.0`): busy (`delay_after_fetch(1)` → `0.0`, resets idle); idle ramp
  (`delay_after_fetch(0)` → `base`, `2*base`, … capped at `max_idle`);
  back-pressure (`delay_after_fetch(-1)` → `base`, idle unchanged); error ramp
  (`delay_after_error()` → `1.0`, `2.0`, … capped at `_MAX_ERROR_DELAY`); the
  `_MAX_EXPONENT` counter cap; reset rules (any fetch clears `error_attempt`;
  only busy clears `idle_count`); and a `jitter=lambda: 0.5`/`1.5` bounds check.
  Run — expect failure (module absent).

- [ ] **Step 2 (GREEN): Implement `PollSchedule`**

  Per design.md decisions 1-4: `__init__(*, base, max_idle, jitter=_default_jitter)`;
  module-private `_default_jitter`, `_MAX_EXPONENT = 30`, `_MAX_ERROR_DELAY = 30.0`;
  the two methods with the exact formulas and reset rules. No I/O.

- [ ] **Step 3: Tests pass + 100%**

  `uv run pytest tests/test_unit.py -v --no-cov` (iterate), then `just test` to
  confirm the full gate (`schedule.py` must be 100% from these unit tests).

- [ ] **Step 4: Commit** (`feat: add PollSchedule for poll-loop backoff`)

---

### Task 2: Rewire `_consume` to use `PollSchedule`

**Files:**
- Modify: `faststream_redis_timers/subscriber/usecase.py`

- [ ] **Step 1: Replace the inline backoff**

  Construct `schedule = PollSchedule(base=…polling_interval, max_idle=…max_polling_interval)`
  before the loop. Replace the inline `idle_count`/`error_attempt`/jitter/cap
  logic: except branch → `delay = schedule.delay_after_error()`; else branch →
  `delay = schedule.delay_after_fetch(fetched)`; after the `finally`,
  `if delay: await anyio.sleep(delay)`. Remove `import random` and the
  `_BACKOFF_EXP_CAP` constant (now in `schedule.py`). Keep the limiter, ping,
  `start_signal`, task group, `while self.running`, and the error `self._log`.

- [ ] **Step 2: Lean on the existing loop tests**

  `just test` → green. Of note: `test_consume_sets_start_signal_when_ping_returns_false`
  (start-signal ordering), `test_consume_logs_get_msgs_error_with_repr` (error
  path), `test_delivery` (busy), `test_concurrency` (back-pressure). None should
  need edits. Check `term-missing`; if the `if delay:` guard or a loop branch is
  uncovered, add ONE focused test.

- [ ] **Step 3: Commit** (`refactor: drive _consume backoff through PollSchedule`)

---

### Task 3: Final validation

- [ ] **Step 1: `just lint`** — ruff + `ty` clean (use `ty: ignore`); confirm
  `import random` and `_BACKOFF_EXP_CAP` are gone from `usecase.py`.
- [ ] **Step 2: `just test`** — full suite, 100% coverage, all green.
- [ ] **Step 3: `just check-planning`** — `planning: OK`; finalize this bundle's
  `summary:` to the realized result.
- [ ] **Step 4: Open the PR** per `CLAUDE.md` (push, open, watch CI).

---

## Validation summary (post-implementation)

- `subscriber/schedule.py` exists with `PollSchedule` at 100% coverage from pure
  unit tests; `usecase.py` has no `import random`, no `_BACKOFF_EXP_CAP`, no
  inline backoff math.
- `_consume` reads as fetch → decide delay → (maybe) sleep; limiter/control flow
  unchanged.
- All existing suites pass unedited; observable timing unchanged.

## Risks & mitigations

- **Backoff drift.** The new unit tests pin the exact formulas; the loop suites
  guard integration. Any red is a real regression, not a test to "fix."
- **`start_signal` ordering.** The sleep moves after the `finally`; preserved and
  covered by the start-signal test. If that test goes red, the ordering is wrong —
  stop and fix the loop, don't edit the test.
- **Docker for `just test`.** If unavailable, `uv run pytest tests/test_unit.py
  --no-cov` covers `PollSchedule`; note in the PR that the Redis loop suites
  weren't run locally.
