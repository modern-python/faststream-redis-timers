# mkdocs → GitHub Actions migration + action version bumps

**Date:** 2026-06-09
**Status:** Approved (design)

## Goal

Move docs hosting from Read the Docs to GitHub Pages via a GitHub Actions
workflow, bring CI layout into line with `modern-di` (reusable
`_checks.yml`), and bump pinned action versions across all workflows.

## Non-goals

- Adopting modern-di's weekly `scheduled.yml` dependency check (out of scope
  for this pass).
- Refactoring the Justfile's `test` / `install` recipes away from
  `docker compose` (orthogonal — CI already runs pytest inline against a
  service-container Redis, not via `just test`).
- Changing the Python matrix or supported versions.
- Reworking `mkdocs.yml` content, theme, or nav.

## Current state

| Concern    | Today                                                    |
|------------|----------------------------------------------------------|
| Docs host  | Read the Docs (`.readthedocs.yaml` → `docs/requirements.txt` → `mkdocs.yml`) |
| CI         | `.github/workflows/ci.yml` (single file, lint + pytest jobs, Redis service) |
| Publish    | `.github/workflows/publish.yml` (release-triggered, runs `just publish`)    |
| Actions    | `actions/checkout@v4`, `extractions/setup-just@v2`, `astral-sh/setup-uv@v3` |

`docs/requirements.txt` contains the mkdocs build dependencies and is
consumed by Read the Docs via `.readthedocs.yaml`.

## Target state

| Concern    | After                                                    |
|------------|----------------------------------------------------------|
| Docs host  | GitHub Pages (`gh-pages` branch, force-pushed by `mkdocs gh-deploy`) |
| CI         | `_checks.yml` (reusable) called from `ci.yml`            |
| Docs CI    | `docs.yml` (path-filtered, runs `just docs-deploy`)       |
| Publish    | `publish.yml` (unchanged behavior, bumped actions)        |
| Actions    | `actions/checkout@v6`, `extractions/setup-just@v4`, `astral-sh/setup-uv@v8.2.0` |

`docs/requirements.txt` is preserved and consumed by
`uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force`
(matches modern-di's pattern; keeps deps reproducible locally).

## Changes

### Added files

#### `.github/workflows/_checks.yml`

Reusable workflow. Mirrors modern-di's `_checks.yml` structurally, with
two adaptations:

- The `pytest` job keeps the `services.redis` block (image `redis:8`,
  port `6379`, health-check options) — required by this repo's
  integration tests.
- The `pytest` step keeps the inline `uv sync --all-extras
  --no-install-project` + `uv run --no-sync pytest . --cov=.
  --cov-report xml` invocation, with the same `PYTHONDONTWRITEBYTECODE`,
  `PYTHONUNBUFFERED`, and `REDIS_URL=redis://127.0.0.1:6379/0` env vars
  as the current `ci.yml`. Reason: `just test` runs `docker compose`
  which is incompatible with the GitHub Actions service-container model.

Triggers: `workflow_call: {}`.

Action versions: `actions/checkout@v6`, `extractions/setup-just@v4`,
`astral-sh/setup-uv@v8.2.0` (with `enable-cache: true` and
`cache-dependency-glob: "**/pyproject.toml"` on the `setup-uv` step).

Python: lint uses `3.13`; pytest matrix is `["3.13", "3.14"]` with
`fail-fast: false` (unchanged from today).

Lint job runs `just install lint-ci` (unchanged).

#### `.github/workflows/docs.yml`

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

`fetch-depth: 0` is required by `mkdocs gh-deploy` because it commits to
`gh-pages` and needs full history to detect the branch. `contents: write`
is required to push to `gh-pages`.

### Modified files

#### `.github/workflows/ci.yml`

Becomes a thin wrapper around `_checks.yml`. Keeps the existing
triggers (`push` to `main`, `pull_request: {}`) and `concurrency` block
(`group: ${{ github.head_ref || github.run_id }}`, `cancel-in-progress:
true`). Body:

```yaml
jobs:
  checks:
    uses: ./.github/workflows/_checks.yml
```

#### `.github/workflows/publish.yml`

Behavior unchanged. Action versions bumped:
- `actions/checkout@v4` → `@v6`
- `extractions/setup-just@v2` → `@v4`
- `astral-sh/setup-uv@v3` → `@v8.2.0`

#### `Justfile`

Append:

```just
# Force-pushes built site to gh-pages; CI runs this on push to main.
# Manual invocation from a stale checkout will roll the live site back.
docs-deploy:
    uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
```

(Same recipe and comment as modern-di — the warning matters because
`gh-deploy --force` overwrites whatever is live.)

### Deleted files

- `.readthedocs.yaml` — Read the Docs hosting is decommissioned.

### Files kept as-is

- `docs/requirements.txt` — still the source of mkdocs build deps,
  consumed by `uvx --with-requirements` in the new `docs-deploy` recipe.
- `mkdocs.yml` — no content or theme changes.
- `docs/**` — no doc edits.

## Operational follow-up (manual, after merge)

After the first successful `docs.yml` run creates the `gh-pages` branch:

1. Repo Settings → Pages → Source: **Deploy from a branch**, Branch:
   `gh-pages` / `(root)`.
2. Verify the published URL renders the site.
3. (Optional) Update README badges and any RTD links to point at the
   GitHub Pages URL. *Out of scope for the implementation PR; tracked
   separately if needed.*
4. (Optional) Delete the Read the Docs project from the RTD dashboard.

## Risks and mitigations

| Risk                                                       | Mitigation                                              |
|------------------------------------------------------------|---------------------------------------------------------|
| First `gh-deploy` fails because `gh-pages` doesn't exist   | `mkdocs gh-deploy` creates the branch on first run. No prep needed. |
| Pages not enabled → workflow succeeds but no live site     | Documented as operational follow-up; verify after first run. |
| `setup-uv@v8.2.0` behavior differs from `@v3`              | Modern-di runs this in production; cache key syntax unchanged. Will be caught by the first CI run on the migration PR. |
| `gh-deploy --force` from a stale local checkout rolls site back | Comment in Justfile warns against manual invocation; CI is the canonical deploy path. |
| Read the Docs builds keep running until project is removed | Harmless — RTD will build from `.readthedocs.yaml` which we delete in this PR, so subsequent RTD builds fail until the project is removed. Operational follow-up notes deletion. |

## Verification

After the PR merges:

1. CI on the PR itself runs `_checks.yml` via `ci.yml` and passes (lint +
   pytest matrix, Redis service healthy).
2. After merge to `main`, `docs.yml` triggers (because the PR touches
   `.github/workflows/docs.yml`), builds, and pushes to `gh-pages`.
3. Manual `workflow_dispatch` of `docs.yml` works.
4. `gh-pages` branch exists with rendered HTML at the root.
5. After enabling Pages, the site is reachable at the GitHub Pages URL.
