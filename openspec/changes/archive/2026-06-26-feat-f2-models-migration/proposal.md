# Proposal: feat/f2-models-migration

## Intent

Reintroduce the F2 domain persistence layer (Asset, Scan, Vulnerability, Report) into `main` as a **two-PR delivery**, via controlled extraction from `origin/feat/f2-pr-slicing-01-migration`. Lands SQLAlchemy models, two chained Alembic revisions, and minimal DB-free tests so later F2 slices (services, API, integration cascades) have a schema foundation. Recovers from the abandoned `develop` / `feat/f2-pr-slicing` chain without broad cherry-picks or branch merges.

## Scope

### In Scope

- **PR-A** (`feat/f2-models-migration-pr-a`): `Asset` + `Scan` models; `tenants/models.py` +3 plan columns; `migrations/env.py` imports for Asset/Scan; Alembic revision **R1** (tenant columns + `assets` + `scans` + indexes/triggers/RLS/grants), `down_revision b5e9d8c4a123`; DB-free unit tests for Asset/Scan; `tests/unit/conftest.py` no-op override; `tests/conftest.py` import hook.
- **PR-B** (`feat/f2-models-migration-pr-b`, stacked on PR-A after merge): `Vulnerability` + `Report` models + `reports/__init__.py`; `migrations/env.py` imports for Vuln/Report; Alembic revision **R2** (`vulnerabilities` + `reports` + indexes/triggers/RLS/grants), `down_revision R1`; DB-free unit tests for Vuln/Report; `tests/integration/conftest.py` infra.

### Out of Scope

- Services, use cases, API routers for F2 domains (roadmap slice 7).
- `tests/integration/test_alembic_migration_graph.py` (separate focused PR).
- DB-backed cascade/persistence tests (roadmap slices 5–6).
- LLM abstraction, demo-vulnerable-target, CI optimization.

## Capabilities

### New Capabilities

- `f2-domain-models`: SQLAlchemy ORM for Asset, Scan, Vulnerability, Report (tenant FK cascade, CheckConstraints, JSONB metadata).
- `f2-tenant-plan-extension`: Tenant plan columns (`scans_per_day`, `ai_enrichment_level`, `report_types`) + backfill wiring.

### Modified Capabilities

- `database-migrations`: **Now two chained revisions (R1 → R2)** replacing the single `8f2c1a4b9d7e`; each independently reversible; single head preserved at every stage.

## Approach

Split **by entity along the dependency chain** (Asset → Scan → Vulnerability; Asset → Report):

- **PR-A** lands the root cluster (Asset, Scan, tenant extension). Scan's only parent (Asset) ships in the same PR, so R1 is self-consistent.
- **PR-B** stacks on PR-A after merge; Vulnerability (parent Scan) and Report (parent Asset) reference tables already on `main`, so R2 chains cleanly onto R1.

Both revisions form a linear chain `b5e9d8c4a123` → R1 → R2; `alembic heads` reports one head at every stage. Minimal DB-free tests ship with the models they validate. Diff forecasts: PR-A ~430 additions, PR-B ~420 (exact counts at `sdd-tasks`).

**Constraints preserved**: `main` is authoritative; `origin/feat/f2-pr-slicing-01-migration` is reference-only; no `develop` merge, no broad cherry-picks, no whole-branch merges; controlled manual port only; `main`-style import ordering (`from __future__ import annotations` first); `Report` trailing-whitespace cleanup during port.

## Affected Areas

| Area | PR | Impact | Description |
|------|----|--------|-------------|
| `app/modules/assets/models.py` | A | New | Asset ORM (53) |
| `app/modules/scans/models.py` | A | New | Scan ORM (62) |
| `app/modules/vulnerabilities/models.py` | B | New | Vulnerability ORM (61) |
| `app/modules/reports/__init__.py`, `models.py` | B | New | Report module + ORM (66) |
| `app/modules/tenants/models.py` | A | Modified | +3 plan columns (5) |
| `migrations/env.py` | A+B | Modified | +4 imports split 2/2 |
| `migrations/versions/..._R1.py` | A | New | assets + scans + tenant cols (~150) |
| `migrations/versions/..._R2.py` | B | New | vulnerabilities + reports (~106) |
| `tests/conftest.py` | A+B | Modified | +4 import-hook lines split 2/2 |
| `tests/integration/conftest.py` | B | New | Real PG + Alembic loader (60) |
| `tests/unit/conftest.py` | A | New | No-op DB override (37) |
| `tests/unit/test_f2_models.py` | A+B | New | DB-free inspection tests split 2/2 (~243) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Splitting known-good single revision into two new revisions | Med | R1/R2 are mechanical halves of the tested `8f2c1a4b9d7e`; verify `alembic upgrade head` + `downgrade -1` per PR; linear chain keeps single head |
| PR-B stacks on PR-A — rebase risk if A changes during review | Med | PR-B branch tracks PR-A head; rebase only R2 + Vuln/Report files; freeze PR-A once opened |
| Tenant `report_types` mutable-default list | Low | `server_default` JSONB + backfill in R1; no Python-side mutable default on the column |
| Alembic hash collision with future main migrations | Low | R1 reuses `8f2c1a4b9d7e` (rescoped to assets/scans/tenant); R2 hash assigned at design; verify single head |
| Sync DB reset quirks (stale `DuplicateTableError`) | Med | Reset DB before any integration subset |

## Rollback Plan

Two-stage, each PR independently reversible:

- **PR-B rollback**: `alembic downgrade R1` (drops `vulnerabilities`/`reports`) then `git revert <PR-B merge>`. R1, Asset, Scan, and tenant columns remain.
- **PR-A rollback**: `alembic downgrade b5e9d8c4a123` (drops `assets`/`scans` + tenant columns) then `git revert <PR-A merge>`. No data loss for existing F1 rows (tenant columns use `server_default` + backfill; downgrade drops them).

## Dependencies

- Main head `b5e9d8c4a123` (`add_last_login_at_to_users`) — current Alembic tip on `main`.
- `origin/feat/f2-pr-slicing-01-migration` — reference-only source for controlled extraction.
- Local Docker + PostgreSQL for the integration subset (PR-B infra).

## Success Criteria

**PR-A**

- [ ] `alembic upgrade head` creates `assets`, `scans` and adds the three tenant columns with backfill; `alembic heads` reports one head.
- [ ] `alembic downgrade b5e9d8c4a123` cleanly reverses PR-A.
- [ ] `pytest -m "not integration"` green (existing 97 + Asset/Scan DB-free unit tests).

**PR-B**

- [ ] After PR-A merges, `alembic upgrade head` creates `vulnerabilities`, `reports`; single head.
- [ ] `alembic downgrade R1` cleanly reverses PR-B.
- [ ] `pytest -m "not integration"` green (existing + PR-A + Vuln/Report DB-free unit tests).

**Both**

- [ ] No broad cherry-picks, no `develop` merge, no whole-branch merges — all changes typed into `main`-based branches.
- [ ] Each PR diff ≤ ~450 additions (reviewable).

## Proposal Question Round

The prior open question (size exception vs split) is **resolved by user decision: two PRs**. No new product/PRD questions surfaced — scope content is unchanged; only delivery packaging changed. A new question round is therefore skipped. If the user wants to revisit split boundary placement, flag it at `sdd-tasks`.
