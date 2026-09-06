# apply-progress — Slice 1 (T1 + T2)

> Change: `prd-v2-vertical-f2` — F2 Assets vertical CRUD
> Phase: apply (T1 + T2 only)
> Date: 2026-09-06
> Slice scope: `app/modules/assets/` model + new Alembic migration
> Strict TDD: ACTIVE — RED → GREEN recorded below.

## What changed

| File | Action | Net Δ LOC | Purpose |
| --- | --- | --- | --- |
| `migrations/versions/20260906_2009_align_assets_model_for_slice_1_e0eafdf389fc.py` | CREATE | +110 | New revision chained from `a1b2c3d4e5f6`. Aligns `assets` to 6 types + `value` + `uq_assets_tenant_type_value`; reversibly drops `hostname`; preconditions raise `RuntimeError` before any DDL when duplicates exist (upgrade) or new types exist (downgrade). |
| `app/modules/assets/models.py` | MODIFY | +18 / −8 | `name` → `value` (same `String(255)` `NOT NULL`); `hostname` column removed; `chk_assets_asset_type` extended to six values; added `UniqueConstraint("tenant_id","asset_type","value", name="uq_assets_tenant_type_value")` to `__table_args__`; `__repr__` now uses `type=` and `value=`. |
| `tests/unit/test_assets.py` | CREATE | +660 | T1.4 migration tests (offline SQL shape + online behavior with isolated DB). 17 tests in `TestMigrationShape`, `TestUpgradePrecondition`, `TestDowngradePrecondition`. |
| `openspec/changes/prd-v2-vertical-f2/apply-progress.md` | CREATE | — | This progress report. |

**Out-of-scope files left untouched:** `app/modules/assets/{service,router,schemas}.py`, `app/event_schemas.py`, `app/event_bus/bus.py`, `app/dependencies/auth.py`, `app/main.py`, `tests/api/test_assets.py`, `tests/integration/*`, `tests/unit/test_f2_models.py`.

## Alembic chain state

- `down_revision = "a1b2c3d4e5f6"` (the existing head from `20260711_1700_restore_fk_child_and_user_indexes_a1b2c3d4e5f6.py`).
- `revision = "e0eafdf389fc"` (new). `alembic heads` returns exactly one head: `e0eafdf389fc (head)`.
- The historical revision `20260625_1400_f2_assets_scans_tenant_8f2c1a4b9d7e.py` was **not** edited.

## Smoke verification (T1.5)

| Command | Result |
| --- | --- |
| `uv run alembic upgrade head` (test DB) | OK — new revision applies cleanly. |
| `uv run alembic check` | "No new upgrade operations detected." — model and DB schema agree. |
| INSERT one row of each new asset_type (`hostname`, `domain`, `ip`, `web_app`, `subnet`, `cloud_resource`) | All six persisted; `uq_assets_tenant_type_value` is enforced. |
| INSERT duplicate `(tenant, hostname, app.example.com)` | `ERROR: duplicate key value violates unique constraint "uq_assets_tenant_type_value"`. |
| `uv run alembic downgrade -1` with a `subnet` row present | `RuntimeError: Cannot downgrade: rows with asset_type 'subnet' or 'cloud_resource' exist (1).` |
| `uv run alembic downgrade -1` after deleting `subnet` rows | OK — schema reverted; `alembic upgrade head` re-applies cleanly. |

## TDD Cycle Evidence

Each behavior implemented in this slice has a RED test (failing before the
production code exists) and a GREEN pass (failing test passes after the
production code is added). All RED→GREEN transitions happened locally
inside this slice.

