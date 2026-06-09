# mkdocs → GitHub Actions migration + action bumps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate documentation hosting from Read the Docs to GitHub Pages via a new `docs.yml` workflow, extract `ci.yml` into a reusable `_checks.yml` (mirroring `modern-di`), and bump pinned action versions across all workflows.

**Architecture:** Workflow files are the only mutable surface. `_checks.yml` becomes a `workflow_call`-only reusable workflow containing the lint and pytest jobs; `ci.yml` shrinks to a thin caller; a new `docs.yml` runs `just docs-deploy` on doc-related pushes to `main`. A `docs-deploy` recipe is added to the Justfile so the deploy command is reproducible locally. `.readthedocs.yaml` is deleted.

**Tech Stack:** GitHub Actions (reusable workflows via `workflow_call`), `just` task runner, `uv` package manager, `mkdocs` + `mkdocs gh-deploy` for GitHub Pages publishing, Redis 8 service container for integration tests.

---

## Spec reference

Design: `planning/specs/2026-06-09-mkdocs-gh-actions-design.md`

## File map

**Created:**
- `.github/workflows/_checks.yml` — reusable workflow with `lint` + `pytest` jobs
- `.github/workflows/docs.yml` — GitHub Pages deploy on doc changes

**Modified:**
- `.github/workflows/ci.yml` — thin caller of `_checks.yml`
- `.github/workflows/publish.yml` — action versions bumped
- `Justfile` — appended `docs-deploy` recipe

**Deleted:**
- `.readthedocs.yaml`

**Untouched but worth knowing:**
- `docs/requirements.txt` — still consumed by `mkdocs gh-deploy` via `uvx --with-requirements`
- `mkdocs.yml` — no content/theme changes

---

## Task ordering rationale

Ordered so each commit leaves `main` green:

1. Justfile recipe first — independently testable, no CI surface change.
2. `_checks.yml` next — exists but is dormant (`workflow_call` only) until ci.yml calls it.
3. `ci.yml` refactor — now `_checks.yml` is callable.
4. `docs.yml` — independent of CI; isolated change.
5. `publish.yml` bumps — independent, last because least risky.
6. Delete `.readthedocs.yaml` — final cleanup, no behavior dependency.
7. Verification on a feature branch.

---

## Task 1: Add `docs-deploy` recipe to Justfile

**Files:**
- Modify: `Justfile` (append at end)

- [ ] **Step 1: Read the current Justfile**

Run: `cat Justfile`
Expected: shows recipes `default`, `down`, `sh`, `test`, `build`, `install`, `lint`, `lint-ci`, `publish`. No `docs-deploy` recipe exists yet.

- [ ] **Step 2: Append the `docs-deploy` recipe**

Append the following block at the end of `Justfile` (preserve the existing trailing newline behavior — `eof-fixer` enforces a single trailing newline):

```just

# Force-pushes built site to gh-pages; CI runs this on push to main.
# Manual invocation from a stale checkout will roll the live site back.
docs-deploy:
    uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
```

Note: indentation under the recipe MUST be a tab (just convention), matching the existing recipes in this file.

- [ ] **Step 3: Verify Justfile parses**

Run: `just --list`
Expected: output includes the line `docs-deploy` among the available recipes; no parse error.

- [ ] **Step 4: Dry-check the recipe is well-formed**

Run: `just --show docs-deploy`
Expected: prints
```
docs-deploy:
    uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
```

Do NOT actually run `just docs-deploy` — it would force-push the docs.

- [ ] **Step 5: Lint and format**

Run: `just lint`
Expected: no errors. `eof-fixer` may rewrite the trailing newline; that's fine.

- [ ] **Step 6: Commit**

```bash
git add Justfile
git commit -m "$(cat <<'EOF'
chore(justfile): add docs-deploy recipe for mkdocs gh-deploy

Mirrors modern-di. Used by the upcoming docs.yml workflow and lets
maintainers reproduce the deploy locally if needed.
EOF
)"
```

---

## Task 2: Create reusable `_checks.yml` workflow

**Files:**
- Create: `.github/workflows/_checks.yml`

- [ ] **Step 1: Confirm current CI structure**

Run: `cat .github/workflows/ci.yml`
Expected: shows the existing `lint` and `pytest` jobs with action versions `checkout@v4`, `setup-just@v2`, `setup-uv@v3`, Redis service block on the `pytest` job, Python matrix `3.13` and `3.14`, env vars `PYTHONDONTWRITEBYTECODE: 1`, `PYTHONUNBUFFERED: 1`, `REDIS_URL: redis://127.0.0.1:6379/0`.

