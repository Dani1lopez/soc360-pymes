# Design: migrate-to-uv

## Technical Approach

PR-1 introduces uv project-mode alongside the existing pip workflow without breaking it. We hand-write a `pyproject.toml` that maps the current `requirements*.txt` pins into PEP 621 metadata, preserving extras per-package to avoid squashing `[standard]`, `[asyncio]`, `[hiredis]`, `[redis]`, `[cryptography]`, and `[bcrypt]`. A parallel CI job proves uv before pip is ever removed. The `requirements*.txt` files stay verbatim and receive a legacy header. No Dockerfile exists, so Docker/Compose is a no-op; future-image guidance is documented only.

## Architecture Decisions

| Decision | Options | Tradeoffs | Choice |
|----------|---------|-----------|--------|
| Keep pip green in PR-1 | (a) Replace pip immediately (b) Add uv in parallel, drop pip later | (a) Breaks rollback, blocks team if uv fails (b) Slightly larger CI matrix, safe rollback | (b) Parallel uv job; pip untouched |
| Extras per-package vs flattened | (a) `uvicorn[standard]==0.32.1` (b) `uvicorn==0.32.1` + manual transitive deps | (a) Matches current intent, uv resolves extras (b) Loses upstream extras mapping, maintenance burden | (a) Preserve brackets in `pyproject.toml` |
| `uv.lock` treatment | (a) Commit and treat as generated (b) Ignore | (a) Reproducible resolution, standard uv practice (b) Loses frozen sync guarantee | (a) Commit; PR description marks generated |
| Dev dependency grouping | (a) `[project.optional-dependencies.dev]` (b) Dependency groups (PEP 735) if uv supports | (a) Works today with `uv sync --extra dev` (b) May require newer uv | (a) Optional extras `dev` |
| Lockfile version pinning | (a) Pin exact versions from `requirements*.txt` (b) Re-resolve to latest compatible | (a) Identical first resolution, zero behaviour change (b) Risk of unexpected upgrades | (a) Copy pins verbatim |

## Data Flow

No runtime data flow changes. Dependency resolution moves from `pip install -r requirements*.txt` to `uv sync --frozen --extra dev`, producing a `.venv` with the same package tree.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Create | PEP 621 metadata, `requires-python>=3.12`, runtime deps with extras, `[project.optional-dependencies.dev]` |
| `.python-version` | Create | `3.12` — uv interpreter pin |
| `uv.lock` | Create (generated) | Committed; deterministic resolution |
| `requirements.txt` | Modify | Add legacy header pointing to `pyproject.toml`; pins unchanged |
| `requirements-dev.txt` | Modify | Add legacy header; content unchanged |
| `.github/workflows/ci.yml` | Modify | Add parallel `uv` job (`astral-sh/setup-uv@v4` → `uv sync --frozen --extra dev` → `uv run pytest`) |
| `README.md` | Modify | Insert uv quickstart block above pip block |
| `README.es.md` | Modify | Insert Spanish uv quickstart block above pip block |

## Interfaces / Contracts

### `pyproject.toml` structure

```toml
[project]
name = "soc360-pymes"
version = "0.1.0"
description = "..."
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.115.6",
    "uvicorn[standard]==0.32.1",
    "sqlalchemy[asyncio]==2.0.36",
    ...
]

[project.optional-dependencies]
dev = [
    "pytest==8.3.4",
    "pytest-asyncio==0.24.0",
    "ruff==0.8.4",
    ...
]

[tool.ruff]
# existing config stays if present; otherwise rely on current ruff CLI flags
```

### CI contract

- Existing `test` job: unchanged pip path.
- New `test-uv` job: same services, same env vars, steps:
  1. `actions/checkout@v4`
  2. `astral-sh/setup-uv@v4` (no Python setup action needed)
  3. `uv sync --frozen --extra dev`
  4. `uv run pytest`

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Smoke — sync | `uv sync --frozen --extra dev` reproduces `.venv` | Run locally and in CI; assert no resolution errors |
| Smoke — extras | Extra-provided packages present | `uv run python -c "import uvicorn, sqlalchemy.ext.asyncio, redis.asyncio, celery, jose, passlib"` |
| Smoke — commands | Tooling runs inside uv | `uv run pytest`, `uv run ruff check .`, `uv run mypy .`, `uv run alembic upgrade head`, `uv run celery --help` |
| Smoke — seed | Seed script under uv | `uv run python scripts/seed_db.py --dry-run` |
| Integration — CI parity | Both jobs pass on PR | Open PR, verify pip job and uv job green |
| Regression — pip | Legacy install still works | Fresh venv + `pip install -r requirements-dev.txt` + `pytest` |

## Migration / Rollout

Phased:
1. **PR-1 (this change)**: uv available and proven; pip stays canonical.
2. **PR-2 (future SDD)**: Drop pip CI job; `requirements*.txt` still tracked.
3. **PR-3 (future SDD)**: Delete `requirements*.txt`; update README spec; re-anchor PRD `T-007`.

Rollback: remove `pyproject.toml`, `.python-version`, `uv.lock`, uv CI job, and uv README blocks. `requirements*.txt` remain verbatim → pip workflow restored instantly.

## Open Questions

- None blocking. Future Docker image should use `uv sync --frozen` with BuildKit cache mounts; documented as foresight only.
