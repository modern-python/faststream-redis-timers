# faststream-redis-timers

FastStream broker integration for Redis-backed distributed timer scheduling.

## Commands

- `just test` — run full test suite (spins up Redis via docker-compose)
- `just lint` — format and lint
- `just install` — install deps

## Workflow

Per-feature workflow: brainstorming → spec in
`planning/specs/YYYY-MM-DD-<slug>-design.md` → writing-plans →
plan in `planning/plans/YYYY-MM-DD-<slug>-plan.md` →
executing-plans / subagent-driven-development →
requesting-code-review → finishing-a-development-branch.

Topic slugs are kebab-case descriptions (e.g. `faststream-0.7-migration`),
not story IDs.

## Tests

- `tests/test_unit.py` — pure unit tests (no Redis required)
- `tests/test_fake.py` — `TestTimersBroker` fake-broker tests (no Redis required)
- `tests/test_delivery.py` — timer delivery integration tests (requires Redis)
- `tests/test_cancel.py` — cancel/future-timer integration tests (requires Redis)
- `tests/test_isolation.py` — topic isolation and multi-broker integration tests (requires Redis)
