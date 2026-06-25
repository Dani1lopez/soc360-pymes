## Verification Report

**Change**: `feat-f2-models-migration`
**Scope**: PR-A only (`feat/f2-models-migration-pr-a`)
**Version**: N/A
**Mode**: Strict TDD — confirmed by `openspec/config.yaml` (`strict_tdd: true`) and `pytest` runner availability through `uv run`.

### Scope Boundary

Verified only PR-A tasks 1.1-2.2 and PR-A implementation files.

- In scope: `Asset`, `Scan`, tenant plan columns, R1 migration, Asset/Scan/Tenant DB-free unit tests, unit `prepare_database` override, and PR-A migration registration.
- Out of scope: PR-B tasks 3.1-4.2 (`Vulnerability`, `Report`, R2, PR-B integration infra). These remain intentionally pending and are not blocking this verdict.

### Completeness

| Metric | Value |
|--------|-------|
| PR-A tasks total | 6 |
| PR-A tasks complete | 6 |
| PR-A tasks incomplete | 0 |
| PR-B tasks pending | 6, out of scope |

### PR-A File Scope

| Expected PR-A file | Status | Notes |
|--------------------|--------|-------|
| `app/modules/assets/models.py` | ✅ Present | `Asset` model with tenant FK, JSONB metadata, constraints, timestamps |
| `app/modules/scans/models.py` | ✅ Present | `Scan` model with tenant/asset FKs, JSONB config, constraints, timestamps |
| `app/modules/tenants/models.py` | ✅ Modified | Added `scans_per_day`, `ai_enrichment_level`, `report_types` |
| `migrations/env.py` | ✅ Modified | Imports `Asset` and `Scan` only for PR-A |
| `migrations/versions/20260625_1400_f2_assets_scans_tenant_8f2c1a4b9d7e.py` | ✅ Present | R1 revision, `down_revision = "b5e9d8c4a123"` |
| `tests/conftest.py` | ✅ Modified | Imports `Asset` and `Scan` in `prepare_database` |
| `tests/unit/conftest.py` | ✅ Present | DB-free no-op `prepare_database` override |
| `tests/unit/test_f2_models.py` | ✅ Present | 22 DB-free model inspection tests |

No PR-B `reports` model files, `vulnerabilities` model files, or R2 migration were found in the PR-A scope.

### Build & Tests Execution

**Build**: ➖ Not applicable; schema/model/test verification only.

**Tests**: ✅ Passed

```text
Command: pytest tests/unit -m "not integration"
Result: blocked in this shell because bare `pytest` is not on PATH.

Command: uv run pytest tests/unit -m "not integration"
Result: 265 passed, 7 warnings in 0.59s

Command: uv run pytest tests/unit/test_f2_models.py -q
Result: 22 passed, 1 warning in 0.04s

Command: uv run pytest -m "not integration"
Result: 371 passed, 84 deselected, 95 warnings in 114.54s
```

**Coverage**: ➖ Not available — `openspec/config.yaml` marks coverage unavailable.

### Alembic / Migration Evidence

```text
Command: uv run alembic heads
Result: 8f2c1a4b9d7e (head)

Command: GROQ_API_KEY=<redacted> uv run alembic history
Result: b5e9d8c4a123 -> 8f2c1a4b9d7e (head), linear chain preserved

Command: GROQ_API_KEY=<redacted> uv run alembic upgrade head --sql
Result: generated offline SQL successfully, including tenant columns, assets/scans tables, indexes, updated_at triggers, RLS policies, grants, and alembic_version update to 8f2c1a4b9d7e.

Command: GROQ_API_KEY=<redacted> uv run alembic downgrade 8f2c1a4b9d7e:b5e9d8c4a123 --sql
Result: generated offline downgrade SQL successfully, including revoke/drop policies, triggers, indexes, scans/assets tables, tenant plan columns, and alembic_version rollback to b5e9d8c4a123.
```

Live PostgreSQL was reachable through Docker and verified against the local `soc360_test` database using a redacted test `DATABASE_URL_MIGRATION` override:

```text
Command: docker compose ps
Result: soc360_postgres and soc360_redis Up/healthy

Command: GROQ_API_KEY=<redacted> DATABASE_URL_MIGRATION=<redacted test DB> uv run alembic upgrade head
Result: succeeded through R1 (8f2c1a4b9d7e)

Command: GROQ_API_KEY=<redacted> DATABASE_URL_MIGRATION=<redacted test DB> uv run alembic current
Result: 8f2c1a4b9d7e (head)

Command: GROQ_API_KEY=<redacted> DATABASE_URL_MIGRATION=<redacted test DB> uv run alembic downgrade b5e9d8c4a123
Result: succeeded

Command: GROQ_API_KEY=<redacted> DATABASE_URL_MIGRATION=<redacted test DB> uv run alembic current
Result: b5e9d8c4a123
```

