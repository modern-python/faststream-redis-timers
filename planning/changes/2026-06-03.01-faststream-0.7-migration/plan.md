# FastStream 0.7 migration — PR1 (defensive pin + planning scaffold) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten the FastStream pin to `>=0.6,<0.7`, adopt `--cov-fail-under=100`, and scaffold the `planning/` workflow directory mirroring `faststream-outbox`. Lands the PR2 design doc in the same commit so PR2 has a home.

**Architecture:** Pure config + docs change. No runtime code touched. Single commit on `chore/pin-faststream-pre-0.7`. The coverage gate is conditional: if `just test` is not at 100% today, the gate addition gets reverted and deferred to PR2 (recorded as decision in commit body).

**Tech Stack:** `pyproject.toml`, `uv`, `pytest-cov`, markdown.

**Related spec:** `planning/specs/2026-06-03-faststream-0.7-migration-design.md`.

---

## Task 1: Create the working branch

**Files:** None (git operation).

- [ ] **Step 1: Confirm clean tree**

Run: `git status`
Expected: `nothing to commit, working tree clean` (a fresh `planning/` dir from the brainstorming session is acceptable; we'll stage it later).

- [ ] **Step 2: Create branch**

Run: `git switch -c chore/pin-faststream-pre-0.7`
Expected: `Switched to a new branch 'chore/pin-faststream-pre-0.7'`

## Task 2: Establish coverage baseline (precondition for gate adoption)

**Files:** None (read-only test run).

The spec's R8 flags that adopting `--cov-fail-under=100` in PR1 requires the suite to already hit 100%. This task discovers the baseline.

- [ ] **Step 1: Run full suite via Justfile**

Run: `just test`
Expected: All tests pass. Final coverage line at bottom of output shows total `%` covered.

- [ ] **Step 2: Record baseline**

Note the total coverage percentage from the report. There are three branches:

- **If `100%`:** Continue to Task 3 — gate adoption is safe.
- **If `<100%` AND missing lines are trivially testable:** Continue to Task 3 but write the backfill tests in Task 3a (insert before Task 4) before adding the gate.
- **If `<100%` AND gaps are non-trivial:** Skip the gate adoption entirely; remove "adopt `--cov-fail-under=100`" from this PR's scope; record decision in commit body; gate moves to PR2 where the orphaned-branch removal naturally lifts coverage.

## Task 3: Tighten the FastStream pin

**Files:**
- Modify: `pyproject.toml` (line 12)

- [ ] **Step 1: Read current dependencies block**

Run: `sed -n '9,14p' pyproject.toml`
Expected output:
```
requires-python = ">=3.13,<4"
license = "MIT"
dependencies = [
    "faststream~=0.6",
    "redis>=5.0",
]
```

- [ ] **Step 2: Edit the pin**

Change `"faststream~=0.6"` to `"faststream>=0.6,<0.7"` on line 12.

- [ ] **Step 3: Verify edit**

Run: `grep -n "faststream" pyproject.toml | grep -v module`
Expected: `12:    "faststream>=0.6,<0.7",`

## Task 4: Adopt `--cov-fail-under=100` (conditional on Task 2)

**Files:**
- Modify: `pyproject.toml` (line 67)

**Skip this task if Task 2 step 2 selected the third branch (`<100%`, non-trivial gaps).**

- [ ] **Step 1: Read current pytest config**

Run: `sed -n '66,70p' pyproject.toml`
Expected output:
```
[tool.pytest.ini_options]
addopts = "--cov=. --cov-report term-missing"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

- [ ] **Step 2: Append the coverage gate to addopts**

Change `addopts = "--cov=. --cov-report term-missing"` to `addopts = "--cov=. --cov-report term-missing --cov-fail-under=100"`.

- [ ] **Step 3: Verify edit**

Run: `grep -n "addopts" pyproject.toml`
Expected: `addopts = "--cov=. --cov-report term-missing --cov-fail-under=100"`

## Task 5: Regenerate lockfile

**Files:**
- Touched (gitignored, not committed): `uv.lock`

`uv.lock` is gitignored in this repo, so the file is local-only. The regeneration confirms the resolver is happy with the tightened pin.

- [ ] **Step 1: Regenerate lock**

Run: `uv lock`
Expected: `Resolved N packages in <time>` with no error. The `faststream` line in `uv.lock` should resolve to a `0.6.x` version (verify by `grep '^name = "faststream"' -A 2 uv.lock`).

- [ ] **Step 2: Sync environment**

Run: `uv sync --all-extras --all-groups --frozen`
Expected: Sync succeeds against the frozen lock.

## Task 6: Verify the gate (re-run suite)

**Files:** None.

- [ ] **Step 1: Re-run full suite under the new gate**

Run: `just test`
Expected: All tests pass; if Task 4 ran, the final line is `Required test coverage of 100% reached`. If Task 4 was skipped, this is just a re-confirmation that the pin change didn't break anything.

## Task 7: Scaffold `planning/` (likely already present from spec-writing)

**Files:**
- Create (if missing): `planning/specs/.gitkeep`
- Create (if missing): `planning/plans/.gitkeep`

- [ ] **Step 1: Check current state**

Run: `ls -la planning/specs planning/plans 2>&1`
Expected: Both directories already exist with `.gitkeep` files and a design doc in `planning/specs/`. (Created at spec-writing time.)

- [ ] **Step 2: Touch any missing `.gitkeep` files**

If either `.gitkeep` is missing:
Run: `touch planning/specs/.gitkeep planning/plans/.gitkeep`

## Task 8: Confirm design + plan docs are on disk

**Files:**
- Verify: `planning/specs/2026-06-03-faststream-0.7-migration-design.md`
- Verify: `planning/plans/2026-06-03-faststream-0.7-migration-pr1-plan.md` (this file)
- Verify: `planning/plans/2026-06-03-faststream-0.7-migration-pr2-plan.md`

- [ ] **Step 1: List planning files**

Run: `ls planning/specs planning/plans`
Expected output:
```
planning/plans:
.gitkeep
2026-06-03-faststream-0.7-migration-pr1-plan.md
2026-06-03-faststream-0.7-migration-pr2-plan.md

planning/specs:
.gitkeep
2026-06-03-faststream-0.7-migration-design.md
```

## Task 9: Add `## Workflow` section to CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read current CLAUDE.md to confirm anchor**

Run: `grep -n "^## " CLAUDE.md`
Expected output:
```
5:## Commands
11:## Tests
```

- [ ] **Step 2: Insert `## Workflow` between `## Commands` and `## Tests`**

After the `## Commands` block (which ends with the `just install` line on line 9) and before the `## Tests` heading on line 11, insert this block (mind the leading blank line):

```markdown

## Workflow

Per-feature workflow: brainstorming → spec in
`planning/specs/YYYY-MM-DD-<slug>-design.md` → writing-plans →
plan in `planning/plans/YYYY-MM-DD-<slug>-plan.md` →
executing-plans / subagent-driven-development →
requesting-code-review → finishing-a-development-branch.

Topic slugs are kebab-case descriptions (e.g. `faststream-0.7-migration`),
not story IDs.
```

- [ ] **Step 3: Verify section order**

Run: `grep -n "^## " CLAUDE.md`
Expected output:
```
5:## Commands
11:## Workflow
22:## Tests
```
(Line numbers approximate; the important thing is `## Workflow` appears between `## Commands` and `## Tests`.)

## Task 10: Verify gitignore does not eat new plan files

**Files:** None (read-only check).

- [ ] **Step 1: Sanity check the gitignore rule**

Run: `git check-ignore -v planning/plans/2026-06-03-faststream-0.7-migration-pr1-plan.md`
Expected: exit code `1` (no output) — the file is NOT ignored.

If exit code is `0` and output names `plan.md` as the rule: the gitignore rule is matching too aggressively (would surprise me but verify). In that case, edit `.gitignore` to anchor the rule: change the bare `plan.md` line to `/plan.md` so it only matches the root.

## Task 11: Run lint

**Files:** None.

- [ ] **Step 1: Run lint**

Run: `just lint`
Expected: All four steps (`eof-fixer`, `ruff format`, `ruff check --fix`, `ty check`) green. Note: `eof-fixer` may auto-add newlines to `.gitkeep` or CLAUDE.md — re-stage afterward.

## Task 12: Stage and commit

**Files:** All modified/created files this PR.

- [ ] **Step 1: Stage changes**

Run:
```
git add pyproject.toml \
        CLAUDE.md \
        planning/
```

- [ ] **Step 2: Confirm staged files**

Run: `git status --short`
Expected output (order may vary):
```
M  CLAUDE.md
M  pyproject.toml
A  planning/plans/.gitkeep
A  planning/plans/2026-06-03-faststream-0.7-migration-pr1-plan.md
A  planning/plans/2026-06-03-faststream-0.7-migration-pr2-plan.md
A  planning/specs/.gitkeep
A  planning/specs/2026-06-03-faststream-0.7-migration-design.md
```

If `uv.lock` shows up in `git status` despite being gitignored, do **not** stage it — confirm `.gitignore` still lists `uv.lock`.

- [ ] **Step 3: Verify no per-call kwarg accidentally landed**

Run: `git diff --cached pyproject.toml`
Expected: only the two single-line edits (pin + addopts).

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore: pin faststream <0.7 and adopt planning/ workflow

- pyproject.toml: faststream~=0.6 -> >=0.6,<0.7. Explicit upper bound
  makes intent visible and lets the 0.7 migration land in a feature
  branch without users pulling unfinished work.
- pyproject.toml: addopts adds --cov-fail-under=100 (matches sister
  faststream-outbox project). Hardens the coverage gate before the
  0.7 migration (PR2) removes branches.
- planning/: scaffold planning/specs/ + planning/plans/ with .gitkeep
  files; mirrors the sister faststream-outbox layout. Includes the
  faststream-0.7 migration design and the two plan files so PR2 has
  a home.
- CLAUDE.md: new ## Workflow section pointing at the planning/ layout.

Companion PR migrates to faststream 0.7 and drops 0.6 support
(>=0.7,<0.8).
EOF
)"
```

(If Task 4 was skipped, drop the `--cov-fail-under=100` bullet from the body.)

- [ ] **Step 5: Verify commit**

Run: `git log -1 --stat`
Expected: single commit with the message above and the staged files.

## Task 13: Push and open PR

**Files:** None (git remote operation).

- [ ] **Step 1: Push branch**

Run: `git push -u origin chore/pin-faststream-pre-0.7`
Expected: `* [new branch]` line and a hint URL for opening the PR.

- [ ] **Step 2: Open PR via gh**

```bash
gh pr create --title "chore: pin faststream <0.7 and adopt planning/ workflow" --body "$(cat <<'EOF'
## Summary

