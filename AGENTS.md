# faststream-redis-timers

FastStream broker integration for Redis-backed distributed timer scheduling.
[`CONTEXT.md`](CONTEXT.md) opens with what it does and owns the vocabulary — read it before naming
a concept in code, a test name, or an issue title.

## Commands

`just` (task runner) + `uv` (package manager); the [`justfile`](justfile) is the source of truth
for recipes — run `just --list` or read it. The things it does not say:

- A `ty` suppression is written `# ty: ignore`, never `# type: ignore`.
- `tests/test_unit.py`, `tests/test_fake.py`, `tests/test_store_seam.py` and
  `tests/test_tuning_defaults.py` need no Redis; the rest (the integration suites) do.
- Verifying a Python-version / interpreter-compat change: run the **full** suite on the target
  interpreter (the CI matrix, or `just test` in docker), not just the no-Redis subset. An
  integration-only failure — e.g. a broker-shutdown hang that only bites under a specific
  interpreter's async timing — won't surface in the no-Redis subset alone.

## Workflow

Real work **not scheduled** becomes a GitHub issue.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches.
Nothing enforces that docstring shape; it is read at review time.