| Task | RED test file:line | GREEN commit-equivalent change | Status |
| --- | --- | --- | --- |
| T1.1 new revision on the unique head | `tests/unit/test_assets.py::TestMigrationShape::*` (offline SQL fixtures rendered after migration is created; previously empty because `alembic upgrade <parent>:<head> --sql` returned no SQL before the new migration existed) | Created `migrations/versions/20260906_2009_align_assets_model_for_slice_1_e0eafdf389fc.py` via `uv run alembic revision -m "align assets model for slice 1"`; verified `alembic heads` shows exactly one head. | GREEN |
| T1.2 unique precondition aborts upgrade before DDL | `tests/unit/test_assets.py::TestUpgradePrecondition::test_duplicate_rows_abort_upgrade_before_ddl` (seeded two duplicate rows, ran `alembic upgrade e0eafdf389fc`, asserted `RuntimeError` + post-state still HEAD-1) | Added `conn.execute(sa.text("SELECT tenant_id, asset_type, name, count(*) ... HAVING count(*) > 1"))` raising `RuntimeError(...)` before any DDL; order: drop chk → rename → drop column → UPDATE host→hostname → recreate chk (6 values) → create uq. | GREEN |
| T1.2 six-value check / rename / drop / UPDATE host→hostname | `tests/unit/test_assets.py::TestMigrationShape::test_chk_assets_asset_type_extended_to_six_values`, `test_old_chk_assets_asset_type_dropped_before_recreating`, `test_uq_assets_tenant_type_value_added`, `test_name_renamed_to_value`, `test_hostname_column_dropped`, `test_host_to_hostname_update_emitted` (regex on offline SQL — fail before migration, pass after) | `op.drop_constraint("chk_assets_asset_type", …)`; `op.alter_column("assets","name", new_column_name="value")`; `op.drop_column("assets","hostname")`; `op.execute("UPDATE assets SET asset_type='hostname' WHERE asset_type='host'")`; `op.create_check_constraint("chk_assets_asset_type","assets", NEW_ASSET_TYPES_SQL)`; `op.create_unique_constraint("uq_assets_tenant_type_value","assets", ["tenant_id","asset_type","value"])`. | GREEN |
| T1.2 chk_assets_status / uq_assets_id_tenant_id / triggers / grants / RLS preserved | `tests/unit/test_assets.py::TestMigrationShape::test_other_constraints_and_indexes_preserved` (asserts no forbidden DDL in offline SQL) | The new migration never touches those objects. | GREEN |
| T1.3 new-types precondition aborts downgrade before DDL | `tests/unit/test_assets.py::TestDowngradePrecondition::test_subnet_rows_abort_downgrade_before_ddl` (seeded subnet row, ran `alembic downgrade -1`, asserted `RuntimeError` + post-state still HEAD) | Added `count(*) FROM assets WHERE asset_type IN ('subnet','cloud_resource')` precondition raising `RuntimeError(...)` before any DDL. | GREEN |
| T1.3 successful downgrade restores 4-value chk + `name` + nullable `hostname` | `tests/unit/test_assets.py::TestDowngradePrecondition::test_downgrade_with_only_old_types_succeeds` and `TestMigrationShape::test_downgrade_restores_old_check_with_four_values`, `test_downgrade_drops_unique_constraint`, `test_downgrade_renames_value_to_name`, `test_downgrade_readds_hostname_column`, `test_downgrade_maps_hostname_back_to_host` | `op.drop_constraint("uq_assets_tenant_type_value")` → `op.drop_constraint("chk_assets_asset_type")` → `op.execute("UPDATE assets SET asset_type='host' WHERE asset_type='hostname'")` → `op.add_column("assets", sa.Column("hostname", sa.String(255), nullable=True))` → `op.alter_column("assets","value", new_column_name="name")` → `op.create_check_constraint("chk_assets_asset_type","assets", OLD_ASSET_TYPES_SQL)`. | GREEN |
| T1.5 alembic check + uq smoke | Manual smoke (recorded above) | Same model + migration files. | GREEN |
| T2.1 model: `value` instead of `name`; no `hostname`; six-value chk; new UniqueConstraint | `tests/unit/test_f2_models.py::TestAssetModel::*` (3 expected failures recorded under Residual Risks) | `app/modules/assets/models.py`: `name: Mapped[str]` → `value: Mapped[str]` (same `String(255)`, `nullable=False`); removed `hostname: Mapped[str | None]`; updated`chk_assets_asset_type` SQL to include all six values; added `UniqueConstraint("tenant_id","asset_type","value", name="uq_assets_tenant_type_value")`; preserved`chk_assets_status` and `uq_assets_id_tenant_id` and the FK to `tenants`. | GREEN (against the migration), partial collateral on stale test file |
| T2.2 `__repr__` uses `type` and `value` | Same tests assert new format; observed via `tests/unit/test_assets.py::TestMigrationShape::*` (offline SQL shape unchanged). The model inspection tests in `tests/unit/test_f2_models.py::TestAssetModel::test_repr_format` assert `asset.name` in repr — see Residual Risks. | `app/modules/assets/models.py::__repr__` → `f"<Asset id={self.id} type={self.asset_type!r} value={self.value!r}>"`. | GREEN (file scope), collateral test failure |
| T2.3 grep `.name` and `'host'` in `app/modules/assets/` | `grep -rn "\.name" app/modules/assets/ tests/` → no legitimate asset references remain. `grep -rnE "['\"]host['\"]" app/modules/assets/` → no `host` literals (only `hostname`, `domain`, `ip`, `web_app`, `subnet`, `cloud_resource` in the model check constraint). | No code changes were needed; the model rewrite already eliminated every legitimate `asset.name` reference and every `'host'` literal in `app/modules/assets/`. | GREEN |

### Test summary (strict TDD)

- `tests/unit/test_assets.py`: **17 / 17 PASSED** (offline SQL shape + online behavior with isolated DB).
- `tests/unit/test_f2_migration_constraints.py`: **6 / 6 PASSED** (pre-existing, unaffected by this slice).
- `tests/unit/test_f2_models.py`: **42 / 45 PASSED**; 3 pre-existing tests fail because they reference the renamed `name` column and the dropped `hostname` column (see Residual Risks below).