- Tightens the FastStream pin from `~=0.6` to `>=0.6,<0.7`. The companion PR migrates to 0.7 and drops 0.6 support.
- Adopts `--cov-fail-under=100` (matches sister `faststream-outbox` project).
- Scaffolds `planning/specs/` and `planning/plans/` and lands the 0.7 migration design + two-PR plan files.

## Test plan

- [ ] `just lint` passes
- [ ] `just test` passes at 100% coverage
- [ ] `planning/specs/` and `planning/plans/` are tracked by git
- [ ] `CLAUDE.md` shows the new `## Workflow` section between `## Commands` and `## Tests`
EOF
)"
```

(If Task 4 was skipped: drop the second bullet of the Summary block.)

- [ ] **Step 3: Note PR URL**

The `gh pr create` command outputs the PR URL. Record it for the user.

---

## Verification (acceptance gate)

The PR is done iff:

- [ ] `git diff main..chore/pin-faststream-pre-0.7 -- pyproject.toml` shows only the pin edit and (if applicable) the `--cov-fail-under=100` addition.
- [ ] `git grep -n "faststream~=0.6"` returns nothing on the branch.
- [ ] `planning/specs/2026-06-03-faststream-0.7-migration-design.md` exists and is tracked.
- [ ] `planning/plans/2026-06-03-faststream-0.7-migration-pr1-plan.md` (this file) exists and is tracked.
- [ ] `planning/plans/2026-06-03-faststream-0.7-migration-pr2-plan.md` exists and is tracked.
- [ ] `planning/specs/.gitkeep` and `planning/plans/.gitkeep` exist and are tracked.
- [ ] `CLAUDE.md` contains the `## Workflow` section between `## Commands` and `## Tests`.
- [ ] `just lint` clean on the branch tip.
- [ ] `just test` green (at 100% if Task 4 ran).
- [ ] PR is open with the prescribed title and body.


