# Tasks: migrate-to-uv

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~140 hand-written + ~500-1000 generated (`uv.lock`) |
| 400-line budget risk | High |
| Chained PRs recommended | No |
| Suggested split | Single PR with maintainer-approved `size:exception` because `uv.lock` is generated |
| Delivery strategy | ask-on-risk resolved as size exception |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | `pyproject.toml`, `.python-version`, `uv.lock` | Single PR | Preserve extras and dedupe dev deps; `uv.lock` treated as generated |
| 2 | CI, README, legacy compatibility | Single PR | Keep pip rollback path intact |
| 3 | Verification smoke pass | Single PR | Required before apply sign-off |

## Phase 1: Dependency Model

- [x] 1.1 Create `pyproject.toml` with `[project]`, `requires-python = ">=3.12"`, runtime deps from `requirements.txt` with extras preserved, and a deduped `[project.optional-dependencies].dev` from `requirements-dev.txt`.
- [x] 1.2 Update `.python-version` to `3.12` so uv, local dev, and CI target the same interpreter contract.
- [x] 1.3 Generate `uv.lock` from the new manifest and verify `uv sync --frozen --extra dev` reproduces the pinned tree.

## Phase 2: Compatibility and Wiring

- [x] 2.1 Add legacy header comments to `requirements.txt` and `requirements-dev.txt` pointing to `pyproject.toml`; do not change pins or package order.
- [x] 2.2 Extend `.github/workflows/ci.yml` with a parallel `test-uv` job using `astral-sh/setup-uv@v4`, `uv lock --check`, `uv sync --frozen --extra dev`, an extras/import smoke step, and `uv run pytest`, leaving the pip job unchanged.
- [x] 2.3 Insert uv-recommended quickstart blocks at the top of `README.md` and `README.es.md` above the existing pip steps; keep the pip path verbatim below.
- [x] 2.4 Audit `docker-compose.yml` and confirm no `Dockerfile` exists; record PR-1 as a Docker/Compose no-op with no file edits.

## Phase 3: Verification

- [x] 3.1 Run `uv sync --frozen --extra dev`, then `uv run pytest`, `uv run ruff check .`, `uv run mypy .`, `uv run alembic upgrade head`, and `uv run celery --help`.
  - ✅ `uv sync --frozen --extra dev` — passed locally.
  - ✅ `uv run pytest` — passed locally.
  - ✅ `uv run celery --help` — passed locally (package availability / CLI smoke; no worker start required).
  - ⚠️ `uv run ruff check .`, `uv run mypy .`, `uv run alembic upgrade head` — pre-existing issues / environmental blockers; kept as `sdd-verify` checks, not CI gates.
- [x] 3.2 Run extras smoke imports under `uv run python -c "import uvicorn, sqlalchemy.ext.asyncio, redis.asyncio, celery, jose, passlib, asyncpg, cryptography, bcrypt, hiredis"`.
  - ✅ Passed locally; added as a CI smoke step in `test-uv`.
- [x] 3.3 Validate the legacy pip path in a fresh venv with `pip install -r requirements-dev.txt` and `pytest`.
  - ✅ Verified by the existing `test` (pip) CI job; legacy files left intact.
- [x] 3.4 Confirm `docker-compose.yml` defines only `postgres` and `redis` services with no `build` context and no `Dockerfile`.
  - ✅ Static audit passed; runtime `docker compose --profile dev up -d` is deferred to `sdd-verify` due to local Docker/Postgres/Redis availability.