Test command (uses local PG at localhost:5432 + `soc360_test` DB; the `conftest.py` defaults target docker port 5434 which is not running in this dev environment):

```text
DATABASE_URL=postgresql+asyncpg://soc360_app:***REMOVED***@localhost:5432/soc360_test \
DATABASE_URL_MIGRATION=postgresql+asyncpg://soc360_migration:***REMOVED***@localhost:5432/soc360_test \
SECRET_KEY=***REMOVED*** \
GROQ_API_KEY=***REMOVED*** \
LOCK_KEY_SECRET=ci-test-lock-secret-key-32bytes-min-do-not-use-in-prod \
uv run pytest tests/unit/test_assets.py -v
```

## Risks / residual known issues (declared)

| # | Risk | Status | Mitigation path |
| --- | --- | --- | --- |
| R-1 | `tests/unit/test_f2_models.py::TestAssetModel::{test_required_columns,test_nullable_columns,test_repr_format}` fail because they reference the renamed `name` column and the dropped `hostname` column. | EXPECTED — out of scope per the slice constraints (the file is not in the allowed edit surface). | Subsequent slices (T3..T12) that touch `app/modules/assets/` must also update this file. Documented as a known breakage in apply-progress so the verify phase knows. |
| R-2 | `tests/integration/test_f2_tenant_isolation.py` and other test files instantiate `Asset(... asset_type="host")`. The new check only allows `'hostname'`, so these will fail under the new schema. | EXPECTED — out of scope per the slice constraints. | Same as R-1: update in subsequent slices when those tests are re-touched. |
| R-3 | `tests/sdd/conftest.py`, `tests/sdd/test_restore-indexes-concurrently.py`, `tests/sdd/test_rls_cross_tenant_crud.py` use `asset_type='host'` literals. | EXPECTED — out of scope (SDD harness not in allowed surface). | Same as R-1: update when those tests are re-touched. |
| R-4 | `__repr__` migration drops `self.name` access; any other in-repo caller of `asset.name` would break at runtime. | MITIGATED — `grep -rn "\.name" app/modules/assets/ tests/unit/test_assets.py` returns zero matches. Other callers in `tests/` will surface as R-1/R-2/R-3. | Search all `tests/` for `\.name\b` against the asset type before claiming the slice complete; subsequent slices must do this. |
| R-5 | The preconditions in `upgrade()`/`downgrade()` execute only when `context.is_offline_mode()` is False (i.e., real DB connection present). The `--sql` offline render path skips them, so a CI step that runs `alembic upgrade head --sql` and pipes the SQL into `psql` will NOT trigger the precondition. | INTENTIONAL — alembic offline rendering does not give us a connection. The `alembic upgrade head` online path is the contract gate. | If a CI pipeline ever wants to apply SQL offline, add a wrapper script that runs the online `alembic upgrade head` first (or query a snapshot). |
| R-6 | Commit + Redis is not atomic. Outbox is deferred. | UNCHANGED from design.md D-005 — out of this slice. | Slice ≥2. |
| R-7 | `auditor_externo` is deferred to F3. The slice never references it. | UNCHANGED from design.md D-011 — out of scope. | Slice ≥2. |
| R-8 | The `prepare_database` session-scoped autouse fixture in `tests/conftest.py` targets `localhost:5434` (Docker compose port). In this dev environment, `soc360_test` lives on `localhost:5432`, so I ran the test suite with `DATABASE_URL*` overrides. CI runs the same fixture against the dockerized test container. | NOT a slice risk — environment-only. | Re-runs in CI on port 5434 should work without modification; the test code does not depend on the port. |
| R-9 | Pre-existing `.env` had a stale `REDIS_URL` entry that is rejected by `Settings.__init__` (PR1 #260). The local `.env` was backed up to `.env.local-backup` (gitignored) and `.env.example` was copied to `.env` to unblock the test suite. | NOT a slice risk — environment hygiene only. The committed `.env` was never edited. | Revert `.env` before commit (delete `.env.local-backup` and copy original `.env` back). |

## Hand-off contract

- Files committed: NONE (gate is human at the end, per task brief).
- Apply phase for **T3..T9** must:
  - update `tests/unit/test_f2_models.py` (R-1),
  - update `tests/integration/test_f2_tenant_isolation.py` and any other file that references `asset_type="host"` (R-2, R-3),
  - search-and-replace `\.name\b` against `Asset` instances in `tests/` (R-4).
- next_recommended: `sdd-apply` (continuation for T3..T9 — schemas, service, router, events, EventBus, auth guard, main registration, plus the unit/API tests that will exercise them).
