# faststream-redis-timers

FastStream broker integration for Redis-backed distributed timer scheduling.

## Commands

`just` (task runner) + `uv` (package manager); the [`Justfile`](Justfile) is the
source of truth for recipes — run `just --list` or read it. The non-obvious bits:

- `just test [args]` — full suite in docker compose (spins up Redis). Args
  forward to pytest. `tests/test_unit.py` + `tests/test_fake.py` need no Redis;
  the rest (the integration suites) do.
- `just lint` / `just lint-ci` — autofix vs non-mutating; `lint-ci` also runs the
  planning-bundle validator (`planning/index.py --check`).
- Verifying a Python-version / interpreter-compat change: run the **full** suite
  on the target interpreter (the CI matrix, or `just test` in docker), not just
  the no-Redis subset. An integration-only failure — e.g. a broker-shutdown hang
  that only bites under a specific interpreter's async timing — won't surface in
  `test_unit.py` / `test_fake.py` alone.

## Workflow

Planning uses a portable convention — `architecture/` (repo root) is the living
**truth home** and promotion target; `planning/changes/` holds the per-change
bundles. Start at the
[Quick path](planning/README.md#quick-path-start-here) in
[`planning/README.md`](planning/README.md) (the authoritative spec) to pick a
lane — **Full** (`design.md` + `plan.md`), **Lightweight** (single `change.md`),
or **Tiny** (just a commit) — and ship. `just check-planning` validates bundles;
`just index` prints the change + decision listing; `planning/_templates/` are
copy-and-fill starting points.

## Architecture

[`architecture/`](architecture/) is the living per-capability truth home.
**When a change alters a capability's behavior, update the matching
`architecture/<capability>.md` in the same PR** — that promotion keeps
`architecture/` true. Capability pages are authored over time; see
[`architecture/README.md`](architecture/README.md).
