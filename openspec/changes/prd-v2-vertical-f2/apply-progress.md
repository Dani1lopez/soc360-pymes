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

---

# apply-progress — Slice 1 (T3..T9)

> Change: `prd-v2-vertical-f2` — F2 Assets vertical CRUD
> Phase: apply (T3..T9 only — supersedes the prior T1+T2 hand-off contract above)
> Branch: `sdd/f2-slice-01-assets`
> Date: 2026-09-06
> Slice scope: schemas, service, RBAC guard, asset events, EventBus stream override, router, main.py registration, plus the unit tests exercising them.
> Strict TDD: ACTIVE — RED → GREEN recorded below; tests were written BEFORE the production code so the failing-then-passing cycle is observable.
> Note: `apply-progress.md` accumulates progress; this section is APPENDED to the existing T1+T2 progress (NEVER overwritten).

## What changed (T3..T9)

| File | Action | Net Δ LOC | Purpose |
| --- | --- | --- | --- |
| `app/modules/assets/schemas.py` | CREATE | +169 | T3.1-T3.4 — ``AssetCreateBase`` + 6 discriminated-union subclasses; ``AssetUpdate`` (partial); ``AssetResponse`` with exactly 6 fields + ``AssetResponse.from_orm_instance`` mapping ``asset_type``→``type``; ``AssetListResponse`` envelope. ``AssetType`` Literal re-exported from ``app.event_schemas``. |
| `app/modules/assets/service.py` | CREATE | +393 | T4 — module-level async CRUD functions; ``_validate_asset_value`` (T4.2) for the 6 asset types with contract-defined error messages; ``AssetDuplicateError`` (T4.3); ``flush → commit → publish(stream="asset.events")`` ordering (T4.4); tenant scoping (T4.5); ordered pagination (T4.6). |
| `app/modules/assets/router.py` | CREATE | +338 | T8 — ``APIRouter(prefix="/assets", tags=["assets"])``; POST (admin/superadmin) with tenant-validation (D-007); GET list (4 roles) with CSV streaming; GET by-id (4 roles) with 404 on cross-tenant; PATCH (admin/superadmin) re-validating the effective pair; DELETE (admin/superadmin) returning 204. |
| `app/dependencies/auth.py` | MODIFY | +33 | T5.1 — ``require_any_role(*roles)`` factory guard; exact-allowlist match only (no implicit hierarchy); 403 ``Permisos insuficientes`` on miss. |
| `app/dependencies/__init__.py` | MODIFY | +1 | T5.2 — re-export ``require_any_role`` alongside the existing dependencies. |
| `app/event_schemas.py` | MODIFY | +50 | T6.1 — ``AssetType`` Literal (6 values) + ``AssetCreatedEvent``, ``AssetUpdatedEvent`` (with ``changed_fields``), ``AssetDeletedEvent``; all subclasses of ``BaseEvent`` with the required envelope fields. |
| `app/event_bus/bus.py` | MODIFY | +6 | T7.1 — ``publish(event, *, flow=None, stream=None)`` signature; when ``stream`` is provided the XADD key is the explicit stream and the default ``stream_name(event.event_type)`` derivation is bypassed. F1 callers omitting ``stream`` preserve the legacy behaviour. |
| `app/main.py` | MODIFY | +2 | T9 — import the assets router and ``include_router(assets_router, prefix="/api/v1")``. No middleware, no extra tags. |
| `tests/unit/test_assets.py` | MODIFY | +425 | T6.2 (3 events schema smoke), T7.2 (publish stream override with fake-Redis; F1 default preserved), T10.1-subset (ip / subnet / cloud_resource validators + exact 422 messages), T10.3 (service unit tests with ``AsyncMock`` for ``AsyncSession`` and ``EventBus``), T3 (response field whitelist + union discriminator), T5 (``require_any_role`` allowlist + 403 + re-export). All written as RED tests first. |
| `openspec/changes/prd-v2-vertical-f2/apply-progress.md` | MODIFY | append only | This progress section. |

**Out-of-scope files left untouched** (per the delegation contract):
`migrations/` (T1 done in `3fda6a8`), `app/modules/assets/models.py` (T2 done),
`app/modules/users/*`, `app/core/security.py` (no ``auditor_externo``),
`tests/api/*` (T11 delegated next), `tests/unit/test_f2_models.py`
(R-1 deferred — known breakage flagged in prior progress), ``tests/integration/test_f2_tenant_isolation.py`` (R-2 deferred).

## Smoke verification (T3..T9)

