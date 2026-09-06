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

**The spec for a change is its PR body**, not a committed file: why, design, non-goals,
verification, reviewed with the diff. There is no change file and no lane to choose. A trivial PR
(typo, dep bump, formatter, CI tweak) ships a conventional-commit title with no body ceremony.

Two things outlive the PR, and there are exactly two places to put them: an alternative **rejected**
with reasoning becomes an ADR in [`docs/adr/`](docs/adr/) (`NNNN-slug.md`, sequential, with a
revisit trigger), and real work **not scheduled** becomes a GitHub issue. There is no third state,
and no separate truth-home directory — a behaviour change is reviewed with the diff, not promoted
to a page.

### Where a fact goes

Four homes, one owner each:

| Home | Holds |
|---|---|
| `faststream_redis_timers/` | anything readable from the module — the default |
| a named test | an **invariant**: must stay true, and a change could silently break it |
| `docs/adr/` | a rejected alternative, with the reasoning that would otherwise be re-litigated |
| `docs/` | anything a user needs; `README.md` is the short version of the same |

Before writing a line anywhere:

> Can an agent get this by reading `faststream_redis_timers/`? → **don't write it.**
> Would a wrong change here fail a test? → it belongs **in the test**, not in prose.
> Does a user need it? → **`docs/`**.
> Otherwise it does not get written.

**Prose about mechanism has no home. There is no file to add a paragraph to.** This file included:
it is always loaded, so a line that restates a docstring, a justfile comment, or `pyproject.toml`
costs every turn and rots in two places at once. This package mirrors FastStream's own Redis broker
layout closely enough to tempt a page re-deriving that structure; that is the failure mode to watch
for here.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches.
Nothing enforces that docstring shape; it is read at review time. A relative link to an ADR *is*
checked — CI runs lychee `--offline` over every `.md` — but a path named in a docstring or a
comment is not. Both ADRs and `INVARIANT:` docstrings ratchet: nothing prunes a record once its
call is settled. Keeping them lean is a standing habit.
