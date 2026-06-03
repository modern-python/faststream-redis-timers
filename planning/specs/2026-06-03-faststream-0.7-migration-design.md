# Design: FastStream 0.7 migration (two-PR split)

**Date:** 2026-06-03
**Status:** Approved
**Slug:** `faststream-0.7-migration`

## Summary

Migrate `faststream-redis-timers` from `faststream~=0.6` to `faststream>=0.7,<0.8`
in **two PRs against `main`**:

1. **PR1 — `chore/pin-faststream-pre-0.7`**: Defensive pin. Tighten the
   dependency to `faststream>=0.6,<0.7`, regenerate `uv.lock`, adopt
   `--cov-fail-under=100`, and scaffold the `planning/` workflow directory
   (mirroring the sister `faststream-outbox` project). This design doc ships
   in the same commit so PR2 has a home immediately.
2. **PR2 — `chore/faststream-0.7-migration`** (off `main` after PR1 merges):
   Bump to `faststream>=0.7,<0.8`. Drop 0.6 support entirely (no compat shim).
   Fix the mechanical 0.7 break points (`codec`, `add_call` kwarg,
   `create_publisher_fake_subscriber` instance form, any moved
   `_internal.*` imports). Drop the public per-call `middlewares=` kwarg
   that upstream removed. Single bundled commit.

No new 0.7 features (broker-level `AckPolicy` default, multi-broker, MQTT,
Redis Cluster broker) are adopted in this change.

## Motivation

FastStream 0.7.0 is released. The current `~=0.6` specifier already excludes
0.7 by resolver behavior, but the explicit `<0.7` upper bound makes intent
visible to readers and lets the migration land freely in a feature branch
without users accidentally pulling unfinished work via a `--upgrade` resolve.

PR2 then aligns the package with the same upstream surface the sister
`faststream-outbox` migration targeted. The API breaks land in one diff so
reviewers see the full cost in one place. The package is at version `"0"`
(sentinel / pre-release) with no stability promise, so a hard break on the
per-call `middlewares=` kwarg is in policy provided it is documented in the
commit/PR.

The PR1/PR2 split (vs. the single-PR shape the outbox used) is the user's
chosen sequencing: ship the safety pin in minutes, then take the migration
through review on its own merits.

## Scope decisions

- **Drop 0.6 support entirely.** Single code path, no `_compat.py` shim.
  Users still on 0.6 stay on the currently-released wheel.
- **Pure compat migration.** No adoption of new 0.7 features. The mechanical
  fix sites + the public-`middlewares=`-kwarg removal are the entire scope of
  PR2.
- **Drop the public `middlewares=` kwarg** on `TimersRegistrator.subscriber`,
  `TimersRegistrator.publisher`, `TimersRoute`, and `TimersRoutePublisher`.
  The two alternatives both lose:
  - *Keep the kwarg, route to broker scope internally* — semantically wrong;
    broker-scope middleware runs on every queue, not the one the kwarg was
    attached to. Silent change of meaning is worse than a hard break.
  - *Re-implement per-subscriber middleware locally* — reproduces behavior
    upstream just removed; ongoing maintenance cost for a v0 package.
- **PR2 ships as a single bundled commit.** Splitting would create an
  incoherent intermediate state — `add_call` doesn't accept `middlewares_=`
  anymore, so the public `middlewares=` kwarg becomes a silent no-op if
  removed in a separate commit.
- **Adopt `--cov-fail-under=100` in PR1.** Matches the outbox baseline and
  hardens the gate before PR2 disturbs anything; PR2's R1 (coverage drops
  from removed branches) then red-fails CI rather than degrading silently.

## Design

### PR1 — `chore/pin-faststream-pre-0.7`

#### `pyproject.toml`
- `dependencies`: `"faststream~=0.6"` → `"faststream>=0.6,<0.7"`.
- `[tool.pytest.ini_options].addopts`: append `--cov-fail-under=100`.
- **Precondition:** current suite must already hit 100% line coverage. If
  not, either fill the gaps in PR1 (preferred — keeps PR1 cohesive as
  "lock + scaffold + raise quality bar") or revert the gate change and
  defer the gate to PR2. The PR1 implementation step starts by running
  `just test` and inspecting the report.

#### `uv.lock`
- `uv.lock` is gitignored in this repo. Regenerate locally via `uv lock`
  (no `--upgrade` — just refresh the constraints) to confirm the resolver
  is happy with the tightened pin, but the file does not ship in the commit.

#### `planning/specs/`, `planning/plans/`
- New directories with `.gitkeep` files (zero-byte). The `.gitkeep` in
  `planning/specs/` is defensive but technically redundant — this design
  doc populates the dir on first commit.