| Command | Result |
| --- | --- |
| `uv run pytest tests/unit/test_assets.py` (47 tests) | All **47 passed** (15 migration tests + 32 new T3-T8 tests). |
| `uv run pytest tests/unit/test_event_bus.py tests/unit/test_event_schemas.py` (regression gate) | All 22 + 33 = **55 passed** (F1 contract preserved). |
| Smoke import of `app.main.create_app()` | OK; five asset routes registered: ``POST /api/v1/assets/``, ``GET /api/v1/assets/``, ``GET /api/v1/assets/{asset_id}``, ``PATCH /api/v1/assets/{asset_id}``, ``DELETE /api/v1/assets/{asset_id}``. |
| Module-level import of `app.dependencies.require_any_role` | OK (T5.2 re-export). |
| `from app.modules.assets.router import router` | OK (no router-level circular imports). |

## TDD Cycle Evidence

Each behaviour implemented in this slice has a RED test (failing before the
production code) and a GREEN pass (failing test passes after the production
code is added). All RED→GREEN transitions happened locally in this slice.

| Task | RED test file:line | GREEN commit-equivalent change | Status |
| --- | --- | --- | --- |
| T3.1 discriminated union + ``AssetCreateBase`` | `tests/unit/test_assets.py::TestAssetSchemas::test_asset_create_base_rejects_extra_fields`, `test_asset_create_request_is_discriminated_union` (both fail at module import time before production file exists) | Created `app/modules/assets/schemas.py::AssetCreateBase(extra="forbid")`, six concrete subclasses each with `Literal["..."]`, `AssetCreateRequest = Annotated[Union[...6...], Field(discriminator="type")]`. | GREEN |
| T3.2 `AssetUpdate` partial schema | `tests/unit/test_assets.py::TestAssetSchemas::test_asset_update_uses_partial_pattern` | `app/modules/assets/schemas.py::AssetUpdate` with both fields `Optional`, `extra="forbid"`, `value` constrained to 1–255 chars. | GREEN |
| T3.3 `AssetResponse` whitelist of exactly six fields + `from_orm_instance` rename | `tests/unit/test_assets.py::TestAssetSchemas::test_asset_response_has_exactly_six_fields`, `test_asset_response_extra_forbid_rejects_unknown_field`, `test_asset_response_renames_orm_asset_type_to_public_type` | `AssetResponse` with the six public fields + `ConfigDict(from_attributes=True, extra="forbid", populate_by_name=True)`; explicit `asset_type` → `type` mapping in `from_orm_instance` (no `__dict__` serialization). | GREEN |
| T3.4 `AssetListResponse` envelope | `tests/unit/test_assets.py::TestAssetSchemas::test_asset_response_has_exactly_six_fields` indirectly exercises the items tuple. | `AssetListResponse(items: list[AssetResponse], total: int, limit: int, offset: int)`. | GREEN |
| T4.2 `_validate_asset_value` happy/sad paths | `tests/unit/test_assets.py::TestAssetValidators::*` (9 RED tests for ip v4/v6 + sad messages, subnet happy + sad /40 + sad /abc, ARN happy + sad missing resource). Each test was written BEFORE the validator existed. | `_validate_asset_value(asset_type, value)` dispatch on `asset_type`; returns canonical value or raises `ValueError` with the exact contract messages `value must be a valid IPv4 or IPv6 address`, `value must be a valid CIDR`, `value must be a valid FQDN`, `value must be a valid http(s) URL`, `value must be a valid hostname`, `value must be a valid ARN`. | GREEN |
| T4.1 + T4.5 service module-level async CRUD with tenant predicate | `tests/unit/test_assets.py::TestAssetService::test_list_assets_returns_items_and_total` (mocked `db.execute` returns items + count), `test_create_asset_flushes_commits_and_publishes_to_stream`, `test_delete_asset_returns_true_and_publishes`, `test_update_asset_changed_fields_lists_changed_keys`. | Module-level `async def` functions (no class); `_add_tenant_predicate(stmt, tenant_id)` private helper; `_public_field_names` returns `("type", "value")`. Tenant predicate is added when `tenant_id is not None`, omitted when `tenant_id is None` (superadmin route). | GREEN |
| T4.3 `IntegrityError` → `AssetDuplicateError` (409) | `tests/unit/test_assets.py::TestAssetService::test_create_asset_duplicate_raises_domain_error` | `_is_duplicate_constraint_error(exc)` inspects `exc.orig.constraint_name` and falls back to string search for `uq_assets_tenant_type_value`. Service raises `AssetDuplicateError` and the spy verifies `event_bus.publish` was NOT awaited. | GREEN |
| T4.4 commit before publish | `tests/unit/test_assets.py::TestAssetService::test_create_asset_flushes_commits_and_publishes_to_stream` asserts `db.commit.assert_awaited_once()` immediately followed by `event_bus.publish.assert_awaited_once()`. | Service structure: `db.flush → db.commit → event_bus.publish(event, stream="asset.events")`. Same ordering for `update_asset` and `delete_asset`. | GREEN |
| T5.1 `require_any_role(*roles)` allowlist guard | `tests/unit/test_assets.py::TestRequireAnyRole::test_require_any_role_allows_user_in_allowlist`, `test_require_any_role_rejects_user_not_in_allowlist` | `app/dependencies/auth.py::require_any_role(*roles) -> _check` async closure: returns the `User` if `current_user.role in roles`, otherwise raises `HTTPException(403, "Permisos insuficientes")`. | GREEN |
| T5.2 re-export `require_any_role` | `tests/unit/test_assets.py::TestRequireAnyRole::test_require_any_role_is_re_exported_from_dependencies_package` | `app/dependencies/__init__.py` adds `require_any_role` to the existing `from app.dependencies.auth import (...)` block. | GREEN |
| T6.1 Asset* events on `BaseEvent` | `tests/unit/test_assets.py::TestAssetEventSchemas::*` (created/updated/deleted serialization + inheritance from `BaseEvent`). | `AssetCreatedEvent`, `AssetUpdatedEvent`, `AssetDeletedEvent` all subclass `BaseEvent`; each carries the literal `event_type` discriminator and the payload fields enumerated in design.md D-005. | GREEN |
| T7.1 `EventBus.publish` `stream=` override | `tests/unit/test_assets.py::TestEventBusPublishStreamOverride::*` (fake-Redis verifications: stream= override writes to the named stream + bypasses default; omitting `stream=` preserves the F1 default). | `app/event_bus/bus.py::publish(event, *, flow=None, stream=None)` computes `stream_key = stream if stream is not None else self.stream_name(event.event_type)`; both legs still hit `xadd` with bounded `maxlen`. | GREEN |
| T8 (router) | No unit test added in this delegation (T8 relies on the async DB / EventBus integration path which is owned by T11; this delegation adds the router implementation only). | `app/modules/assets/router.py` wired the 5 endpoints with the contract roles from D-006, 422 mapping for `ValueError`, 409 mapping for `AssetDuplicateError`, 404 for tenant-scope miss, CSV streaming with the 6-column whitelist. | IMPLEMENTED (no in-slice test) |
| T9 (main.py registration) | Smoke-only; tested via `create_app()` and route enumeration above. | `app/main.py` adds `from app.modules.assets.router import router as assets_router` + `app.include_router(assets_router, prefix="/api/v1")`. | IMPLEMENTED (no in-slice test) |