- [ ] **Step 2: Create `_checks.yml`**

Create `.github/workflows/_checks.yml` with exactly this content:

```yaml
name: checks
on:
  workflow_call: {}

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: extractions/setup-just@v4
      - uses: astral-sh/setup-uv@v8.2.0
        with:
          enable-cache: true
          cache-dependency-glob: "**/pyproject.toml"
      - run: uv python install 3.13
      - run: just install lint-ci

  pytest:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version:
          - "3.13"
          - "3.14"
    services:
      redis:
        image: redis:8
        ports:
          - 6379:6379
        # Set health checks to wait until redis has started
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v8.2.0
        with:
          enable-cache: true
          cache-dependency-glob: "**/pyproject.toml"
      - run: uv python install ${{ matrix.python-version }}
      - run: |
          uv sync --all-extras --no-install-project
          uv run --no-sync pytest . --cov=. --cov-report xml
        env:
          PYTHONDONTWRITEBYTECODE: 1
          PYTHONUNBUFFERED: 1
          REDIS_URL: redis://127.0.0.1:6379/0
```

Key points:
- `on: workflow_call: {}` makes this callable from `ci.yml` and nothing else (no push/pr triggers — it would otherwise duplicate runs).
- Pytest job retains the Redis service block, env vars, and inline `uv sync` / `uv run pytest` invocation from the original `ci.yml`. We do **not** switch to `just install` / `just test` because `just test` runs `docker compose`, incompatible with the GitHub Actions service-container model.
- Lint job pins Python 3.13.

- [ ] **Step 3: Verify YAML parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/_checks.yml')); print('ok')"`
Expected: prints `ok`. (PyYAML ships with macOS system Python; if missing, use `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/_checks.yml'))"`.)

- [ ] **Step 4: (Optional) actionlint check**

If `actionlint` is installed (`brew install actionlint`), run:

```
actionlint .github/workflows/_checks.yml
```

Expected: no output (clean). If not installed, skip — CI will validate on push.

- [ ] **Step 5: Lint**

Run: `just lint`
Expected: no errors. `eof-fixer` ensures trailing newline.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/_checks.yml
git commit -m "$(cat <<'EOF'
ci: add reusable _checks.yml with bumped action versions

Mirrors modern-di's reusable workflow layout. Keeps the redis service
block and inline pytest command (just test runs docker compose, which
is incompatible with GH Actions service containers).

Bumps: checkout v4->v6, setup-just v2->v4, setup-uv v3->v8.2.0.
EOF
)"
```

---

## Task 3: Refactor `ci.yml` to call `_checks.yml`

**Files:**
- Modify: `.github/workflows/ci.yml` (full rewrite)

- [ ] **Step 1: Replace the contents of `ci.yml`**

Overwrite `.github/workflows/ci.yml` with exactly:

```yaml
name: main

on:
  push:
    branches:
      - main
  pull_request: {}

concurrency:
  group: ${{ github.head_ref || github.run_id }}
  cancel-in-progress: true

jobs:
  checks:
    uses: ./.github/workflows/_checks.yml
```

Triggers and `concurrency` block are byte-for-byte preserved from the original; only the `jobs` block changes.

- [ ] **Step 2: Verify YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Verify reusable-workflow reference path**

Run: `test -f .github/workflows/_checks.yml && echo present`
Expected: prints `present`.

- [ ] **Step 4: (Optional) actionlint**

Run: `actionlint .github/workflows/ci.yml .github/workflows/_checks.yml` (if installed)
Expected: no output.

- [ ] **Step 5: Lint**

Run: `just lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: collapse ci.yml to a caller of _checks.yml

Triggers and concurrency unchanged. All jobs now live in the reusable
workflow, matching modern-di's layout.
EOF
)"
```

---

## Task 4: Create `docs.yml` workflow

**Files:**
- Create: `.github/workflows/docs.yml`

- [ ] **Step 1: Create `docs.yml`**

Create `.github/workflows/docs.yml` with exactly this content:

```yaml
name: Deploy Docs

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - ".github/workflows/docs.yml"
  workflow_dispatch:

concurrency:
  group: docs-deploy
  cancel-in-progress: true

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: extractions/setup-just@v4
      - uses: astral-sh/setup-uv@v8.2.0
      - run: just docs-deploy
