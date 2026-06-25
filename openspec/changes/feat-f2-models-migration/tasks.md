# Tasks: feat/f2-models-migration

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | PR-A ~420-430, PR-B ~420-430 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR-A → PR-B |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|------|
| 1 | Asset, Scan, tenant plan extension, R1, DB-free unit tests, hooks | PR-A | Base on `main`; freeze once opened |
| 2 | Vulnerability, Report, R2, DB-free unit tests, integration conftest infra | PR-B | Stack on PR-A during implementation; retarget to `main` after merge |

## Phase 1: PR-A — Asset / Scan / Tenant Extension

- [x] 1.1 Add failing DB-free assertions for `Asset` and `Scan` in `tests/unit/test_f2_models.py` covering defaults, enums, FK targets, JSONB fields, and constraint names.
- [x] 1.2 Create `app/modules/assets/models.py` and `app/modules/scans/models.py` with `Base`, `Mapped[...]`, `__table_args__`, tenant/asset FKs, and `ON DELETE CASCADE`.
- [x] 1.3 Extend `app/modules/tenants/models.py` with `scans_per_day`, `ai_enrichment_level`, and `report_types` defaults aligned to `f2-tenant-plan-extension`.
- [x] 1.4 Update `migrations/env.py`, `tests/conftest.py`, and `tests/unit/conftest.py`, then add R1 for tenant backfill + `assets`/`scans` + indexes/triggers/RLS/grants.

## Phase 2: PR-A Verification

- [x] 2.1 Keep PR-A migration reversible: `alembic upgrade head`, `alembic heads`, and `alembic downgrade b5e9d8c4a123` must all be covered by the PR-A verification notes.
- [x] 2.2 Confirm `pytest -m "not integration"` stays green with the new `tests/unit/test_f2_models.py` coverage and the unit conftest DB override.

## Phase 3: PR-B — Vulnerability / Report

- [ ] 3.1 Add failing DB-free assertions for `Vulnerability` and `Report` in `tests/unit/test_f2_models.py` covering severity/status enums, FK targets, and metadata columns.
- [ ] 3.2 Create `app/modules/vulnerabilities/models.py`, `app/modules/reports/__init__.py`, and `app/modules/reports/models.py` with `Base`, `Mapped[...]`, constraints, and parent FKs.
- [ ] 3.3 Update `migrations/env.py` and `tests/conftest.py` for PR-B imports, then add R2 chained to R1 for `vulnerabilities`/`reports` + indexes/triggers/RLS/grants.
- [ ] 3.4 Add `tests/integration/conftest.py` cleanup/Alembic loader infra only if the integration subset still needs stale-table protection.

## Phase 4: PR-B Verification / Cleanup

- [ ] 4.1 Verify PR-B downgrade returns cleanly to R1 and `alembic heads` still reports a single head.
- [ ] 4.2 Re-run `pytest -m "not integration"` and clean any trailing whitespace/import ordering drift before opening PR-B.
