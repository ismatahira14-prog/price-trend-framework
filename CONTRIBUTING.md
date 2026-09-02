# Contributing to Price Trend Framework

Thanks for helping build this out. This document is the actual workflow we use — read
it once, then it's mostly muscle memory.

## Getting set up

Follow the "Setup - local (VS Code)" section in [README.md](README.md) first. Once
`pytest` passes locally, you're ready to contribute.

## Git workflow (trunk-based, PR-reviewed)

`main` is always deployable — the live dashboard tracks it directly. Nobody pushes to
`main` directly (it's protected — see below); every change goes through a branch + PR.

1. **Sync and branch off `main`:**
   ```bash
   git checkout main
   git pull
   git checkout -b <type>/<short-description>
   ```
   Branch prefixes: `feature/`, `fix/`, `docs/`, `refactor/`, `chore/`.
   Example: `feature/weather-source`, `fix/crop-yield-rounding`.

2. **Commit as you go.** Write commit messages that explain *why*, not just *what* —
   see the existing `git log` for the house style. Small, focused commits beat one
   giant one.

3. **Keep it green locally before pushing:**
   ```bash
   pytest -q
   ```
   If you touched `dashboard/`, also sanity-check it runs: `.\run.cmd dashboard`.

4. **Push and open a PR against `main`:**
   ```bash
   git push -u origin <branch-name>
   gh pr create --fill   # or open the PR on github.com
   ```
   Fill in the PR template (what changed, why, how you tested it).

5. **CI must pass** (`.github/workflows/tests.yml` runs the test suite on every PR).
   Get at least one review/approval before merging (branch protection enforces this
   once collaborators are added).

6. **Merge via "Squash and merge"** on GitHub (keeps `main`'s history one commit per
   logical change) and delete the branch afterward.

## Adding a new dataset

This is the most common contribution. See the README's "Adding a new dataset"
section — in short: drop the file in `data/raw/`, add an entry to
`config/sources.yaml`, write a loader if the shape is new, run
`python -m pricelab.ingest --all`, and fix any unmapped names it reports.

## Code style

- Match the surrounding module's style — this codebase favors short, direct
  functions with a docstring explaining *why*, not restating *what* the code does.
- `ruff check` runs in CI (advisory for now). Run it locally: `ruff check src tests dashboard`.
- Tests live in `tests/`, mirroring the module they cover. New loaders, data
  functions, and dashboard logic all need at least one test — see
  `tests/test_dashboard_app.py` for how we test Streamlit pages headlessly
  (`streamlit.testing.v1.AppTest`), which has caught several real bugs in this
  project that manual testing missed.

## Reporting bugs / requesting features

Use GitHub Issues — templates are provided for both. For dashboard bugs, a
screenshot and the exact steps to reproduce save everyone time.

## Project structure

See "Project layout" in [README.md](README.md) for what lives where.