```

Key points:
- `fetch-depth: 0` is required by `mkdocs gh-deploy` so it can read/commit on `gh-pages`.
- `permissions: contents: write` is required to push to `gh-pages`.
- `paths` filter limits triggers to actual doc changes; `workflow_dispatch` allows manual runs.
- The deploy command is `just docs-deploy` (defined in Task 1).

- [ ] **Step 2: Verify YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docs.yml')); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: (Optional) actionlint**

Run: `actionlint .github/workflows/docs.yml` (if installed)
Expected: no output.

- [ ] **Step 4: Lint**

Run: `just lint`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "$(cat <<'EOF'
ci: add docs.yml workflow to deploy mkdocs to GitHub Pages

Triggers on push to main when docs/, mkdocs.yml, or this workflow
changes. Force-pushes the built site to gh-pages via the new
just docs-deploy recipe. Replaces Read the Docs as the docs host.

GitHub Pages source must be set to gh-pages / (root) in repo settings
after the first successful run.
EOF
)"
```

---

## Task 5: Bump action versions in `publish.yml`

**Files:**
- Modify: `.github/workflows/publish.yml`

- [ ] **Step 1: Read current `publish.yml`**

Run: `cat .github/workflows/publish.yml`
Expected: a single job using `actions/checkout@v4`, `extractions/setup-just@v2`, `astral-sh/setup-uv@v3`, running `just publish` with `PYPI_TOKEN`.

- [ ] **Step 2: Replace the contents of `publish.yml`**

Overwrite `.github/workflows/publish.yml` with exactly:

```yaml
name: Publish Package

on:
  release:
    types:
      - published

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: extractions/setup-just@v4
      - uses: astral-sh/setup-uv@v8.2.0
      - run: just publish
        env:
          PYPI_TOKEN: ${{ secrets.PYPI_TOKEN }}
```

Only changes: three action version bumps. Behavior, triggers, and env unchanged.

- [ ] **Step 3: Verify YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml')); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: (Optional) actionlint**

Run: `actionlint .github/workflows/publish.yml` (if installed)
Expected: no output.

- [ ] **Step 5: Lint**

Run: `just lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "$(cat <<'EOF'
ci: bump publish.yml action versions

checkout v4->v6, setup-just v2->v4, setup-uv v3->v8.2.0. No behavior
change.
EOF
)"
```

---

## Task 6: Delete `.readthedocs.yaml`

**Files:**
- Delete: `.readthedocs.yaml`

- [ ] **Step 1: Confirm the file exists**

Run: `cat .readthedocs.yaml`
Expected: shows the existing 14-line config (Python 3.10, requirements at `docs/requirements.txt`, mkdocs config at `mkdocs.yml`).

- [ ] **Step 2: Delete the file**

Run: `git rm .readthedocs.yaml`
Expected: prints `rm '.readthedocs.yaml'`.

- [ ] **Step 3: Confirm `docs/requirements.txt` is still present**

Run: `cat docs/requirements.txt`
Expected: prints the mkdocs requirements (still used by `mkdocs gh-deploy` via `uvx --with-requirements` in `Justfile`).

- [ ] **Step 4: Lint**

Run: `just lint`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore: remove .readthedocs.yaml (docs now deploy from GH Actions)

Read the Docs is no longer the docs host. docs/requirements.txt
remains and is consumed by mkdocs gh-deploy via uvx --with-requirements.

After this PR merges and the first docs.yml run creates the gh-pages
branch, set repo Settings -> Pages -> Source: gh-pages / (root).
EOF
)"
```

---

## Task 7: End-to-end verification on a feature branch

This task does not write code — it confirms the previous six tasks behave correctly on GitHub before merging.

- [ ] **Step 1: Push the branch**

Assuming you've been working on a feature branch (e.g. `chore/mkdocs-gh-actions`):

```bash
git push -u origin chore/mkdocs-gh-actions
```

If you have been committing on `main` locally, first move the commits to a branch:

```bash
git branch chore/mkdocs-gh-actions
git reset --hard origin/main
git checkout chore/mkdocs-gh-actions
git push -u origin chore/mkdocs-gh-actions
```

- [ ] **Step 2: Open a draft PR**

```bash
gh pr create --draft --title "ci: migrate docs to GH Actions + bump action versions" --body "$(cat <<'EOF'
## Summary
- Migrate docs hosting from Read the Docs to GitHub Pages via new `docs.yml`
- Extract `ci.yml` jobs into reusable `_checks.yml` (mirrors modern-di)
- Bump action versions: `checkout@v4`->`@v6`, `setup-just@v2`->`@v4`, `setup-uv@v3`->`@v8.2.0`
- Add `just docs-deploy` recipe
- Delete `.readthedocs.yaml`