Notes:

- Bare `alembic` is not on PATH in this shell; `uv run alembic ...` is the working invocation.
- The first default live Alembic attempt without the test migration URL override failed with `asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "soc360_app"`. The safe test DB override resolved this.
- Offline Alembic generation requires a test `GROQ_API_KEY` because application settings validation rejects missing `GROQ_API_KEY` when `LLM_PROVIDER='groq'`.

### TDD Compliance

| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | ✅ | `apply-progress` contains a TDD Cycle Evidence table for PR-A tasks 1.1-2.2 |
| All PR-A tasks have tests/evidence | ✅ | 6/6 PR-A tasks have unit or migration command evidence |
| RED confirmed | ✅ | `tests/unit/test_f2_models.py` exists; structural migration evidence exists for task 2.1 |
| GREEN confirmed | ✅ | Focused F2 model tests, unit suite, and full non-integration suite passed |
| Triangulation adequate | ✅ | 22 F2 model tests: 8 Asset, 8 Scan, 6 Tenant extension |
| Safety net for modified files | ✅ | `uv run pytest tests/unit -m "not integration"` and `uv run pytest -m "not integration"` passed after PR-A changes |

**TDD Compliance**: 6/6 PR-A tasks have verified evidence.

### Test Layer Distribution

| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 22 PR-A-focused tests | 1 (`tests/unit/test_f2_models.py`) | pytest |
| Integration | 0 new PR-A tests | 0 | available but DB-backed F2 persistence/cascade tests are deferred by design |
| E2E | 0 | 0 | not available |
| **Total** | **22** | **1** | |

### Changed File Coverage

Coverage analysis skipped — no coverage tool is configured for this project.

### Assertion Quality

**Assertion quality**: ✅ All assertions in `tests/unit/test_f2_models.py` verify real model metadata or constructed model behavior. No tautologies, ghost loops, smoke-only checks, or type-only assertions without value assertions were found.

### Quality Metrics

**Linter**: ⚠️ `uv run ruff check <PR-A files>` reported one F401 in a changed file:

```text
tests/conftest.py:30:37: F401 `app.core.database.set_tenant_context` imported but unused
```

This import appears pre-existing, but the file is part of the PR-A diff and will still surface if Ruff is enforced on changed files.

**Type Checker**: ⚠️ `uv run mypy app/modules/assets/models.py app/modules/scans/models.py app/modules/tenants/models.py tests/unit/test_f2_models.py` reported 10 errors:

- 7 pre-existing `app/core/config.py` environment-constructor errors triggered by import graph.
- 3 changed-test helper typing errors in `tests/unit/test_f2_models.py` because helpers accept `type` but access SQLAlchemy-specific `__mapper__` / `__table__` attributes.

Per Strict TDD verify rules, quality metrics are warning-level evidence, not critical failures.

### Spec Compliance Matrix

| Requirement | PR-A scenario/scope | Test / Evidence | Result |
|-------------|---------------------|-----------------|--------|
| `f2-domain-models`: F2 entity tables | Asset table/model schema subset | `TestAssetModel` + live/offline R1 migration | ✅ COMPLIANT for PR-A structural scope |
| `f2-domain-models`: F2 entity tables | Scan table/model schema subset | `TestScanModel` + live/offline R1 migration | ✅ COMPLIANT for PR-A structural scope |
| `f2-domain-models`: Cascading deletes | Asset/Scan FK cascade definition | Static model/migration inspection; R1 live upgrade/downgrade | ✅ COMPLIANT structurally; DB-backed cascade behavior deferred |
| `f2-domain-models`: Tenant isolation | Asset/Scan RLS policy definition | R1 offline SQL and migration source include RLS enablement and policies | ✅ COMPLIANT structurally; DB-backed RLS behavior deferred |
| `f2-domain-models`: Query indexes | Asset tenant index, Scan tenant/asset indexes | R1 offline SQL and migration source include expected indexes | ✅ COMPLIANT |
| `f2-tenant-plan-extension`: Tenant plan columns | Columns/defaults/backfill/downgrade | `TestTenantPlanExtension` + offline/live R1 upgrade/downgrade | ✅ COMPLIANT for database behavior |
| `database-migrations`: R1 chains to main head | `b5e9d8c4a123 -> 8f2c1a4b9d7e` and single head | `uv run alembic heads`, `uv run alembic history`, live `current` | ✅ COMPLIANT |
| `database-migrations`: R1 upgrade succeeds | R1 creates tenant columns + `assets`/`scans` | Offline SQL and live `upgrade head` succeeded | ✅ COMPLIANT |
| `database-migrations`: R1 downgrade reverses PR-A | R1 downgrade returns to `b5e9d8c4a123` | Offline SQL and live `downgrade b5e9d8c4a123` succeeded | ✅ COMPLIANT |
| `database-migrations`: PR-A env registration | `migrations/env.py` imports `Asset` and `Scan` only | Source inspection | ✅ COMPLIANT |
| PR-B requirements/scenarios | Vulnerability, Report, R2 | Not evaluated | ➖ Out of scope for PR-A |