#### `planning/specs/2026-06-03-faststream-0.7-migration-design.md`
- This design doc, committed alongside the pin so PR2 has a home.

#### `CLAUDE.md`
- Insert `## Workflow` section between `## Commands` and `## Tests`:

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

#### `.gitignore`
- No change. The existing `plan.md` entry targets a literal basename;
  gitignore patterns without slashes match basenames exactly at any depth,
  so `plan.md` matches only a file literally named `plan.md` — never
  `planning/plans/2026-06-03-<slug>-plan.md`.

### PR2 — `chore/faststream-0.7-migration`

#### `pyproject.toml`
- `dependencies`: `"faststream>=0.6,<0.7"` → `"faststream>=0.7,<0.8"`.

#### `uv.lock`
- `uv.lock` is gitignored. Regenerate locally via `uv lock --upgrade` to
  resolve to a 0.7.x release; the file does not ship in the commit.

#### `faststream_redis_timers/publisher/producer.py` — `TimersProducer`
- Add `codec: CodecProto` attribute, initialized in `__init__`. Imported
  from the upstream module that exposes it in 0.7 (exact path verified
  during implementation — see Unknowns below).
- Value: use upstream's default codec instance (likely a JSON codec, to
  confirm). The producer owns its encoding pipeline via
  `TimerMessageFormat.encode` and ignores `self.codec` at runtime; the
  attribute exists solely to satisfy structural typing against
  `ProducerProto` so ty's match succeeds.
- If `Optional[CodecProto]` turns out to satisfy the protocol, default to
  `None` — simpler and avoids importing a runtime symbol we never call.
  Implementation plan picks whichever passes ty.

#### `faststream_redis_timers/testing.py` — `FakeTimersProducer` and `TestTimersBroker`
- `FakeTimersProducer`: add the same `codec` attribute (mirrors
  `TimersProducer`).
- `TestTimersBroker.create_publisher_fake_subscriber`: drop `@staticmethod`,
  add `self`. Body untouched.

#### `faststream_redis_timers/registrator.py` — `TimersRegistrator`
- `subscriber()`: drop
  `middlewares: Sequence[SubscriberMiddleware[TimerMessage]] = ()` from
  the signature, and drop `middlewares_=middlewares` from the
  `add_call(...)` call.
- `publisher()`: drop `middlewares: Sequence[PublisherMiddleware] = ()`
  from the signature and the corresponding `middlewares=middlewares`
  pass-through to `create_publisher(...)`.

#### `faststream_redis_timers/publisher/factory.py`
- Drop the `middlewares=` parameter and the `middlewares=middlewares`
  pass-through to the publisher constructor.

#### `faststream_redis_timers/publisher/usecase.py`
- Audit and remove any `middlewares` storage that becomes unreachable.
- `_extra_middlewares=()` at lines 79/87/94 is a private signature mirroring
  upstream `PublisherUsecase._publish`. Implementation plan checks whether
  0.7's `_publish` still takes this kwarg; if not, drop the local plumbing
  and update the call site in `tests/test_delivery.py:106`.

#### `faststream_redis_timers/router.py` — `TimersRoute`, `TimersRoutePublisher`
- Drop `middlewares=` from the publisher route signature and pass-through.
- Drop `middlewares=` from the subscriber route signature and pass-through.
- `broker_middlewares=` (broker-scope) at the router-base level stays.

#### `faststream_redis_timers/broker.py`
- `broker_middlewares=middlewares` (broker-scope) stays — unchanged in 0.7.
- Audit other `faststream._internal.*` imports for moves/renames; fix as
  ty/ruff flag them.

#### `faststream_redis_timers/subscriber/config.py`
- Verify `AckPolicy.NACK_ON_ERROR` still exists in 0.7 under the same module
  path. If renamed, update.

#### Tests
- `tests/test_delivery.py:106` passes `_extra_middlewares=()` to
  `pub._publish(...)`. Keep or remove depending on whether the private
  signature still accepts it post-migration.
- Any test passing `middlewares=[...]` to `broker.subscriber(...)`,
  `broker.publisher(...)`, `TimersRouter`, `TimersRoute`, or
  `TimersRoutePublisher`:
  - If the test was only covering the per-call middleware shape, delete.
  - If the test covered some other behavior that incidentally passed
    middlewares, rewrite using broker-scope `BaseMiddleware`
    (`TimersBroker(middlewares=[...])`).
- `--cov-fail-under=100` (adopted in PR1) is the hard gate: every removed
  code branch must have its coverage line gone, and every new branch
  (e.g., the `codec` attribute init, if it has any conditional) must be
  exercised.