Spec: planning/specs/2026-06-09-mkdocs-gh-actions-design.md
Plan: planning/plans/2026-06-09-mkdocs-gh-actions-plan.md

## Test plan
- [ ] CI (`_checks.yml` via `ci.yml`) passes: lint + pytest matrix
- [ ] After merge, `docs.yml` triggers (PR touches `.github/workflows/docs.yml`)
- [ ] `gh-pages` branch is created on first successful `docs.yml` run
- [ ] Manual `workflow_dispatch` of `docs.yml` works
- [ ] Configure Pages: Settings -> Pages -> Source: `gh-pages` / `(root)`
- [ ] Published site renders at the GitHub Pages URL

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch the CI run**

```bash
gh pr checks --watch
```

Expected:
- The `main / checks / lint` and `main / checks / pytest (3.13)` and `main / checks / pytest (3.14)` jobs all pass.
- `docs.yml` does NOT run on the PR (it triggers on `push` to `main`, not `pull_request`). This is expected.

- [ ] **Step 4: Inspect the workflow run via the UI or `gh`**

```bash
gh run list --workflow ci.yml --limit 3
gh run list --workflow docs.yml --limit 3
```

Expected: CI runs visible; no `docs.yml` runs yet.

- [ ] **Step 5: Merge the PR**

```bash
gh pr ready
gh pr merge --squash --delete-branch
```

(Or use the GitHub UI.)

- [ ] **Step 6: Confirm `docs.yml` triggers on the merge commit**

```bash
gh run list --workflow docs.yml --limit 3 --branch main
gh run watch
```

Expected: a `Deploy Docs` run starts because the merge commit modifies `.github/workflows/docs.yml`. It checks out, sets up `just` + `uv`, runs `just docs-deploy`, which builds the site and force-pushes to `gh-pages`.

- [ ] **Step 7: Confirm `gh-pages` branch exists**

```bash
git fetch origin
git branch -r | grep gh-pages
```

Expected: prints `origin/gh-pages`.

- [ ] **Step 8: Enable GitHub Pages**

In a browser, go to repo Settings → Pages:
- Source: **Deploy from a branch**
- Branch: `gh-pages` / `(root)`
- Save.

Wait ~1 minute for the first Pages build, then visit the URL shown on the settings page.

Expected: the rendered mkdocs site loads.

- [ ] **Step 9: Verify manual dispatch works**

```bash
gh workflow run docs.yml
gh run watch
```

Expected: a manually-triggered `Deploy Docs` run completes successfully.

- [ ] **Step 10: (Optional) Update README / decommission RTD**

Not part of this plan. If you have RTD badges or links in `README.md` pointing at `readthedocs.io`, update them to the GitHub Pages URL in a follow-up PR. Delete the Read the Docs project from the RTD dashboard when convenient.

---

## Rollback

If anything goes wrong after merge:

- **CI broken (`_checks.yml` reference fails):** Revert the merge commit. `ci.yml` reverts to its monolithic form.
- **Docs deploy fails:** The `gh-pages` branch is independent of `main`; nothing else is at risk. Fix forward — usually a Justfile recipe issue or a missing `docs/requirements.txt` dep.
- **Read the Docs builds still running:** Delete the project from the RTD dashboard. No code change needed.

---

## Self-review notes

- **Spec coverage:** Every "Changes" item in the spec maps to a task:
  - `_checks.yml` → Task 2
  - `docs.yml` → Task 4
  - `ci.yml` refactor → Task 3
  - `publish.yml` bumps → Task 5
  - `Justfile` recipe → Task 1
  - `.readthedocs.yaml` deletion → Task 6
  - Operational follow-up (Pages enable) → Task 7 Step 8
- **Type consistency:** Action versions (`checkout@v6`, `setup-just@v4`, `setup-uv@v8.2.0`) match across all four workflow files. `just docs-deploy` is defined in Task 1 and called by Task 4.
- **No placeholders:** All YAML blocks are complete and copy-pasteable; all commands have expected output.
