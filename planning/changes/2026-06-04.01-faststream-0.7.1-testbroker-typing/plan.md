# FastStream 0.7.1 TestBroker typing alignment — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop our `TestTimersBroker.__aenter__` workaround now that FastStream 0.7.1 fixes the `Broker | list[Broker]` typing bug, and align our generics with upstream's new `TestBroker[Broker, EnterType]` shape.

**Architecture:** Bump the FastStream pin to `>=0.7.1`, bind `EnterType = TimersBroker` in our subclass generic, delete the override and its assert, update the ASGI registry annotation to two type params, and add a regression test that proves the entered context yields a single `TimersBroker` (not a list/tuple).

**Tech Stack:** Python 3.13, FastStream 0.7.1, `uv` for deps, `ruff` for lint, `ty` for type check, `pytest` (under docker compose for the Redis-backed suites).

**Spec:** [`planning/specs/2026-06-04-faststream-0.7.1-testbroker-typing-design.md`](../specs/2026-06-04-faststream-0.7.1-testbroker-typing-design.md)

**Test placement note:** The regression test is placed in `tests/test_fake.py` rather than `tests/test_unit.py` (which the spec suggested). The test enters the `TestTimersBroker` context, which is the exact pattern `test_fake.py` already exercises, and `test_unit.py` is described in `CLAUDE.md` as "pure unit tests" that don't enter test brokers. Flag for spec-update if you'd rather it live in `test_unit.py`.

**Commit strategy:** Single bundled commit at the end of Task 5. Tasks 1–4 stage incrementally without committing, so that intermediate `ty check` runs reflect work-in-progress and the final commit captures one logical change (the spec calls for this).

---

### Task 1: Bump the FastStream pin to >=0.7.1

**Files:**
- Modify: `pyproject.toml:12`

- [ ] **Step 1: Edit the dependency line**

In `pyproject.toml`, change:

```toml
"faststream>=0.7,<0.8",
```

to:

```toml
"faststream>=0.7.1,<0.8",
```

- [ ] **Step 2: Refresh the lockfile and sync**

Run: `just install`

This runs `uv lock --upgrade` followed by `uv sync --all-extras --all-groups --frozen`. Expected: `uv` resolves `faststream==0.7.1` (the only version satisfying both `>=0.7.1` and `<0.8` at time of writing). The sync should report no errors.

- [ ] **Step 3: Confirm the resolved version**

Run: `uv pip show faststream | grep -i version`
Expected output: `Version: 0.7.1`

- [ ] **Step 4: Sanity-run the no-Redis tests against the upgraded library**

Run: `uv run pytest tests/test_unit.py tests/test_fake.py -v`
Expected: all tests pass (the override still satisfies the typing contract under 0.7.1, since `EnterType` defaults to `Any`). If anything fails here, **stop** — the upgrade has surfaced an unrelated regression that needs investigation before refactoring.

- [ ] **Step 5: Stage the change (do not commit yet)**

Run: `git add pyproject.toml uv.lock`

(If `uv.lock` is not tracked in this repo, drop it from the `git add`; check `git status` first.)

---

### Task 2: Add the regression test for `__aenter__` return shape

**Files:**
- Modify: `tests/test_fake.py` (append new test at the end of the file)

This test is added *before* the refactor so we can prove the contract (single `TimersBroker` returned from the context, never a list or tuple) survives the workaround removal. Under the current code (override returns `TimersBroker` directly) the test should pass on the first run.

- [ ] **Step 1: Append the new test to `tests/test_fake.py`**

Add this test as the last function in the file:

```python
async def test_test_broker_aenter_returns_single_timers_broker() -> None:
    """0.7.1's EnterType binding means TestTimersBroker yields a single TimersBroker, not a list/tuple.

    Guards the contract through the upstream typing refactor: even if the base
    class signature changes again, our single-broker subclass must always hand
    back a single broker instance.
    """
    broker = TimersBroker()
    async with TestTimersBroker(broker) as tb:
        assert isinstance(tb, TimersBroker)
        assert not isinstance(tb, (list, tuple))
```

No new imports needed — `TestTimersBroker` and `TimersBroker` are already imported at the top of `tests/test_fake.py`.

- [ ] **Step 2: Run the new test to confirm it passes against the current code**

Run: `uv run pytest tests/test_fake.py::test_test_broker_aenter_returns_single_timers_broker -v`
Expected: PASS. (The current `__aenter__` override returns the single `TimersBroker`, so the assertions hold.)

- [ ] **Step 3: Stage the change**

Run: `git add tests/test_fake.py`

---

### Task 3: Refactor `TestTimersBroker` — bind `EnterType`, drop the override

**Files:**
- Modify: `faststream_redis_timers/testing.py:34-45`

- [ ] **Step 1: Replace the class declaration and remove the override**

In `faststream_redis_timers/testing.py`, locate the current block (lines 34–45):

```python
class TestTimersBroker(TestBroker[TimersBroker]):
    scheduled_timers: list[ScheduledTimer]

    def __init__(self, broker: TimersBroker, **kwargs: typing.Any) -> None:
        super().__init__(broker, **kwargs)
        self.scheduled_timers = []

    async def __aenter__(self) -> TimersBroker:
        # __init__ enforces a single broker, so upstream's multi-broker list branch is unreachable.
        result = await super().__aenter__()
        assert not isinstance(result, list)  # noqa: S101
        return result
```

Replace with:

```python
class TestTimersBroker(TestBroker[TimersBroker, TimersBroker]):
    scheduled_timers: list[ScheduledTimer]

    def __init__(self, broker: TimersBroker, **kwargs: typing.Any) -> None:
        super().__init__(broker, **kwargs)
        self.scheduled_timers = []
```

The base `__aenter__` returns `EnterType`, which we now bind to `TimersBroker`, so the override is redundant.

- [ ] **Step 2: Re-run the regression test from Task 2**

Run: `uv run pytest tests/test_fake.py::test_test_broker_aenter_returns_single_timers_broker -v`
Expected: PASS. (Now the result comes from the base class via `EnterType = TimersBroker` instead of our override.)

- [ ] **Step 3: Re-run the full `test_fake.py` suite to confirm no regression in fake-broker usage**

Run: `uv run pytest tests/test_fake.py -v`
Expected: all 15 tests pass (every test uses `async with TestTimersBroker(broker)`; if `EnterType` were wired wrong, `tb.publish(...)` calls would explode).

- [ ] **Step 4: Stage the change**

Run: `git add faststream_redis_timers/testing.py`

---

### Task 4: Update the ASGI registry annotation

**Files:**
- Modify: `faststream_redis_timers/__init__.py:28`

- [ ] **Step 1: Update the return type annotation**

In `faststream_redis_timers/__init__.py`, locate line 28:

```python
    def get_broker_registry() -> dict[type[BrokerUsecase[typing.Any, typing.Any]], type[TestBroker[typing.Any]]]:
```

Replace with:

```python
    def get_broker_registry() -> dict[type[BrokerUsecase[typing.Any, typing.Any]], type[TestBroker[typing.Any, typing.Any]]]:
```

This matches the new shape of `faststream.asgi.factories.asyncapi.try_it_out._get_broker_registry`, which 0.7.1 typed as `dict[..., type[TestBroker[Any, Any]]]`.

- [ ] **Step 2: Confirm `ty` is satisfied with the new annotation**

Run: `uv run ty check faststream_redis_timers/__init__.py`
Expected: no errors (or, if `ty check` requires the whole project, run `uv run ty check` and confirm no new errors compared to a clean baseline).

- [ ] **Step 3: Stage the change**

Run: `git add faststream_redis_timers/__init__.py`

---

### Task 5: Final validation and bundled commit

**Files:**
- All four changes above are now staged together.

- [ ] **Step 1: Lint the staged changes**

Run: `just lint`
Expected: `eof-fixer`, `ruff format`, `ruff check --fix`, and `ty check` all pass. If `ruff format` or `ruff check --fix` modifies any staged file, re-stage with `git add <modified-files>`.

- [ ] **Step 2: Run the full test suite (under docker compose, with Redis)**

Run: `just test`
Expected: every test in `tests/test_unit.py`, `tests/test_fake.py`, `tests/test_delivery.py`, `tests/test_cancel.py`, `tests/test_isolation.py`, and `tests/test_envelope.py` passes. The new regression test from Task 2 should appear in the output and pass.

- [ ] **Step 3: Review staged diff one more time**

Run: `git diff --staged`
Expected: changes only in `pyproject.toml`, `uv.lock` (if tracked), `tests/test_fake.py`, `faststream_redis_timers/testing.py`, and `faststream_redis_timers/__init__.py`. No drive-by edits.

- [ ] **Step 4: Commit**

Run:

```bash
git commit -m "$(cat <<'EOF'
chore: adopt faststream 0.7.1 TestBroker typing fix

ag2ai/faststream#2903 makes TestBroker generic over a second EnterType
TypeVar (default Any) and threads it through __aenter__. Bind
EnterType = TimersBroker in our TestTimersBroker, delete the
__aenter__ override + isinstance(list) assert that worked around the
old Broker | list[Broker] return type, and update the ASGI registry
annotation to the new two-param shape. Bumps the floor to >=0.7.1.

Adds a regression test guarding the single-broker contract through
future upstream changes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Verify clean tree**

Run: `git status`
Expected: working tree clean; one new commit on the current branch.

---

## Validation summary (post-implementation)

After Task 5, the following should hold:

- `pyproject.toml` requires `faststream>=0.7.1,<0.8`.
- `TestTimersBroker` declares `TestBroker[TimersBroker, TimersBroker]` with no `__aenter__` override.
- The ASGI registry hook in `__init__.py` is annotated `TestBroker[typing.Any, typing.Any]`.
- `tests/test_fake.py::test_test_broker_aenter_returns_single_timers_broker` is present and passing.
- `just lint` and `just test` both succeed.

## Risks & mitigations

- **Upstream AST helper depth.** Our `TestTimersBroker.__init__` adds an extra frame on top of `TestBroker.__init__`. The 0.7.1 PR adds a `while … name == "__init__"` walk in `_internal/testing/ast.py` exactly for this, so the `with` AST analysis still finds the user frame. Validated by Task 3 Step 3 (the full `test_fake.py` suite, which depends on this mechanism). No code change required on our side.
- **`uv lock --upgrade` pulling in unrelated upgrades.** `just install` runs `uv lock --upgrade` which refreshes *all* dependencies. If this surfaces incidental breakage, narrow the upgrade in Task 1 Step 2 to `uv lock --upgrade-package faststream` and re-run `uv sync --frozen` to avoid pulling in unrelated changes.
- **`just test` requires Docker.** If Docker isn't running locally, `just test` will fail at the compose step. Either start Docker before Task 5 Step 2, or run `uv run pytest tests/test_unit.py tests/test_fake.py -v` as a partial substitute (this skips the Redis-backed suites — note this in the PR description if you couldn't run the full suite).