**Compliance summary**: PR-A scoped requirements are compliant. DB-backed F2 persistence/cascade/RLS behavior remains deferred by the accepted design and should be covered in later slices.

### Correctness (Static Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| Asset model | ✅ Implemented | UUID PK, tenant FK cascade, required/optional columns, JSONB metadata, constraints, timestamps |
| Scan model | ✅ Implemented | UUID PK, tenant/asset FK cascade, required/optional columns, JSONB config, constraints, timestamps |
| Tenant plan extension | ⚠️ Implemented with caveat | DB defaults exist; ORM uses `server_default` only, not Python-side `default=` as the design text describes |
| R1 migration | ✅ Implemented | Revision `8f2c1a4b9d7e`, `down_revision = "b5e9d8c4a123"`, assets/scans/tenant columns/indexes/triggers/RLS/grants |
| Unit DB override | ✅ Implemented | `tests/unit/conftest.py` overrides session autouse DB setup with no-op fixture |
| PR-A tests | ✅ Implemented | 22 focused DB-free tests pass |

### Coherence (Design)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| Two-PR split by entity dependency | ✅ Yes | PR-A contains Asset/Scan/tenant/R1 only; PR-B remains pending |
| Controlled manual port, no broad merge | ✅ Yes | Working tree shows direct PR-A files, no PR-B implementation |
| R1 chains from `b5e9d8c4a123` | ✅ Yes | `alembic heads` has single head `8f2c1a4b9d7e` |
| DB-free unit tests for PR-A | ✅ Yes | 22 focused tests passed |
| Tenant defaults: server default + backfill | ✅ Yes | Migration and ORM `server_default` are present |
| ORM-side new-object defaults | ⚠️ Partial | Design says ORM side uses `default=`; implementation only uses `server_default` for new tenant plan fields |

### Issues Found

**CRITICAL**: None.

**WARNING**:

1. `ruff` reports pre-existing unused import `set_tenant_context` in changed `tests/conftest.py`.
2. `mypy` reports 3 changed-test helper typing errors in `tests/unit/test_f2_models.py`; it also reports 7 pre-existing `app/core/config.py` settings-constructor errors.
3. Tenant plan ORM defaults are only database/server defaults. This satisfies DB insert defaults but does not match the design note that ORM-side `default=` should support new-object construction defaults.
4. `Tenant.report_types` is annotated as `dict | None`, while the spec/default value is a JSON array (`["vulnerability"]`). This is a typing/coherence risk even though the database default is correct.
5. Working tree contains untracked items outside the narrow PR-A implementation scope (`.python-version`, `openspec/changes/cleanup-f2-branch-state/`, `openspec/project/`). Commit preparation should stage intentionally.

**SUGGESTION**:

1. Use `uv run ...` for local verification in this environment; bare `pytest` and `alembic` are not on PATH.
2. Keep DB-backed persistence/cascade/RLS tests for the planned later slices, as accepted by the design.
3. If CI enforces Ruff or mypy, address or explicitly defer the warning-level quality findings before opening the PR.

### Verdict

**PASS WITH WARNINGS**

PR-A implementation matches the accepted PR-A scope, tasks 1.1-2.2 are complete, focused and full non-integration tests passed, R1 has a single Alembic head, and live upgrade/downgrade succeeded on the local test PostgreSQL database. Warning-level quality and design-coherence findings should be reviewed before commit/PR, but no critical blocker was found for PR-A verification.

**Ready for pre-PR review / commit preparation**: Yes, with warnings. Stage only intended PR-A files/artifacts and decide whether to clean or defer the Ruff/mypy/ORM-default warnings before opening the PR.
