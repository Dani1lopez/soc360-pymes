# Proposal: migrate-to-uv

## Intent

Migrate soc360-pymes package management from pip + `requirements*.txt` (flat, duplicate-laden, non-deterministic) to `uv` project-mode (`pyproject.toml` + `uv.lock`) **without breaking local dev, Docker, CI, or deployment.** Delivered as the first, reversible slice (PR-1) of a staged migration; pip stays green until uv is proven in CI.

## Scope

### In Scope (PR-1 — this change)
- Add `pyproject.toml` (PEP 621): `requires-python = ">=3.12"`, runtime deps preserving all extras, `dev` optional group (hand-written, not transliterated — fixes duplicate `httpx`/`pytest`/`pytest-asyncio`).
- Add `.python-version` (`3.12`).
- Generate and commit `uv.lock` (treated as generated, not hand-reviewed).
- `.github/workflows/ci.yml`: add a parallel `uv` job (`astral-sh/setup-uv@v4` → `uv sync --frozen --extra dev` → `uv run pytest`); keep the existing pip job. Both must pass.
- `README.md` + `README.es.md`: add a "uv (recommended)" block above the verbatim pip block.
- Header-comment `requirements*.txt` as legacy.

### Out of Scope (follow-up changes, own SDD cycles)
- PR-2: drop the pip CI job, make uv the only CI path. `requirements*.txt` still tracked.
- PR-3: delete `requirements*.txt`, amend `openspec/specs/readme/spec.md` setup order, re-anchor PRD `T-007` to `pyproject.toml`.
- Any future app Docker image (does not exist yet).

## Capabilities

### New Capabilities
- `dependency-management`: uv project-mode packaging contract — `pyproject.toml` source of truth, `uv.lock` reproducible resolution, `uv run`/`uv sync`/`uv add` workflow, dual CI job parity in PR-1.

### Modified Capabilities
- None for this change. The `readme` spec amendment is deferred to the PR-3 follow-up change.

## Approach

Approach 3 from exploration: staged migration to project-mode. PR-1 makes uv available and proven WITHOUT removing pip, so the legacy install is the rollback path. Pins copied verbatim from `requirements*.txt` so the first resolution is identical; extras declared per-package so no `[standard]`/`[asyncio]`/`[hiredis]`/`[redis]`/`[cryptography]`/`[bcrypt]` is squashed.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `pyproject.toml` | New | PEP 621 metadata, runtime deps + `dev` group, tool config hooks. |
| `.python-version` | New | `3.12`; uv interpreter pin. |
| `uv.lock` | New (generated) | Deterministic cross-platform resolution; committed. |
| `requirements.txt`, `requirements-dev.txt` | Modified (legacy header) | Kept verbatim for pip job; flagged legacy. |
| `.github/workflows/ci.yml` | Modified | Add parallel `uv` job; pip job unchanged. |
| `README.md`, `README.es.md` | Modified | Add uv (recommended) block in both languages; pip block kept. |
| `docker-compose.yml` | Audited — Unaffected | Runs only Postgres 16 + Redis 7 for `dev` profile; **no app container installs Python deps**; `docker/*-data` volumes are gitignored data. Dependency-install change cannot reach it. |
| `Dockerfile` | Audited — Absent | None in repo; no image build to break. Foresight: a future app image should use `uv sync --frozen` + BuildKit cache mounts. |
| `.gitignore` | Audited — Compatible | Already ignores `.venv/`, `*.egg-info/`, caches; uv uses `.venv/`. `uv.lock` stays tracked (not ignored). No edit needed. |
| `alembic.ini`, `migrations/env.py` | Audited — Unaffected | `prepend_sys_path = .` works under `uv run alembic`; smoke-test in apply. |
| `scripts/seed_db.py` | Audited — Unaffected | Uses `sys.path.insert`; smoke under `uv run`. |
| `openspec/specs/readme/spec.md` | Deferred (PR-3) | Not touched in PR-1. |
| `openspec/changes/prd-v1-mvp-junio/tasks.md` | Deferred (PR-3) | `T-007` re-anchor cosmetic. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Extras squashed in PEP 621 rewrite (`uvicorn[standard]`, `sqlalchemy[asyncio]`, `redis[hiredis]`, `celery[redis]`, `python-jose[cryptography]`, `passlib[bcrypt]`) | Med | Declare extras per-package; apply smoke-imports `asyncpg`/`cryptography`/`bcrypt`/`hiredis`/`uvicorn` entrypoints under `uv run`. |
| `uv run` vs activated venv confusion | Low | Both target `.venv`; `.venv/bin/{pytest,ruff,mypy}` still work. README standardizes `uv run`. |
| CI parallelization replaces instead of adds | Low | PR-1 ADDS a job; pip job stays until PR-2. |
| `uv.lock` review burden | Med | Marked generated in PR description; not line-reviewed. |
| Python version mismatch on non-3.12 hosts | Low | `.python-version=3.12` + `requires-python>=3.12` surface the same error. |
| Alembic/Celery package availability under uv | Low | Smoke `uv run alembic upgrade head` and `uv run celery --help`; Postgres/Redis via unchanged compose. |
| Dev-only vs runtime leak | Low | Runtime in `[project.dependencies]`; tooling in `[project.optional-dependencies.dev]`; sync with `uv sync --extra dev`. |
| Docker reproducibility regression | Low | No app image today; foresight rule recorded for future images. |

## Rollback Plan

PR-1 keeps the pip CI job + pip README path + `requirements*.txt` as canonical for pip. Revert by deleting the `uv` job, `pyproject.toml`, `.python-version`, `uv.lock`, and the uv README blocks. The project returns to the exact prior pip workflow with zero recovery work.

## Dependencies

- `astral-sh/setup-uv@v4` (GitHub Action).
- `uv` ≥ 0.5 locally and in CI.

## Success Criteria

- [ ] `uv sync --frozen --extra dev` succeeds locally and reproduces the pinned set.
- [ ] New `uv` CI job passes (Postgres + Redis services) alongside the existing pip job.
- [ ] `uv run alembic upgrade head` and `uv run celery --help` smoke succeed.
- [ ] Extras smoke-imports pass under `uv run`.
- [ ] pip install path and legacy `requirements*.txt` still work unchanged.
- [ ] Net hand-written diff of PR-1 forecast and reviewed against the 400-line budget before opening the PR.
