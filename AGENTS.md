# faststream-redis-timers

FastStream broker integration for Redis-backed distributed timer scheduling.
[`CONTEXT.md`](CONTEXT.md) opens with what it does and owns the vocabulary — read it before naming
a concept in code, a test name, or an issue title.

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth —
`just --list`, or read it. The things it does not say:

- `tests/test_unit.py`, `tests/test_fake.py`, `tests/test_store_seam.py` and
  `tests/test_tuning_defaults.py` need no Redis; the rest (the integration suites) do.
- Verifying a Python-version / interpreter-compat change: run the **full** suite on the target
  interpreter (the CI matrix, or `just test` in docker), not just the no-Redis subset. An
  integration-only failure — e.g. a broker-shutdown hang that only bites under a specific
  interpreter's async timing — won't surface in the no-Redis subset alone.

## Workflow

Every link in `README.md` must be absolute: `https://github.com/modern-python/<repo>/blob/main/<path>`,
or `.../tree/main/<path>` for a directory. Never a relative path: `README.md` is also the PyPI long
description, and PyPI does not rewrite relative links, so a relative one 404s on the package page.