#### Docs
- Spot-checked: `README.md` and `docs/usage/*.md` contain no per-call
  `middlewares=` examples (verified via `grep` during brainstorming), so
  no doc rewrite is required. Re-verify during PR2 implementation in case
  intervening commits added one.

### Concrete 0.7 surface (verified via upstream `main` branch)

For reference during implementation:

```python
# faststream/_internal/producer.py — ProducerProto attributes
_parser: AsyncCallable
_decoder: AsyncCallable
codec: CodecProto  # NEW in 0.7

# faststream/_internal/endpoint/subscriber/usecase.py — add_call signature
def add_call(
    self,
    *,
    parser_: Optional[CustomCallable],
    decoder_: Optional[CustomCallable],
    dependencies_: Iterable[Dependant],
    codec_: Optional[CodecProto] = None,  # NEW; timers passes nothing
) -> Self: ...

# faststream/_internal/testing/broker.py — create_publisher_fake_subscriber
@abstractmethod
def create_publisher_fake_subscriber(
    self,
    broker: Broker,
    publisher: Any,
) -> tuple[SubscriberUsecase[Any], bool]: ...
```

## Verification

### PR1

PR1 is done iff:

- Local `uv lock` regenerates without resolving `faststream>=0.7`
  (lockfile is gitignored — verified by local resolve, not by diff).
- `uv sync` succeeds against the regenerated lock.
- `just lint` clean.
- `just test` green (Redis-backed integration suite — unaffected by a pin
  tightening that excludes a version not yet adopted).
- `git grep -n "faststream~=0.6"` returns nothing.
- `planning/specs/2026-06-03-faststream-0.7-migration-design.md` exists in
  the working tree and is tracked.
- `planning/specs/.gitkeep` and `planning/plans/.gitkeep` exist.
- `CLAUDE.md` contains the new `## Workflow` section.

### PR2

PR2 is done iff:

- Local `uv lock --upgrade` resolves `faststream` to a `0.7.x` release.
- `uv sync` succeeds against the regenerated lock.
- `just lint` clean (ruff + ty).
- `just test` green at `--cov-fail-under=100` — all five test files pass.
- `git grep -n "middlewares_=\|middlewares=" faststream_redis_timers/ tests/`
  returns only `broker_middlewares=` entries — no per-call references.
- `git grep -n "faststream~=0.6\|faststream<0.7\|faststream>=0.6,<0.7" .`
  returns nothing.
- `python -c "from faststream_redis_timers import TimersBroker, TimersRouter, TestTimersBroker"`
  exits 0.

## Risk register

- **R1 — Coverage drops.** Removing the `middlewares=` kwarg removes
  branches existing tests exercise. The `--cov-fail-under=100` gate
  (adopted in PR1) catches orphaned `if middlewares:` branches by red-failing
  CI. Mitigation: normal TDD-on-test cleanup as part of PR2.
- **R2 — `CodecProto` import path / shape.** Outbox migration left this as
  an unknown resolved at implementation time. Same here. Mitigation:
  implementation plan inspects the installed 0.7 wheel; either set the
  attribute to the upstream default codec instance or to `None` if the
  protocol permits it.
- **R3 — `AckPolicy.NACK_ON_ERROR` may have moved.** The enum's import
  path (`faststream.middlewares`) and member name should be verified during
  PR2 implementation. Mitigation: single-line fix if renamed.
- **R4 — `_internal.*` imports may have moved.** This package imports ~15
  symbols from `faststream._internal.*` (configs, broker, types,
  basic_types). None are documented as stable. Mitigation: rely on lint +
  test pipeline to surface broken imports; each is a single-line fix.
- **R5 — `_extra_middlewares=` in `TimersPublisher._publish`.** The private
  kwarg at `publisher/usecase.py:79,87,94` and `tests/test_delivery.py:106`
  mirrors upstream `PublisherUsecase._publish`. If upstream removed this
  kwarg in 0.7, the test breaks first and the call site must be updated
  together. Mitigation: implementation plan inspects 0.7's `_publish`
  signature before deciding whether to delete or keep.
- **R6 — Router public API break.** Dropping `middlewares=` from
  `TimersRoute` / `TimersRoutePublisher` is a hard break for any downstream
  user passing it. Mitigation: document in commit message + PR body; v0
  package, no stability promise.
- **R7 — Fake-broker patches.** If `TestTimersBroker`'s patch surfaces
  intercept `BrokerUsecase` dispatch hooks that moved in 0.7, patches may
  stop firing cleanly. Mitigation: surface via `tests/test_fake.py`;
  replace patch site if dispatch hook moved.
- **R8 — Existing coverage may be <100%.** If `just test` does not already
  reach 100%, the gate addition either forces in-PR coverage backfill
  (acceptable scope creep for PR1) or moves to PR2. Mitigation:
  implementation plan for PR1 starts by running the suite and inspecting
  the report; the spec does not assume the baseline.