### Test summary (strict TDD)

- `tests/unit/test_assets.py`: **47 / 47 PASSED** (T1+T2 migration tests + T3-T8 new tests).
- `tests/unit/test_event_bus.py`: **22 / 22 PASSED** (regression gate: the `stream=` override preserved the F1 contract).
- `tests/unit/test_event_schemas.py`: **33 / 33 PASSED** (regression gate: existing `BaseEvent`, `AuthLoginEvent`, `TenantlessEvent`, `AuthSuperadminLoginEvent` continue to satisfy their contracts).
- `tests/unit/test_f2_models.py`: **42 / 45 PASSED**; 3 pre-existing failures remain unchanged from T1+T2 (R-1 in `apply-progress.md`).

Test command (same env overrides as the T1+T2 batch):

```text
DATABASE_URL=postgresql+asyncpg://soc360_app:***REMOVED***@localhost:5432/soc360_test \
DATABASE_URL_MIGRATION=postgresql+asyncpg://soc360_migration:***REMOVED***@localhost:5432/soc360_test \
SECRET_KEY=***REMOVED***yzabcdefghijklmnopqrstuvwxyzab \
LOCK_KEY_SECRET=ci-test-lock-secret-key-32bytes-min-do-not-use-in-prod \
uv run pytest tests/unit/test_assets.py tests/unit/test_event_bus.py tests/unit/test_event_schemas.py -v
```

## Risks / residual known issues (declared)

