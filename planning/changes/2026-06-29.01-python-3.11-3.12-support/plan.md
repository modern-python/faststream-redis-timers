# Python 3.11/3.12 Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lower the supported-Python floor from 3.13 to 3.11 so the package installs and runs on 3.11, 3.12, 3.13, and 3.14.

**Architecture:** Pure-Python library, no compiled extensions. Two source constructs require 3.12+ (`type` statement and `typing.override`); both are backported via `typing_extensions` (declared as a direct runtime dependency, no `sys.version_info` gating). The rest is metadata (`requires-python`, classifiers, ruff target) and a wider CI matrix.

**Tech Stack:** Python, faststream 0.7, redis 8, anyio, `typing_extensions`, uv (package manager), just (task runner), ruff + ty (lint/type-check), pytest, docker compose (integration suite + Redis).

## Global Constraints

- New Python floor: `requires-python = ">=3.11,<4"`. All edits must remain valid on CPython 3.11 through 3.14.
- `typing_extensions` floor is `>=4.12.0` (matches faststream's existing transitive pin; `override` has existed there since 4.4.0).
- `import` statements live at module level only — never inside function bodies.
- Type-checker suppressions use `# ty: ignore[...]`, never `# type: ignore`.
- `uv.lock` is git-ignored — do not commit it. Regenerating it locally is still required so local runs resolve.
- Coverage gate is 100% (`--cov-fail-under=100`); the full suite enforces it. Local 3.11 subset runs use `--no-cov` to bypass the gate (they are an import/runtime smoke check, not the coverage gate).
- `typing.Self` (`broker.py:155`) stays as-is — it exists in the 3.11 stdlib.

---

### Task 1: Make the package compatible with Python 3.11/3.12

Lowers the floor, adds the `typing_extensions` dependency, and rewrites the two incompatible constructs. The pyproject floor change and the source fixes are inseparable: the `override` fix can only be proven by importing on a real 3.11 interpreter, which uv refuses until `requires-python` is lowered; and the ruff `target-version` must move to `py311` alongside the `configs.py` edit or `ruff --fix` (UP040) will revert it.

**Files:**
- Modify: `pyproject.toml` (dependencies, `requires-python`, classifiers, `[tool.ruff] target-version`)
- Modify: `faststream_redis_timers/configs.py:17`
- Modify: `faststream_redis_timers/registrator.py:3`
- Modify: `faststream_redis_timers/broker.py` (import block + decorators at 150/154/159/164)
- Modify: `faststream_redis_timers/subscriber/usecase.py` (import block + decorators at 69/164/169)
- Regenerate (do not commit): `uv.lock`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a package importable on 3.11; the public `RedisClient` type alias keeps its name and meaning (`"Redis[bytes] | Redis[str]"`). No public API names change.

- [ ] **Step 1: Confirm the current break on 3.11 (RED)**

Use the local uv-managed 3.11 interpreter to show `configs.py` does not even parse on 3.11:

```bash
PY311=/Users/kevinsmith/.local/share/uv/python/cpython-3.11.9-macos-aarch64-none/bin/python3.11
$PY311 -m py_compile faststream_redis_timers/configs.py
```

Expected: FAIL with `SyntaxError: invalid syntax` (the PEP 695 `type` statement at line 17). This is the failing state the task fixes. (The `override` import break in the other files is an `ImportError`, not a `SyntaxError`, so it is proven later by the runtime test in Step 8, not here.)

- [ ] **Step 2: Edit `pyproject.toml` — dependency, floor, classifiers, ruff target (all together)**

In `[project]`, change the dependencies block from:

```toml
dependencies = [
    "faststream>=0.7.1,<0.8",
    "redis>=5.0",
]
```

to:

```toml
dependencies = [
    "faststream>=0.7.1,<0.8",
    "redis>=5.0",
    "typing-extensions>=4.12.0",
]
```

Change the floor from:

```toml
requires-python = ">=3.13,<4"
```

to:

```toml
requires-python = ">=3.11,<4"
```

In the `classifiers` list, change:

```toml
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
```

to (add 3.11 and 3.12 above 3.13):

```toml
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
```

In `[tool.ruff]`, change:

```toml
target-version = "py313"
```

to:

```toml
target-version = "py311"
```

- [ ] **Step 3: Regenerate the lock and sync**

Run: `uv lock --upgrade && uv sync --all-extras --all-groups`
Expected: resolves cleanly; `typing-extensions` appears in the lock (it was already present transitively). Do NOT `git add uv.lock` — it is git-ignored.

- [ ] **Step 4: Fix `configs.py` — replace the PEP 695 `type` statement**

Change line 17 from:

```python
type RedisClient = "Redis[bytes] | Redis[str]"
```

to:

```python
RedisClient: TypeAlias = "Redis[bytes] | Redis[str]"
```

Add the import at the top of `configs.py`. The current first import line is `import typing`; add after it:

```python
from typing_extensions import TypeAlias
```

Leave the explanatory comment block immediately above the alias untouched.

- [ ] **Step 5: Fix `registrator.py` — import `override` from `typing_extensions`**

Change line 3 from:

```python
from typing import Any, override
```

to two lines:

```python
from typing import Any
from typing_extensions import override
```

The `@override` decorator usages at lines 18 and 63 (and their `# ty: ignore[invalid-method-override]` comments) are unchanged.

- [ ] **Step 6: Fix `broker.py` — import `override` from `typing_extensions`, swap decorators**

`broker.py` uses `import typing` (line 2) and references `@typing.override` four times plus `typing.Self` once. Keep `import typing` (still needed for `typing.Self` and other `typing.*` uses). Add this import to the top-of-file import block (after the existing `import typing`):

```python
from typing_extensions import override
```

Then replace every `@typing.override` with `@override` (4 occurrences: lines 150, 154, 159, 164). Do NOT touch `async def __aenter__(self) -> typing.Self:` at line 155 — `typing.Self` stays.

- [ ] **Step 7: Fix `subscriber/usecase.py` — import `override` from `typing_extensions`, swap decorators**

This file uses `import typing` (line 3) and `@typing.override` three times. Add to the top-of-file import block (after `import typing`):

```python
from typing_extensions import override
```

Then replace every `@typing.override` with `@override` (3 occurrences: lines 69, 164, 169). Keep `import typing` (other `typing.*` uses remain).

- [ ] **Step 8: Verify the package imports and the unit/fake suites pass on real 3.11 (GREEN)**

These suites need no Redis. Run them on a true 3.11 interpreter via uv (now permitted because the floor is `>=3.11`):

```bash
uv run --python 3.11 pytest tests/test_unit.py tests/test_fake.py --no-cov -v
```

Expected: PASS. This proves both fixes at runtime on 3.11 — the `configs.py` parse fix and that `typing_extensions.override` imports cleanly where `typing.override` would have raised `ImportError`.

If `uv run --python 3.11` is awkward in the environment, the fallback is an explicit ephemeral env:

```bash
uv venv --python 3.11 /private/tmp/claude-501/-Users-kevinsmith-src-pypi-faststream-redis-timers/b6781fe7-4d7e-4081-b268-8696cf7ad9e6/scratchpad/v311
VIRTUAL_ENV=/private/tmp/claude-501/-Users-kevinsmith-src-pypi-faststream-redis-timers/b6781fe7-4d7e-4081-b268-8696cf7ad9e6/scratchpad/v311 uv sync --all-extras --all-groups
VIRTUAL_ENV=/private/tmp/claude-501/-Users-kevinsmith-src-pypi-faststream-redis-timers/b6781fe7-4d7e-4081-b268-8696cf7ad9e6/scratchpad/v311 uv run --no-sync pytest tests/test_unit.py tests/test_fake.py --no-cov -v
```

- [ ] **Step 9: Lint against the new floor**

Run: `just lint-ci`
Expected: PASS. Specifically confirms (a) ruff under `target-version = "py311"` accepts `RedisClient: TypeAlias = ...` and does NOT flag it for conversion back to the `type` statement (UP040 only fires at py312+), and (b) `ty` accepts `typing_extensions.override` and `typing.Self`.

- [ ] **Step 10: Run the full suite (no regression on 3.13 + 100% coverage)**

Run: `just test`
Expected: PASS, coverage 100%. This is the docker integration run (Redis on 3.13); confirms the source changes did not regress the existing platform.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml faststream_redis_timers/configs.py faststream_redis_timers/registrator.py faststream_redis_timers/broker.py faststream_redis_timers/subscriber/usecase.py
git commit -m "feat: support Python 3.11 and 3.12

Backport the PEP 695 type alias and typing.override via typing_extensions,
lower requires-python to >=3.11, add 3.11/3.12 classifiers and ruff target.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Add 3.11 and 3.12 to the CI test matrix

The pytest job in CI currently runs only 3.13 and 3.14. Extend it so the new floor is exercised on every PR.

**Files:**
- Modify: `.github/workflows/_checks.yml` (the `pytest` job's `strategy.matrix.python-version`)

**Interfaces:**
- Consumes: the 3.11-compatible package from Task 1.
- Produces: nothing consumed by later tasks (terminal task).

- [ ] **Step 1: Edit the matrix**

In the `pytest` job, change:

```yaml
        python-version:
          - "3.13"
          - "3.14"
```

to:

```yaml
        python-version:
          - "3.11"
          - "3.12"
          - "3.13"
          - "3.14"
```

Leave the `lint` job (which runs `uv python install 3.13`) unchanged — linting against one interpreter is sufficient and ruff's `target-version` already enforces the floor.

- [ ] **Step 2: Validate the workflow YAML parses**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/_checks.yml')); print('yaml ok')"`
Expected: prints `yaml ok` with no exception. (`pyyaml` is available transitively via the dev tooling; if it is not, `python -c "import yaml"` will fail and you can skip this step — the edit is a 2-line list addition.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/_checks.yml
git commit -m "ci: run pytest matrix on Python 3.11 and 3.12

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the finish

- `Dockerfile` stays on `python:3.13-slim` — it is the dev/test image, not a supported-version gate; no change.
- No `architecture/` page or doc references the version floor, so no capability promotion is required (verified during planning).
- After both tasks: push the branch and open a PR (do not local-merge); watch CI — the new 3.11/3.12 matrix legs are the real cross-version proof.