## Unknowns the implementation plan will resolve

1. Exact `CodecProto` import path and whether `None` is allowed for the
   `codec` attribute.
2. Whether `AckPolicy.NACK_ON_ERROR` survived under that exact name and
   module path.
3. Whether `PublisherUsecase._publish` in 0.7 still accepts
   `_extra_middlewares=`.
4. Whether any `faststream._internal.*` symbol the package imports was
   moved or renamed.
5. Whether the current suite already reaches 100% coverage (gates whether
   PR1 can adopt `--cov-fail-under=100` directly).

Each is a small inspection step; none materially shifts the design.

## Out of scope (deferred to follow-up specs)

- Adopting broker-level `AckPolicy` default (per-broker default that
  subscribers inherit unless overridden).
- Adopting multi-broker capability (run `TimersBroker` alongside another
  in a single `FastStream` app).
- Adopting `RedisClusterBroker` (new in 0.7) — this package's broker
  currently rejects `RedisCluster` clients; cluster support would be its
  own design.
- MQTT or any other new transport.
- README/docs rewrite beyond mechanical removal of per-call `middlewares=`
  examples.
- Any `CHANGELOG.md` entry — none exists; package version is `"0"`.

## Order of operations

### PR1 — `chore/pin-faststream-pre-0.7`

1. `git switch -c chore/pin-faststream-pre-0.7`.
2. `pyproject.toml`: `faststream~=0.6` → `faststream>=0.6,<0.7`; append
   `--cov-fail-under=100` to pytest `addopts`.
3. `uv lock && uv sync` (lockfile is gitignored — local resolve only).
4. `just test` — confirm green at 100%. If <100%, fill gaps or revert the
   `--cov-fail-under=100` change and defer it to PR2.
5. `mkdir -p planning/specs planning/plans`;
   `touch planning/specs/.gitkeep planning/plans/.gitkeep` (already done as
   part of writing this spec).
6. Confirm `planning/specs/2026-06-03-faststream-0.7-migration-design.md`
   is staged (this file).
7. Edit `CLAUDE.md`: insert `## Workflow` section between `## Commands` and
   `## Tests`.
8. `just lint`.
9. Single commit:
   `chore: pin faststream <0.7 and adopt planning/ workflow`.
   Body lists the pin change, the coverage-gate adoption, and the
   planning-dir layout.
10. Push; open PR. Body re-states the pin reason ("guard users against
    accidentally pulling unfinished 0.7 work; companion PR migrates to 0.7
    and drops 0.6 support").

### PR2 — `chore/faststream-0.7-migration` (off `main` after PR1 merges)

1. `git switch main && git pull && git switch -c chore/faststream-0.7-migration`.
2. `pyproject.toml`: `faststream>=0.6,<0.7` → `faststream>=0.7,<0.8`.
3. `uv lock --upgrade && uv sync` (lockfile is gitignored — local resolve only).
4. Fix import/attribute errors as ty and ruff surface them:
   - `TimersProducer.codec` + `FakeTimersProducer.codec`.
   - `add_call` kwargs in `registrator.py`.
   - `create_publisher_fake_subscriber` signature in `testing.py`.
   - Any moved `faststream._internal.*` import.
5. Drop public `middlewares=` kwarg from `TimersRegistrator.subscriber` /
   `.publisher`, `TimersRoute`, `TimersRoutePublisher`.
6. Drop internal storage/plumbing in `publisher/factory.py`,
   `publisher/config.py`, `publisher/usecase.py`. Decide on
   `_extra_middlewares=()` based on upstream 0.7
   `PublisherUsecase._publish` signature.
7. Update tests: delete or rewrite any per-call `middlewares=` usage;
   verify `tests/test_delivery.py:106`'s `_extra_middlewares=()` still
   matches the post-migration signature.
8. Re-grep `README.md` + `docs/usage/*.md` for `middlewares=`; rewrite any
   surviving example to broker-scope or drop it. (Expected no-op per the
   brainstorming-time grep.)
9. `just lint && just test` until green at 100% coverage.
10. Single commit:
    `chore: migrate to faststream 0.7 (breaking: drop per-call middlewares=)`.
    Body enumerates each break point with file pointers.
11. Open PR; body re-states the break for downstream consumers.

## Acceptance criteria

- Both PRs' verification commands pass.
- PR1 commit message documents the pin + planning scaffold + coverage gate.
- PR2 commit message documents each break point.
- No grep hit for `faststream~=0.6`, `faststream<0.7`,
  `faststream>=0.6,<0.7`, or per-call `middlewares=` outside
  `broker_middlewares=` after PR2.