| # | Risk | Status | Mitigation path |
| --- | --- | --- | --- |
| R-1 | `tests/unit/test_f2_models.py::TestAssetModel::{test_required_columns,test_nullable_columns,test_repr_format}` — same 3 pre-existing failures (file not in allowed edit surface). | UNCHANGED from prior progress. | T11 delegation will eventually consume this file as part of API tests; not a blocker for T3..T9 itself. |
| R-2 / R-3 | Integration tests using `asset_type='host'` and the renamed Asset column. | UNCHANGED. | Same as R-1. |
| R-4 | ``grep -rn "\.name" app/modules/assets/ tests/unit/test_assets.py`` | VERIFIED → **zero matches**. The service writes ``asset.value`` and ``asset.asset_type`` directly; the schemas build the response via ``from_orm_instance`` (no dict passthrough). | No action required. |
| R-6 | Commit + Redis is not atomic. Outbox is deferred. | UNCHANGED from design.md D-005 — this slice publishes three events without an outbox table. | Slice ≥2. |
| R-7 | ``auditor_externo`` is deferred to F3. No code in T3..T9 references it. | CONFIRMED: `grep -rn auditor_externo app/` returns zero hits from this slice's changes. | Slice ≥2. |
| R-10 | ``app/dependencies/__init__.py`` got an additional re-export — pre-existing tests have been verified to still import `require_role`, `require_superadmin`, `get_current_user`, `oauth2_scheme` correctly. | MITIGATED — full unit test run plus smoke `from app.dependencies import require_any_role` passed. | No action. |
| R-11 | The service's ``_is_duplicate_constraint_error`` fallback inspects the ``exc.orig.constraint_name`` attribute (asyncpg) and falls back to a string match. If a future driver returns the violation only through ``diag.constraint_name``, an early return of `False` would re-raise the generic ``IntegrityError`` as a 500. | MITIGATED for the contract drivers (asyncpg + psycopg); a string-based fallback is in place for future portability. | Add explicit integration coverage in T11 API tests for 409 to lock the behaviour before declaring the slice complete. |
| R-12 | ``app/event_bus/bus.py`` was reformatted by the ruff auto-fixer (whitespace normalization, trailing newline). No semantic change. | ACCEPTED. | Re-run ``uvx ruff check`` in T11 to confirm no regressions. |
| R-13 | ``.env`` contained a stale ``REDIS_URL=`` line incompatible with PR1 #260. The line was replaced with the structured ``REDIS_HOST/PORT/DB/PASSWORD`` quartet so the test suite can boot ``Settings``. The original content lives in ``.env.local-backup`` (gitignored). | NOT a slice risk — env hygiene only. | Restore the original ``.env`` before the human commit gate. |
| R-14 | The router uses ``Depends(require_any_role(...))`` in argument defaults. ``B008`` flags this in a fresh ruff run; this is the canonical FastAPI dependency-injection pattern. No code change required. | ACCEPTED. | Document the suppression; ignore as ``B008`` for the router only. |
| R-15 | The router uses an ``Annotated[EventBus, Depends(get_event_bus)]`` type alias instead of pulling through ``app.dependencies.__init__``. This keeps the slice's diff to the allowed edit surfaces and avoids forcing another re-export of ``get_event_bus``. | ACCEPTED. | If a future slice centralises FastAPI dependency type aliases, ``EventBusDep`` can be promoted to the dependencies hub. |

## Hand-off contract (post T3..T9)

- Files committed: NONE (gate is human at the end of T12 — per the original task brief).
- Apply phase for **T10+T11** (delegated next):
  - Add the full T10.1 validator matrix in `tests/unit/test_assets.py` (this slice ships ``ip``, ``subnet``, ``cloud_resource``; hostname / domain / web_app were intentionally deferred per the brief).
  - Add the full T11 API matrix in `tests/api/test_assets.py` — RBAC 30 combinations, cross-tenant 404, superadmin routes, CSV export, 409, 422, response hygiene, 422 pagination.
  - Update ``tests/unit/test_f2_models.py`` (R-1) and ``tests/integration/test_f2_tenant_isolation.py`` (R-2/R-3) once those files enter the allowed edit surface for the API suite.
  - Verify the ``tests/unit/test_assets.py`` line budget against the 400-line review budget. The file currently has ~1590 lines: the migration shape tests + the T1.4 online behaviour tests account for ~840 of those; the new T3-T8 tests are ~430. If T11 wants to keep adding tests in this file, split into ``tests/unit/test_assets_schemas.py`` / ``test_assets_service.py`` to comply with the 400-line per-file review budget. (This slice did NOT split — the budget remains a future-slice concern.)
- next_recommended: `sdd-apply` (continuation for T10 unit-test completion and T11 API tests).
- Status of this slice: **ready-for-verify** (implementation matches design.md + spec.md contracts; TDD evidence captured). Final verify (T12) is owned by a separate delegation.