---

# FastStream 0.7 migration — PR2 (migrate to 0.7, drop 0.6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bump `faststream>=0.6,<0.7` → `faststream>=0.7,<0.8`. Drop 0.6 support entirely (no compat shim). Fix the mechanical 0.7 break points and drop the public per-call `middlewares=` kwarg upstream removed. Single bundled commit on `chore/faststream-0.7-migration`.

**Architecture:** Surgical edits across `publisher/`, `registrator.py`, `router.py`, `testing.py`. No new features adopted (broker-level `AckPolicy` default, multi-broker, Redis Cluster, MQTT — all deferred). The producer's `codec` attribute is a structural-typing satisfier (`DefaultCodec()` shared instance); runtime ignores it because `TimerMessageFormat.encode` owns the encoding pipeline.

**Tech Stack:** FastStream 0.7, ty, ruff, pytest-cov (gate at 100% from PR1, unless PR1 deferred it).

**Related spec:** `planning/specs/2026-06-03-faststream-0.7-migration-design.md`.

**Pre-resolved unknowns from spec (verified against upstream `main` during plan writing):**
- `CodecProto` lives at `faststream._internal.parser.CodecProto`. Non-Optional on `ProducerProto`.
- `DefaultCodec` concrete impl lives at `faststream._internal.parser.DefaultCodec`. Stateless — safe to share as a class-level default.
- `AckPolicy.NACK_ON_ERROR` still exists; importable via `from faststream.middlewares import AckPolicy` (unchanged).
- `PublisherUsecase._publish(... _extra_middlewares=)` is preserved in 0.7. No change to `publisher/usecase.py` lines 79/87/94 or `tests/test_delivery.py:106`.
- `PublisherUsecaseConfig` in 0.7 has no `middlewares` field at all — passing `middlewares=` to `TimersPublisherConfig(...)` will TypeError.
- `add_call` in 0.7 takes only `parser_`, `decoder_`, `dependencies_`, `codec_` (optional). No `middlewares_`.

---

## Task 1: Create the working branch (PR1 must be merged to main first)

**Files:** None (git operation).

- [ ] **Step 1: Confirm PR1 has merged**

Run: `git switch main && git pull`
Expected: HEAD includes the `chore: pin faststream <0.7 and adopt planning/ workflow` commit.

- [ ] **Step 2: Create branch**

Run: `git switch -c chore/faststream-0.7-migration`
Expected: `Switched to a new branch 'chore/faststream-0.7-migration'`

## Task 2: Bump the pin and resolve

