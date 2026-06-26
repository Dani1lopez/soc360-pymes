# Design: feat-f2-models-migration

## Technical Approach

Reintroduce the F2 persistence layer via controlled manual port from `origin/feat/f2-pr-slicing-01-migration`, split into two stacked PRs that each leave `alembic heads` with a single head.

- **PR-A** lands `Asset`, `Scan`, three tenant plan columns, and Alembic **R1** (`down_revision = b5e9d8c4a123`).
- **PR-B** lands `Vulnerability`, `Report`, and Alembic **R2** (`down_revision = R1`), stacked on PR-A after merge.

Each PR carries its own model files, migration revision, `env.py` imports, `tests/conftest.py` import hook, and DB-free unit tests. No broad cherry-picks or branch merges.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Delivery split | Two PRs by entity dependency | Single PR or size exception | User chose two PRs to stay within 400-line review budget; PR-A is root cluster, PR-B is leaf cluster |
| Stacking model | PR-B branch from PR-A head, retarget to `main` after A merges | Feature-branch chain | Minimizes rebase surface; only R2 + Vuln/Report files move |
| Source extraction | Controlled manual port from reference | Cherry-pick/merge `develop` | Reference branch is clean; `develop` carries unrelated noise |
| Migration split | Two mechanical halves of tested `8f2c1a4b9d7e` | Autogenerate two new revisions | Preserves tested DDL; splitting by table ownership keeps each revision reversible and self-contained |
| Tenant defaults | `server_default` + backfill in migration | Python-side `default=` on model | Avoids mutable default list; backfill covers existing rows |
| Test layering | DB-free unit tests only; integration conftest as infra | DB-backed persistence/cascade tests now | Keeps slice focused on schema; cascade tests deferred to roadmap slices 5–6 |
| Model style | Match `main` conventions (`from __future__ import annotations` first, no stray blanks) | Copy reference verbatim | Reference already matches; only `Report` needs trailing-whitespace cleanup |

## Data Flow

No runtime data flow — schema-only change. Migration chain:

```
main head b5e9d8c4a123
        │
        ▼
    PR-A R1  ──► assets + scans + tenant cols + indexes/triggers/RLS/grants
        │
        ▼
    PR-B R2  ──► vulnerabilities + reports + indexes/triggers/RLS/grants
```

## File Changes

### PR-A (`feat/f2-models-migration-pr-a`)

| File | Action | Description |
|------|--------|-------------|
| `app/modules/assets/models.py` | Create | Asset ORM with tenant FK, CheckConstraints, JSONB metadata |
| `app/modules/scans/models.py` | Create | Scan ORM with asset FK, nullable timestamps, CheckConstraints |
| `app/modules/tenants/models.py` | Modify | Add `scans_per_day`, `ai_enrichment_level`, `report_types` columns |
| `migrations/env.py` | Modify | Register `Asset` and `Scan` imports for autogenerate |
| `migrations/versions/YYYYMMdd_HHMM_R1_*.py` | Create | R1: tenant cols + backfill + assets + scans + indexes/triggers/RLS/grants |
| `tests/conftest.py` | Modify | Import `Asset`, `Scan` in `prepare_database` |
| `tests/unit/conftest.py` | Create | No-op `prepare_database` override for fast unit tests |
| `tests/unit/test_f2_models.py` | Create | DB-free inspection tests for Asset and Scan |

### PR-B (`feat/f2-models-migration-pr-b`)

| File | Action | Description |
|------|--------|-------------|
| `app/modules/vulnerabilities/models.py` | Create | Vulnerability ORM with scan FK, Numeric CVSS, CheckConstraints |
| `app/modules/reports/__init__.py` | Create | Empty module init |
| `app/modules/reports/models.py` | Create | Report ORM with asset FK, nullable generated_at, CheckConstraints |
| `migrations/env.py` | Modify | Register `Vulnerability` and `Report` imports |
| `migrations/versions/YYYYMMdd_HHMM_R2_*.py` | Create | R2: vulnerabilities + reports + indexes/triggers/RLS/grants |
| `tests/conftest.py` | Modify | Import `Vulnerability`, `Report` in `prepare_database` |
| `tests/unit/test_f2_models.py` | Modify | Append DB-free inspection tests for Vulnerability and Report |
| `tests/integration/conftest.py` | Modify | Add `_clean_database()` helper to prevent stale-table errors |

## Interfaces / Contracts

No new public APIs. Schema contracts:

- `Asset`, `Scan`, `Vulnerability`, `Report` inherit from `Base`, use `Mapped[...]`, declare `__table_args__` with named `CheckConstraint`s.
- Tenant columns use `server_default` in migration; ORM side uses `default=` for new-object construction.
- All four tables have `tenant_id` FK with `ON DELETE CASCADE` and an index.
- Parent FK columns (`asset_id`, `scan_id`) are indexed.

## Testing Strategy

| Layer | What to Test | Approach | PR |
|-------|-------------|----------|-----|
| Unit | Model metadata, nullability, defaults, constraint names, FK targets | DB-free inspection via `__mapper__.columns` and `__table__.constraints` | A + B |
| Integration | Alembic upgrade/downgrade roundtrip, single head | Run `alembic upgrade head` and `alembic downgrade -1` against real PG (infra only; full graph test deferred) | B (infra) |
| E2E | Not applicable | — | — |

## Branch / Stacking Strategy

1. `git checkout -b feat/f2-models-migration-pr-a main`
2. Open PR-A targeting `main`. Freeze PR-A once opened.
3. After PR-A merges, `git checkout -b feat/f2-models-migration-pr-b main` and port R2 + Vuln/Report files.
4. Open PR-B targeting `main`. Rebase surface is limited to R2 and four files.

## Migration / Rollout

- **PR-A upgrade**: R1 adds tenant columns with `server_default` + backfill, creates `assets`/`scans`, applies indexes/triggers/RLS/grants.
- **PR-A downgrade**: drops triggers/RLS/grants, drops `assets`/`scans`, drops tenant columns, returns to `b5e9d8c4a123`.
- **PR-B upgrade**: R2 creates `vulnerabilities`/`reports`, applies indexes/triggers/RLS/grants.
- **PR-B downgrade**: drops triggers/RLS/grants, drops `vulnerabilities`/`reports`, returns to R1.

## Rollback Plan

- **PR-B rollback**: `alembic downgrade R1` then `git revert <PR-B merge>`. R1, Asset, Scan, and tenant columns remain.
- **PR-A rollback**: `alembic downgrade b5e9d8c4a123` then `git revert <PR-A merge>`. No data loss for existing F1 rows.

## Risk Mitigation

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Splitting known-good single revision into two | Med | R1/R2 are mechanical halves of tested `8f2c1a4b9d7e`; verify `alembic upgrade head` + `downgrade -1` per PR; linear chain keeps single head |
| PR-B rebase if A changes during review | Med | Freeze PR-A once opened; rebase only R2 + Vuln/Report files |
| Tenant `report_types` mutable default | Low | `server_default` JSONB + backfill in R1; no Python-side mutable default on column |
| Alembic hash collision with future main migrations | Low | R1 reuses `8f2c1a4b9d7e` (rescoped to assets/scans/tenant); R2 hash assigned at apply time; verify single head before each PR merge |
| Stale `DuplicateTableError` on reset | Med | `_clean_database()` drops all public tables before Alembic upgrade in integration conftest |

## Open Questions

- [ ] `tests/integration/test_f2_models.py` (DB-backed persistence/cascade) remains deferred to roadmap slices 5–6; confirm no change.