**Files:**
- Modify: `pyproject.toml` (line 12 — verify with grep, post-PR1 the line numbers shouldn't shift)
- Touched (gitignored): `uv.lock`

- [ ] **Step 1: Read current pin**

Run: `grep -n "faststream" pyproject.toml | grep -v module`
Expected: `12:    "faststream>=0.6,<0.7",` (if PR1 merged cleanly).

- [ ] **Step 2: Bump pin**

Change the `"faststream>=0.6,<0.7"` line to `"faststream>=0.7,<0.8"`.

- [ ] **Step 3: Verify edit**

Run: `grep -n "faststream" pyproject.toml | grep -v module`
Expected: `12:    "faststream>=0.7,<0.8",`

- [ ] **Step 4: Re-lock and sync**

Run: `uv lock --upgrade && uv sync --all-extras --all-groups --frozen`
Expected: `Resolved N packages` with `faststream` at a `0.7.x` version. Confirm via:
Run: `grep -A 2 '^name = "faststream"$' uv.lock | head -3`
Expected: `version = "0.7.X"` where `X` >= 0.

## Task 3: First diagnostic run

**Files:** None (read-only diagnostics).

The remaining tasks are driven by what ty + the test suite report once the new wheel is installed. This task captures the failure surface so subsequent tasks can target it precisely.

- [ ] **Step 1: Run ty to see all type errors**

Run: `uv run ty check 2>&1 | tee /tmp/ty-baseline.txt | head -80`
Expected: One or more errors. The known issues we expect (write them down — they drive Tasks 4–8):
- `TimersProducer` missing `codec` attribute (or `FakeTimersProducer` likewise).
- `TimersRegistrator.subscriber` calling `add_call(..., middlewares_=...)` — `middlewares_` not in signature.
- `TestTimersBroker.create_publisher_fake_subscriber` being a `@staticmethod` vs the abstract instance-method base.
- Possibly: moved `faststream._internal.*` imports (less likely; will surface if so).

- [ ] **Step 2: Run unit + fake tests (no Redis required) to see runtime breaks**

Run: `uv run pytest tests/test_unit.py tests/test_fake.py 2>&1 | tee /tmp/pytest-baseline.txt | tail -60`
Expected: Failures likely include `TypeError: TimersPublisherConfig.__init__() got an unexpected keyword argument 'middlewares'` (from `publisher/factory.py:27`) once the test hits a publisher construction path.

- [ ] **Step 3: Note any surprises**

If ty surfaces an `_internal.*` import that moved, record the new path. Each is a single-line fix in Task 9.

## Task 4: Add `codec` attribute to `TimersProducer` (+ inheritor gets it free)

**Files:**
- Modify: `faststream_redis_timers/publisher/producer.py`

`FakeTimersProducer` inherits from `TimersProducer` but does not call `super().__init__()`, so a class-level default is the simplest way to give both classes the attribute.

- [ ] **Step 1: Write the failing test (extends `tests/test_unit.py`)**

Add to `tests/test_unit.py` (top-level test function):

```python
def test_timers_producer_satisfies_producer_proto_codec() -> None:
    """0.7's ProducerProto requires a `codec: CodecProto` attribute."""
    from faststream._internal.parser import CodecProto, DefaultCodec
    from faststream_redis_timers.publisher.producer import TimersProducer

    # Class-level default — both TimersProducer and FakeTimersProducer inherit it.
    assert isinstance(TimersProducer.codec, DefaultCodec)
    # And the structural check via the protocol annotation passes:
    assert hasattr(TimersProducer, "codec")
    # CodecProto is a Protocol; the runtime check is the annotation existing,
    # but a positive isinstance against DefaultCodec is the load-bearing assertion.
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `uv run pytest tests/test_unit.py::test_timers_producer_satisfies_producer_proto_codec -v`
Expected: FAIL with `AttributeError: type object 'TimersProducer' has no attribute 'codec'`.

- [ ] **Step 3: Edit `producer.py` to satisfy the protocol**

Current `producer.py` top (lines 1-16):

```python
import typing

from faststream_redis_timers.envelope import TimerMessageFormat
from faststream_redis_timers.response import TimerPublishCommand


if typing.TYPE_CHECKING:
    from fast_depends.library.serializer import SerializerProto
    from faststream._internal.types import AsyncCallable

    from faststream_redis_timers.configs import ConnectionState


class TimersProducer:
    _parser: "AsyncCallable"
    _decoder: "AsyncCallable"
```

Change to (note the new runtime import and the class-level codec assignment):

```python
import typing

from faststream._internal.parser import DefaultCodec
from faststream_redis_timers.envelope import TimerMessageFormat
from faststream_redis_timers.response import TimerPublishCommand


if typing.TYPE_CHECKING:
    from fast_depends.library.serializer import SerializerProto
    from faststream._internal.parser import CodecProto
    from faststream._internal.types import AsyncCallable

    from faststream_redis_timers.configs import ConnectionState


class TimersProducer:
    _parser: "AsyncCallable"
    _decoder: "AsyncCallable"
    codec: "CodecProto" = DefaultCodec()
```

Rationale: `CodecProto` is non-Optional on `ProducerProto`, so the attribute must exist. `DefaultCodec()` is stateless (verified in upstream `parser.py`), making the shared class-level default safe. `FakeTimersProducer` inherits the attribute without changes.

- [ ] **Step 4: Run the test, confirm it passes**

Run: `uv run pytest tests/test_unit.py::test_timers_producer_satisfies_producer_proto_codec -v`
Expected: PASS.

- [ ] **Step 5: Confirm `FakeTimersProducer` inherits**

Run inline:
```
uv run python -c "from faststream_redis_timers.testing import FakeTimersProducer; from faststream._internal.parser import DefaultCodec; assert isinstance(FakeTimersProducer.codec, DefaultCodec); print('ok')"
```
Expected: `ok`.

## Task 5: Fix `create_publisher_fake_subscriber` (drop @staticmethod)

**Files:**
- Modify: `faststream_redis_timers/testing.py` (lines 41–56)

- [ ] **Step 1: Write the failing assertion (extends `tests/test_unit.py`)**

Add to `tests/test_unit.py`:

```python
def test_create_publisher_fake_subscriber_is_instance_method() -> None:
    """0.7's TestBroker base declares the method as an instance method."""
    import inspect
    from faststream_redis_timers.testing import TestTimersBroker

    sig = inspect.signature(TestTimersBroker.create_publisher_fake_subscriber)
    # First parameter must be `self` post-migration.
    assert list(sig.parameters)[0] == "self"
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `uv run pytest tests/test_unit.py::test_create_publisher_fake_subscriber_is_instance_method -v`
Expected: FAIL with assertion mismatch (first param will be `broker`, not `self`).

- [ ] **Step 3: Edit `testing.py`**

Current `testing.py:41-46`:

```python
    @staticmethod
    def create_publisher_fake_subscriber(
        broker: TimersBroker,
        publisher: TimersPublisher,
    ) -> tuple[TimersSubscriber, bool]:
```

Change to:

```python
    def create_publisher_fake_subscriber(
        self,
        broker: TimersBroker,
        publisher: TimersPublisher,
    ) -> tuple[TimersSubscriber, bool]:
```

(Drop the `@staticmethod` decorator; add `self` as the first parameter. The body is unchanged.)

- [ ] **Step 4: Run the test, confirm it passes**

Run: `uv run pytest tests/test_unit.py::test_create_publisher_fake_subscriber_is_instance_method -v`
Expected: PASS.

## Task 6: Drop `middlewares_=` from `add_call` and `middlewares=` from `TimersRegistrator.subscriber`

**Files:**
- Modify: `faststream_redis_timers/registrator.py` (lines 7, 29, 61)

- [ ] **Step 1: Find tests that pass per-call `middlewares=` to `subscriber()`**

Run: `git grep -n 'subscriber(.*middlewares=' tests/ faststream_redis_timers/`
Expected: Zero or more hits. Each is a test or call site that must change.

- [ ] **Step 2: For each test hit:**
  - If the test was only covering per-call middleware behavior: delete it. Note: the `--cov-fail-under=100` gate (if PR1 adopted it) will catch any line in `registrator.py` that becomes uncovered as a result.
  - If the test was using middleware to assert something else (interceptor invocation, ordering): rewrite using broker-scope `BaseMiddleware` (`TimersBroker(middlewares=[...])`).

- [ ] **Step 3: Edit `registrator.py`**

Drop `SubscriberMiddleware` from the import on line 7 if no longer used:

Current:
```python
from faststream._internal.types import CustomCallable, PublisherMiddleware, SubscriberMiddleware
```

Change to (drop `SubscriberMiddleware`; keep `PublisherMiddleware` for now — Task 7 handles it):
```python
from faststream._internal.types import CustomCallable, PublisherMiddleware
```

Also drop the now-unused `Sequence` import if no other usage remains — check after the rest of the edits.

In `subscriber()` (lines 18–62):
- Drop line 29: `middlewares: Sequence[SubscriberMiddleware[TimerMessage]] = (),`
- Drop line 61: `middlewares_=middlewares,` from the `add_call(...)` block (the rest of the call stays).

After the edit, lines 57–62 should read:
```python
        return subscriber.add_call(
            parser_=parser or self._parser,
            decoder_=decoder or self._decoder,
            dependencies_=dependencies,
        )
```

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/test_unit.py -v`
Expected: All pass (no regression). Any test that was passing `middlewares=` to `subscriber()` should have been deleted/rewritten in Step 2.

## Task 7: Drop `middlewares=` from `TimersRegistrator.publisher` + plumbing

**Files:**
- Modify: `faststream_redis_timers/registrator.py` (lines 7, 69, 78)
- Modify: `faststream_redis_timers/publisher/factory.py` (lines 2, 9, 18, 27)

- [ ] **Step 1: Find tests that pass per-call `middlewares=` to `publisher()`**

Run: `git grep -n 'publisher(.*middlewares=' tests/ faststream_redis_timers/`
Expected: Zero or more hits. Same triage as Task 6.

- [ ] **Step 2: For each test hit: delete (per-call-only) or rewrite (broker-scope).**

- [ ] **Step 3: Edit `registrator.py` — `publisher()` method**

Drop `PublisherMiddleware` from the import on line 7 (now safe; `subscriber()` no longer needs it either):

Current after Task 6:
```python
from faststream._internal.types import CustomCallable, PublisherMiddleware
```

Change to:
```python
from faststream._internal.types import CustomCallable
```

Drop the `Sequence` import on line 2 if now unused. Check by running `uv run ty check` after the edit; reinstate if needed.

In `publisher()` (lines 64–85):
- Drop line 69: `middlewares: Sequence[PublisherMiddleware] = (),`
- Drop line 78: `middlewares=middlewares,` (the line that passes through to `create_publisher`).

After the edit, lines 64–85 should read:
```python
    @override
    def publisher(  # ty: ignore[invalid-method-override]
        self,
        topic: str,
        *,
        schema_: Any | None = None,
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> TimersPublisher:
        publisher = create_publisher(
            topic=topic,
            config=self.config,  # ty: ignore[invalid-argument-type]
            title_=title_,
            description_=description_,
            schema_=schema_,
            include_in_schema=include_in_schema,
        )
        super().publisher(publisher)
        return publisher
```

- [ ] **Step 4: Edit `publisher/factory.py`**

Current:
```python
import typing
from collections.abc import Sequence

from faststream_redis_timers.publisher.config import TimersPublisherConfig, TimersPublisherSpecificationConfig
from faststream_redis_timers.publisher.usecase import TimersPublisher, TimersPublisherSpecification


if typing.TYPE_CHECKING:
    from faststream._internal.types import PublisherMiddleware

    from faststream_redis_timers.configs import TimersBrokerConfig


def create_publisher(  # noqa: PLR0913
    *,
    topic: str,
    config: "TimersBrokerConfig",
    middlewares: Sequence["PublisherMiddleware"] = (),
    title_: str | None = None,
    description_: str | None = None,
    schema_: typing.Any | None = None,
    include_in_schema: bool = True,
) -> TimersPublisher:
    usecase_config = TimersPublisherConfig(
        _outer_config=config,
        topic=topic,
        middlewares=middlewares,
    )
```

Change to (drop the `Sequence` import, the `PublisherMiddleware` import, the `middlewares=` param, and the `middlewares=middlewares` line in the `TimersPublisherConfig(...)` call):

```python
import typing

from faststream_redis_timers.publisher.config import TimersPublisherConfig, TimersPublisherSpecificationConfig
from faststream_redis_timers.publisher.usecase import TimersPublisher, TimersPublisherSpecification


if typing.TYPE_CHECKING:
    from faststream_redis_timers.configs import TimersBrokerConfig


def create_publisher(  # noqa: PLR0913
    *,
    topic: str,
    config: "TimersBrokerConfig",
    title_: str | None = None,
    description_: str | None = None,
    schema_: typing.Any | None = None,
    include_in_schema: bool = True,
) -> TimersPublisher:
    usecase_config = TimersPublisherConfig(
        _outer_config=config,
        topic=topic,
    )
```

Also reassess `# noqa: PLR0913` — the parameter count is now 7 (below the ruff default of 5? — actually `PLR0913` defaults to flag when >5; with 7 the noqa may still apply, or you may be able to drop it). After the edit, run ruff to find out:

Run: `uv run ruff check faststream_redis_timers/publisher/factory.py`
- If ruff is silent: keep the noqa (matches existing repo style for this kind of suppression).
- If ruff complains "Unused noqa": remove the comment.

- [ ] **Step 5: Run unit + fake tests**

Run: `uv run pytest tests/test_unit.py tests/test_fake.py -v`
Expected: All pass (no regression).

## Task 8: Drop `middlewares=` from router classes

**Files:**
- Modify: `faststream_redis_timers/router.py` (lines 8, 21, 29, 53, 69)

- [ ] **Step 1: Find tests that pass `middlewares=` to `TimersRoute` or `TimersRoutePublisher`**

Run: `git grep -n 'TimersRoute\|TimersRoutePublisher\|TimersRouter' tests/`
Expected: Some test hits. Examine each: if they pass `middlewares=` to the route classes, delete or rewrite (same triage).

- [ ] **Step 2: Edit `router.py` — `TimersRoutePublisher.__init__`**

Current (lines 17–34):
```python
    def __init__(  # noqa: PLR0913
        self,
        topic: str,
        *,
        middlewares: Sequence[PublisherMiddleware] = (),
        schema_: Any | None = None,
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        super().__init__(
            topic=topic,
            middlewares=middlewares,
            schema_=schema_,
            title_=title_,
            description_=description_,
            include_in_schema=include_in_schema,
        )
```

Change to:
```python
    def __init__(  # noqa: PLR0913
        self,
        topic: str,
        *,
        schema_: Any | None = None,
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        super().__init__(
            topic=topic,
            schema_=schema_,
            title_=title_,
            description_=description_,
            include_in_schema=include_in_schema,
        )
```

(Then reassess `# noqa: PLR0913` per the same rule as Task 7 step 4.)

- [ ] **Step 3: Edit `router.py` — `TimersRoute.__init__`**

Current (lines 40–73):
```python
    def __init__(  # noqa: PLR0913
        self,
        call: Callable[..., SendableMessage] | Callable[..., Awaitable[SendableMessage]],
        topic: str,
        *,
        polling_interval: float = 0.05,
        max_polling_interval: float = 5.0,
        max_concurrent: int = 5,
        lease_ttl: int = 30,
        publishers: Iterable[TimersRoutePublisher] = (),
        dependencies: Iterable[Dependant] = (),
        parser: CustomCallable | None = None,
        decoder: CustomCallable | None = None,
        middlewares: Sequence[SubscriberMiddleware[TimerMessage]] = (),
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        super().__init__(
            call=call,
            topic=topic,
            polling_interval=polling_interval,
            max_polling_interval=max_polling_interval,
            max_concurrent=max_concurrent,
            lease_ttl=lease_ttl,
            publishers=publishers,
            dependencies=dependencies,
            parser=parser,
            decoder=decoder,
            middlewares=middlewares,
            title_=title_,
            description_=description_,
            include_in_schema=include_in_schema,
        )
```

Drop the two `middlewares=` lines (signature param and `super().__init__()` pass-through):

```python
    def __init__(  # noqa: PLR0913
        self,
        call: Callable[..., SendableMessage] | Callable[..., Awaitable[SendableMessage]],
        topic: str,
        *,
        polling_interval: float = 0.05,
        max_polling_interval: float = 5.0,
        max_concurrent: int = 5,
        lease_ttl: int = 30,
        publishers: Iterable[TimersRoutePublisher] = (),
        dependencies: Iterable[Dependant] = (),
        parser: CustomCallable | None = None,
        decoder: CustomCallable | None = None,
        title_: str | None = None,
        description_: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        super().__init__(
            call=call,
            topic=topic,
            polling_interval=polling_interval,
            max_polling_interval=max_polling_interval,
            max_concurrent=max_concurrent,
            lease_ttl=lease_ttl,
            publishers=publishers,
            dependencies=dependencies,
            parser=parser,
            decoder=decoder,
            title_=title_,
            description_=description_,
            include_in_schema=include_in_schema,
        )
```

- [ ] **Step 4: Trim unused imports on line 8**

Current:
```python
from faststream._internal.types import BrokerMiddleware, CustomCallable, PublisherMiddleware, SubscriberMiddleware
```

After Steps 2–3, `PublisherMiddleware` and `SubscriberMiddleware` are unused. `BrokerMiddleware` is still used by `TimersRouter.__init__`. Change to:

```python
from faststream._internal.types import BrokerMiddleware, CustomCallable
```

Drop `Sequence` from line 1 if no longer used (it's still used by `BrokerMiddleware` typing in `TimersRouter.__init__` — keep it).

- [ ] **Step 5: Confirm `TimersRouter.__init__` still uses `middlewares` for broker-scope**

Current (lines 79–102) — DO NOT change. `middlewares: Sequence[BrokerMiddleware[TimerMessage]]` at line 85 is broker-scope (passed as `broker_middlewares=middlewares` at line 93). This is the broker-level middleware surface, which is preserved in 0.7.

- [ ] **Step 6: Run unit + fake tests**

Run: `uv run pytest tests/test_unit.py tests/test_fake.py -v`
Expected: All pass.

## Task 9: Run ty + ruff to catch any `_internal.*` import moves

**Files:** Discovered at runtime.

- [ ] **Step 1: Run ty**

Run: `uv run ty check 2>&1 | head -40`
Expected: Either clean OR a small set of "module has no attribute X" errors for moved `_internal.*` symbols.

- [ ] **Step 2: For each "module has no attribute" error**:

  - Locate the symbol's new home in the installed wheel: `find .venv/lib/python3.13/site-packages/faststream -name "*.py" | xargs grep -l "class <Symbol>\|^<Symbol> = \|def <Symbol>"`.
  - Edit the failing import in `faststream_redis_timers/` to the new path.
  - Re-run ty. Iterate until clean.

- [ ] **Step 3: Run ruff**

Run: `uv run ruff check --fix faststream_redis_timers/ tests/`
Expected: Either clean OR auto-fixable issues (e.g. unused imports from the middleware kwargs being dropped). Let ruff fix what it can; review any remaining warnings.

- [ ] **Step 4: Re-run ty after ruff to confirm consistency**

Run: `uv run ty check 2>&1 | tail -10`
Expected: clean.

## Task 10: Verify `AckPolicy.NACK_ON_ERROR` still works as imported

**Files:** None (read-only check).

The spec flagged this as R3. Upstream confirms it survived; this is a fast sanity check.

- [ ] **Step 1: Sanity check the import path**

Run: `uv run python -c "from faststream.middlewares import AckPolicy; print(AckPolicy.NACK_ON_ERROR.value)"`
Expected: `nack_on_error`.

If this raises `ImportError` or `AttributeError`, the location moved — find the new path via `grep -rn "NACK_ON_ERROR" .venv/lib/python3.13/site-packages/faststream/` and update `faststream_redis_timers/subscriber/config.py:6`.

## Task 11: Run the full test suite

**Files:** None.

- [ ] **Step 1: Run full suite via Justfile (Docker; brings up Redis)**

Run: `just test`
Expected: All five test files pass. If `--cov-fail-under=100` is in effect (PR1 adopted it), the report ends with `Required test coverage of 100% reached.`

- [ ] **Step 2: If coverage <100%**:

  - Identify uncovered lines from the `term-missing` report.
  - For each: write a focused test, OR delete dead code that was only reachable via the removed `middlewares=` paths.
  - Re-run: `just test`. Iterate until 100%.

## Task 12: Verify no per-call `middlewares=` survives

**Files:** None.

- [ ] **Step 1: Grep for residual per-call kwargs**

Run: `git grep -n "middlewares_=\|middlewares=" faststream_redis_timers/ tests/`
Expected: Hits only on `broker_middlewares=` and broker-level configs. The phrase `middlewares=` is allowed only as part of `broker_middlewares=` or in a comment.

If any other hit remains: revisit the affected file; the migration is incomplete.

## Task 13: Verify package-public imports still work

**Files:** None.

- [ ] **Step 1: Smoke test the public surface**

Run:
```
uv run python -c "from faststream_redis_timers import TimersBroker, TimersRouter, TestTimersBroker, TimerMessage; print('ok')"
```
Expected: `ok`.

## Task 14: Spot-check docs for stale `middlewares=` examples

**Files:**
- Possibly modify: `README.md`, `docs/usage/*.md`

The brainstorming-time grep returned zero hits, but a quick re-check defends against intervening commits.

- [ ] **Step 1: Grep docs**

Run: `git grep -n 'middlewares=' README.md docs/`
Expected: No hits (zero output).

- [ ] **Step 2: If any hit, rewrite or drop the example**

If a hit appears: the snippet shows per-call `middlewares=` use. Rewrite to broker-scope (`TimersBroker(middlewares=[...])`) or drop the example.

## Task 15: Final lint pass

**Files:** Possibly minor cleanup.

- [ ] **Step 1: Run lint**

Run: `just lint`
Expected: All four steps green. `eof-fixer` may touch files; restage if needed.

## Task 16: Stage and commit

**Files:** All modified.

- [ ] **Step 1: Review diff**

Run: `git status --short && echo '---' && git diff --stat`
Expected: A focused set of edits across `pyproject.toml`, `faststream_redis_timers/publisher/producer.py`, `faststream_redis_timers/publisher/factory.py`, `faststream_redis_timers/testing.py`, `faststream_redis_timers/registrator.py`, `faststream_redis_timers/router.py`, possibly other `faststream_redis_timers/*` files for `_internal.*` moves, and some test files. `uv.lock` (if present) is gitignored — don't stage it.

- [ ] **Step 2: Stage non-lock files**

Run:
```
git add pyproject.toml faststream_redis_timers/ tests/
```

If docs changed in Task 14, also: `git add README.md docs/`.

- [ ] **Step 3: Confirm `uv.lock` is unstaged**

Run: `git status uv.lock`
Expected: Either "ignored" or no mention. If it shows up as modified-and-staged, remove with `git restore --staged uv.lock` and verify `.gitignore` still lists `uv.lock`.

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore: migrate to faststream 0.7 (breaking: drop per-call middlewares=)

Bump dependency from `faststream>=0.6,<0.7` to `>=0.7,<0.8`. Drops support
for the 0.6 series entirely (single code path, no compat shim).

Mechanical 0.7 fix points:
- publisher/producer.py: TimersProducer gains `codec: CodecProto =
  DefaultCodec()` class-level default to satisfy 0.7's ProducerProto.
  FakeTimersProducer inherits the attribute.
- testing.py: create_publisher_fake_subscriber drops @staticmethod and
  gains `self` — 0.7's TestBroker base declares it as an instance method.
- registrator.py: TimersRegistrator.subscriber drops `middlewares=` kwarg;
  add_call(...) drops `middlewares_=` (0.7 removed it from the base).

Public API break — `middlewares=` per-call kwarg removed from:
- TimersRegistrator.subscriber / .publisher
- TimersRoute / TimersRoutePublisher
- internal plumbing in publisher/factory.py + publisher/config.py
Upstream removed per-subscriber/per-publisher middleware in 0.7. We
follow suit rather than (a) silently routing to broker scope (semantic
break, surprising), or (b) reimplementing locally (maintenance cost for
a v0 package). Broker-scope middleware via `TimersBroker(middlewares=[...])`
remains the supported entry point.

No 0.7 features adopted (broker-level AckPolicy default, multi-broker,
Redis Cluster, MQTT). Each gets its own follow-up if/when we want it.
EOF
)"
```

- [ ] **Step 5: Verify commit**

Run: `git log -1 --stat`
Expected: single commit with the message above and the modified files.

## Task 17: Push and open PR

**Files:** None.

- [ ] **Step 1: Push branch**

Run: `git push -u origin chore/faststream-0.7-migration`

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "chore: migrate to faststream 0.7 (breaking: drop per-call middlewares=)" --body "$(cat <<'EOF'
## Summary

- Bumps `faststream>=0.6,<0.7` → `>=0.7,<0.8`. Drops 0.6 support entirely.
- Fixes the mechanical 0.7 break points (`codec` attribute on `TimersProducer`, `create_publisher_fake_subscriber` instance form, `add_call` kwarg).
- **Breaking change for downstream consumers:** the per-call `middlewares=` kwarg is removed from `TimersRegistrator.subscriber`, `TimersRegistrator.publisher`, `TimersRoute`, and `TimersRoutePublisher`. Use broker-scope `TimersBroker(middlewares=[...])` instead.

No new 0.7 features are adopted in this PR (broker-level `AckPolicy` default, multi-broker, Redis Cluster, MQTT each get their own follow-up if we want them).

## Test plan

- [ ] `just lint` clean (ruff + ty + eof-fixer).
- [ ] `just test` green at 100% coverage (Redis-backed integration suite included).
- [ ] `uv run pytest tests/test_unit.py tests/test_fake.py` green standalone.
- [ ] `git grep -n "middlewares_=\|middlewares=" faststream_redis_timers/ tests/` returns only `broker_middlewares=` entries.
- [ ] `git grep -n "faststream~=0.6\|faststream<0.7\|faststream>=0.6,<0.7" .` returns nothing.
- [ ] `python -c "from faststream_redis_timers import TimersBroker, TimersRouter, TestTimersBroker"` exits 0.
EOF
)"
```

- [ ] **Step 3: Note PR URL**

Output of the previous command. Record for the user.

---

## Verification (acceptance gate)

The PR is done iff:

- [ ] `git diff main..chore/faststream-0.7-migration -- pyproject.toml` shows the pin bump to `>=0.7,<0.8`.
- [ ] `git grep -n "middlewares_=\|middlewares=" faststream_redis_timers/ tests/` returns only `broker_middlewares=` entries.
- [ ] `git grep -n "faststream~=0.6\|faststream<0.7\|faststream>=0.6,<0.7" .` returns nothing.
- [ ] `just lint` clean.
- [ ] `just test` green; coverage at 100% if PR1 adopted the gate.
- [ ] `uv run python -c "from faststream_redis_timers import TimersBroker, TimersRouter, TestTimersBroker, TimerMessage"` exits 0.
- [ ] PR is open with the prescribed title and body.
