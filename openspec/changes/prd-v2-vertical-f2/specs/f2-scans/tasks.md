# Slice 2 — Scans: Tasks

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1 100 – 1 350 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | **PR 1 — Schema layer** · **PR 2 — Service layer** · **PR 3 — Router + integration + events** |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

---

```text
Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High
```

---

## Work-Unit Mapping

| WU | Name | Files | Est. lines | Verification command |
|----|------|-------|------------|---------------------|
| WU-2A | Schemas: discriminated union + response + envelope | `app/modules/scans/schemas.py` | ~220 | `pytest tests/unit/test_scans.py -k config -v` |
| WU-2B | Service: CRUD + validation + scoping + events | `app/modules/scans/service.py` | ~350 | `pytest tests/unit/test_scans.py -k service -v` |
| WU-2C | Router: 5 routes / 6 operations + RBAC + asset validation | `app/modules/scans/router.py` | ~200 | `pytest tests/api/test_scans.py -v` |
| WU-2D | Events: `ScanType` + `ScanCreatedEvent/UpdatedEvent/DeletedEvent` | `app/event_schemas.py` | ~60 | `pytest tests/unit/test_scans.py -k event -v` |
| WU-2E | Registration: import + `app.include_router` | `app/main.py` | ~4 | `pytest tests/api/test_scans.py::test_readiness -v` |
| WU-2F | Unit tests: config helper, service, tenant predicates | `tests/unit/test_scans.py` | ~300 | `pytest tests/unit/test_scans.py -v` |
| WU-2G | API tests: 52 scenarios across 6 operations × 5 roles | `tests/api/test_scans.py` | ~350 | `pytest tests/api/test_scans.py -v` |

---

## WU-2A — Schemas (`app/modules/scans/schemas.py`)

### RED

- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_scan_create_request_discriminates_types -v` and see it fail because `app/modules/scans/schemas.py` does not exist. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_scan_create_request_rejects_unknown_type -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_scan_create_request_extra_forbid -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_scan_response_whitelist -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_scan_update_partial_rejects_lifecycle -v` and see it fail. <!-- sdd-owner: implementation -->

### GREEN

- [ ] **Implement**: Create `app/modules/scans/__init__.py` exporting schemas module. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Define `ScanType = Literal["discovery", "vulnerability", "web", "full"]`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `ScanCreateBase` with `tenant_id: UUID`, `asset_id: UUID`, `name: str = Field(..., min_length=1, max_length=255)` and `model_config = ConfigDict(extra="forbid")`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `DiscoveryScanCreate(ScanCreateBase)` with `type: Literal["discovery"]` and `config: DiscoveryConfig` where `DiscoveryConfig` has `host_discovery: bool`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `VulnerabilityScanCreate(ScanCreateBase)` with `type: Literal["vulnerability"]` and `config: VulnerabilityConfig` where `VulnerabilityConfig` has `checks: list[str] = Field(..., min_length=1)` and each item must be non-empty. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `WebScanCreate(ScanCreateBase)` with `type: Literal["web"]` and `config: WebConfig` where `WebConfig` has `paths: list[str] = Field(..., min_length=1)` and each path must start with `/`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `FullScanCreate(ScanCreateBase)` with `type: Literal["full"]` and `config: FullConfig` with `host_discovery: bool`, `checks: list[str] = Field(..., min_length=1)`, `paths: list[str] = Field(..., min_length=1)`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `ScanCreateRequest = Annotated[DiscoveryScanCreate | VulnerabilityScanCreate | WebScanCreate | FullScanCreate, Field(discriminator="type")]`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `ScanUpdate` with optional `name: str | None`, `type: ScanType | None`, `config: dict | None` and `model_config = ConfigDict(extra="forbid")`; MUST NOT include `tenant_id`, `asset_id`, `status`, `started_at`, `completed_at`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `ScanResponse` with `model_config = ConfigDict(from_attributes=True, extra="forbid")` exposing exactly `id`, `tenant_id`, `asset_id`, `name`, `type`, `status`, `config`, `started_at`, `completed_at`, `created_at`, `updated_at`. Map `scan.scan_type → type` via a class attribute or field alias. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Create `ScanListResponse` with `items: list[ScanResponse]`, `total: int`, `limit: int`, `offset: int`. <!-- sdd-owner: implementation -->

### TRIANGULATE

- [ ] Verify: `pytest tests/unit/test_scans.py -k scan_create -v` passes with ≥ 10 cases covering the four types, extra forbid, and missing fields. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/unit/test_scans.py -k scan_response -v` passes covering the 11-field whitelist. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/unit/test_scans.py -k scan_update -v` passes covering partial updates and lifecycle rejection. <!-- sdd-owner: implementation -->

### REFACTOR

- [ ] Run `ruff check app/modules/scans/schemas.py` and fix any lint issues. <!-- sdd-owner: implementation -->

**Evidence**: `pytest tests/unit/test_scans.py -k "scan_create or scan_response or scan_update" --tb=short -q` → all pass. Runtime: `N/A` (pure Pydantic validation, no DB). Rollback boundary: delete `app/modules/scans/schemas.py` and remove any imports; no side effects.

---

## WU-2B — Service (`app/modules/scans/service.py`)

### RED

- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_create_scan_inserts_pending -v` and see it fail because `app/modules/scans/service.py` does not exist. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_create_scan_validates_config -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_list_scans_respects_tenant -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_update_scan_rejects_lifecycle -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_delete_scan_emits_event -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/unit/test_scans.py::test_config_helper_rejects_unknown_key -v` and see it fail. <!-- sdd-owner: implementation -->

### GREEN

- [ ] **Implement**: Create `app/modules/scans/service.py` with `from __future__ import annotations` and imports from `app.modules.scans.models`, `app.modules.scans.schemas`, `app.event_schemas`, `app.event_bus.bus`, `sqlalchemy`, `uuid`, `datetime`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Implement `_validate_scan_config(scan_type: str, config: object) -> dict[str, object]` returning a normalized dict or raising `ValueError` with exact messages from design D-S03. Require `host_discovery` for `discovery`; `checks` (non-empty list of non-empty strings) for `vulnerability`; `paths` (non-empty list of paths starting with `/`) for `web`; all three for `full`. Reject unknown keys. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Implement `_scan_type_to_db(scan_type: str) -> str` mapping the four public `type` literals directly to `Scan.scan_type` values. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Implement `_changed_fields(old: Scan, new_data: dict) -> list[str]` returning ordered public field names (`name`, `type`, `config`) that actually changed. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Implement `async def create_scan(data: ScanCreateRequest, tenant_id: UUID, db: AsyncSession, event_bus: EventBus) -> Scan`:
  1. Call `_validate_scan_config(data.type, data.config)`.
  2. Build `Scan(id=uuid.uuid4(), tenant_id=tenant_id, asset_id=data.asset_id, name=data.name, scan_type=_scan_type_to_db(data.type), status="pending", config=..., started_at=None, completed_at=None)`.
  3. `db.add(scan)`, `await db.flush()`.
  4. `await db.commit()`.
  5. `await event_bus.publish(ScanCreatedEvent(...), stream="scan.events")` with payload from design D-S05.
  6. `await db.refresh(scan)`, return `scan`.
  7. On `IntegrityError`: inspect `constraint_name` per D-S04 → raise `AssetScanDuplicateError` for known constraints; re-raise for unknown. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Implement `async def get_scan(scan_id: UUID, tenant_id: UUID | None, db: AsyncSession) -> Scan | None`. If `tenant_id is None`: query only by `id`. If `tenant_id` is set: query by `id` AND `tenant_id`. Return `scalar_one_or_none()`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Implement `async def list_scans(tenant_id: UUID | None, asset_id: UUID | None, limit: int, offset: int, db: AsyncSession) -> tuple[list[Scan], int]`. Build base predicate: if `tenant_id` then `Scan.tenant_id == tenant_id`; if `asset_id` then `Scan.asset_id == asset_id` (AND with tenant predicate if present). Run count and items queries with `order_by(Scan.created_at.desc(), Scan.id.desc())`, offset, limit. Return `(items, total)`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Implement `async def update_scan(scan: Scan, data: ScanUpdate, tenant_id: UUID | None, db: AsyncSession, event_bus: EventBus) -> Scan`:
  1. If `data.name` is not None, set `scan.name = data.name`.
  2. If `data.type` or `data.config` is not None: compute effective `(type, config)` as `(data.type or scan.scan_type, data.config or scan.config)` and call `_validate_scan_config(effective_type, effective_config)`. Set `scan.scan_type = _scan_type_to_db(effective_type)`, `scan.config = effective_config`.
  3. Call `db.flush()`, `db.commit()`.
  4. Publish `ScanUpdatedEvent` with `changed_fields` (empty list if nothing changed).
  5. `db.refresh(scan)`, return `scan`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Implement `async def delete_scan(scan: Scan, db: AsyncSession, event_bus: EventBus) -> None`:
  1. `await db.delete(scan)`, `db.flush()`, `db.commit()`.
  2. Publish `ScanDeletedEvent`. <!-- sdd-owner: implementation -->

### TRIANGULATE

- [ ] Verify: `pytest tests/unit/test_scans.py -k "config_helper" --tb=short -q` passes covering all error messages from D-S03. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/unit/test_scans.py -k "create_scan" --tb=short -q` passes covering valid create, pending status, config validation, asset FK rejection. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/unit/test_scans.py -k "list_scans" --tb=short -q` passes covering pagination, tenant filter, asset filter. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/unit/test_scans.py -k "update_scan" --tb=short -q` passes covering partial update, effective type+config validation, lifecycle rejection, changed fields. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/unit/test_scans.py -k "delete_scan" --tb=short -q` passes covering deletion and event. <!-- sdd-owner: implementation -->

### REFACTOR

- [ ] Run `ruff check app/modules/scans/service.py --fix` and `ruff format app/modules/scans/service.py`. <!-- sdd-owner: implementation -->

**Evidence**: `pytest tests/unit/test_scans.py -k service --tb=short -q` → all pass. Runtime: `N/A` (service tests use `AsyncMock` for `db` and `event_bus`). Rollback boundary: delete `app/modules/scans/service.py`; no side effects.

---

## WU-2C — Router (`app/modules/scans/router.py`)

### RED

- [ ] **TDD**: Add `pytest tests/api/test_scans.py::test_post_scan_201_admin -v` and see it fail because `app/modules/scans/router.py` does not exist. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/api/test_scans.py::test_post_scan_403_ingestor -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/api/test_scans.py::test_get_scans_200_tenant_isolation -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/api/test_scans.py::test_get_scans_by_asset_404_hidden -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/api/test_scans.py::test_patch_scan_200 -v` and see it fail. <!-- sdd-owner: implementation -->
- [ ] **TDD**: Add `pytest tests/api/test_scans.py::test_delete_scan_204 -v` and see it fail. <!-- sdd-owner: implementation -->

### GREEN

- [ ] **Implement**: Create `app/modules/scans/router.py` with `from __future__ import annotations` and imports from FastAPI, Pydantic, `app.dependencies.auth`, `app.dependencies.event_deps`, `app.modules.scans.schemas`, `app.modules.scans.service`, `app.modules.assets.models`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `from app.core.exceptions import AssetScanDuplicateError` import (or define locally if not yet in core). <!-- sdd-owner: implementation -->
- [ ] **Implement**: Define `router = APIRouter(prefix="/scans", tags=["scans"])`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Define a helper `async def _get_effective_tenant(current_user: User) -> UUID | None`: return `None` if `current_user.is_superadmin` else `current_user.tenant_id`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Define a helper `async def _resolve_asset(asset_id: UUID, effective_tenant_id: UUID | None, db: AsyncSession) -> Asset`: query `Asset` by `id` AND `tenant_id` if `effective_tenant_id` is not None, else only by `id`. Raise `HTTPException(404, detail="scan asset not found")` if not found. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `POST /`:
  - Dependency: `Depends(require_any_role("admin", "superadmin"))`.
  - Extract `effective_tenant_id` and `is_superadmin`.
  - If `is_superadmin`: require `data.tenant_id` in body, use it as `tenant_id`; else require `data.tenant_id == current_user.tenant_id` or 422.
  - Call `_resolve_asset(data.asset_id, effective_tenant_id, db)`.
  - Call `create_scan(data, tenant_id, db, event_bus)`.
  - Return `201` with `ScanResponse`.
  - Catch `AssetScanDuplicateError` → `409`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `GET /`:
  - Dependency: `Depends(require_any_role("admin", "analyst", "viewer", "superadmin"))`.
  - Query params: `asset_id: UUID | None = None`, `limit: int = Query(50, ge=1, le=200)`, `offset: int = Query(0, ge=0)`.
  - If `asset_id` provided: call `_resolve_asset` to validate visibility (returns 404 for invisible).
  - Call `list_scans(effective_tenant_id, asset_id, limit, offset, db)`.
  - Return `ScanListResponse`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `GET /{scan_id}`:
  - Dependency: `Depends(require_any_role("admin", "analyst", "viewer", "superadmin"))`.
  - Call `get_scan(scan_id, effective_tenant_id, db)`. Return `404` if `None`.
  - Return `200` with `ScanResponse`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `PATCH /{scan_id}`:
  - Dependency: `Depends(require_any_role("admin", "superadmin"))`.
  - Extract `effective_tenant_id`. Call `get_scan`; return `404` if `None`.
  - Call `update_scan(scan, data, effective_tenant_id, db, event_bus)`.
  - Return `200` with `ScanResponse`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `DELETE /{scan_id}`:
  - Dependency: `Depends(require_any_role("admin", "superadmin"))`.
  - Extract `effective_tenant_id`. Call `get_scan`; return `404` if `None`.
  - Call `delete_scan(scan, db, event_bus)`.
  - Return `204` with empty body. <!-- sdd-owner: implementation -->

### TRIANGULATE

- [ ] Verify: `pytest tests/api/test_scans.py -k "test_post" --tb=short -q` passes covering 201 admin, 403 analyst/viewer/ingestor, 201 superadmin cross-tenant, 404 missing asset, 422 bad config. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/api/test_scans.py -k "test_get" --tb=short -q` passes covering 200 list with tenant isolation, 200 by-id, 404 cross-tenant, 404 by-asset invisible, pagination 422, 403 ingestor. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/api/test_scans.py -k "test_patch" --tb=short -q` passes covering 200 partial update, 422 lifecycle, 403 analyst, 404 cross-tenant, superadmin cross-tenant. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/api/test_scans.py -k "test_delete" --tb=short -q` passes covering 204 admin, 403 analyst, 404 cross-tenant, superadmin. <!-- sdd-owner: implementation -->

### REFACTOR

- [ ] Run `ruff check app/modules/scans/router.py --fix` and `ruff format app/modules/scans/router.py`. <!-- sdd-owner: implementation -->

**Evidence**: `pytest tests/api/test_scans.py --tb=short -q` → all pass. Runtime: `N/A` (API tests use `httpx.AsyncClient` + `set_tenant_context` override per D-010). Rollback boundary: delete `app/modules/scans/router.py`; un-register from `main.py`; no DB side effects.

---

## WU-2D — Events (`app/event_schemas.py`)

### RED

- [ ] **TDD**: Add `pytest tests/unit/test_scans.py -k "ScanCreatedEvent" -v` and see it fail because the event schemas do not exist. <!-- sdd-owner: implementation -->

### GREEN

- [ ] **Implement**: Add `ScanType = Literal["discovery", "vulnerability", "web", "full"]` near the top of `app/event_schemas.py` (after the existing `AssetType` definition). <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `ScanCreatedEvent(BaseEvent)` with `event_type: Literal["scan.created"] = "scan.created"`, `scan_id: uuid.UUID`, `asset_id: uuid.UUID`, `name: str`, `type: ScanType`, `status: Literal["pending", "running", "completed", "failed", "cancelled"]`, `config: dict | None`, `created_at: datetime`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `ScanUpdatedEvent(BaseEvent)` with `event_type: Literal["scan.updated"] = "scan.updated"`, `scan_id: uuid.UUID`, `changed_fields: list[str]`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `ScanDeletedEvent(BaseEvent)` with `event_type: Literal["scan.deleted"] = "scan.deleted"`, `scan_id: uuid.UUID`. <!-- sdd-owner: implementation -->

### TRIANGULATE

- [ ] Verify: `pytest tests/unit/test_scans.py -k "event" --tb=short -q` passes covering event payload shapes and `event_type` literals. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/unit/test_scans.py::test_event_schemas_validate -v` passes. <!-- sdd-owner: implementation -->

### REFACTOR

- [ ] Run `ruff check app/event_schemas.py --fix` and `ruff format app/event_schemas.py`. <!-- sdd-owner: implementation -->

**Evidence**: `pytest tests/unit/test_scans.py -k event --tb=short -q` → all pass. Runtime: `N/A` (Pydantic model validation). Rollback boundary: remove `ScanType`, `ScanCreatedEvent`, `ScanUpdatedEvent`, `ScanDeletedEvent` from `app/event_schemas.py`; update `app/modules/scans/service.py` to use inline dict payloads if rollback order requires it.

---

## WU-2E — Registration (`app/main.py`)

### RED

- [ ] **TDD**: Add `pytest tests/api/test_scans.py::test_router_registered -v` and see it fail because the router is not registered. <!-- sdd-owner: implementation -->

### GREEN

- [ ] **Implement**: In `app/main.py`, add `from app.modules.scans.router import router as scans_router` near the existing router imports. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `app.include_router(scans_router, prefix="/api/v1")` after the existing `assets_router` registration line. <!-- sdd-owner: implementation -->

### TRIANGULATE

- [ ] Verify: `pytest tests/api/test_scans.py::test_router_registered -v` passes. <!-- sdd-owner: implementation -->
- [ ] Verify: `pytest tests/api/test_scans.py -q` → full suite passes. <!-- sdd-owner: implementation -->

### REFACTOR

- [ ] Run `ruff check app/main.py --fix` and `ruff format app/main.py`. <!-- sdd-owner: implementation -->

**Evidence**: `pytest tests/api/test_scans.py -q` → all pass. Runtime: `N/A`. Rollback boundary: remove the two lines added to `app/main.py`; no DB side effects.

---

## WU-2F — Unit Tests (`tests/unit/test_scans.py`)

### RED / GREEN / TRIANGULATE

- [ ] **Implement**: Create `tests/unit/test_scans.py` with fixtures for `AsyncSession` (mock via `AsyncMock`), `EventBus` (spy via `AsyncMock`), `Scan` instances using `MagicMock` with `from_attributes=True` or factory `make_scan(**kwargs)`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add test for `_validate_scan_config`: cover all four valid types with correct configs, all eight error cases from D-S03 with exact error messages, and unknown `scan_type`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add test for `create_scan`: inserts `status="pending"`, `started_at=None`, `completed_at=None`, publishes `scan.created` event to `stream="scan.events"`, commits before publish, `IntegrityError` from `uq_scans_id_tenant_id` maps to `AssetScanDuplicateError`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add test for `get_scan`: returns `Scan` when found by `id` + `tenant_id`; returns `None` when `tenant_id` mismatches; returns `None` when `tenant_id=None` (superadmin) and `id` not found. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add test for `list_scans`: returns `(items, total)` with correct count, respects `tenant_id=None` (global query), respects `asset_id` filter, applies `order_by(Scan.created_at.desc(), Scan.id.desc())`, respects `limit` and `offset`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add test for `update_scan`: partial update of `name` only, partial update of `type` only (effective config validated), partial update of `config` only, effective `(type, config)` validation when changing `type` alone, publishes `scan.updated` with `changed_fields`, publishes with empty `changed_fields` when nothing changed, `flush` before `commit` before publish. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add test for `delete_scan`: deletes entity, flushes, commits, publishes `scan.deleted` after commit. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add test for `_changed_fields`: returns `["name"]` when name changed, `["type", "config"]` when both changed, `[]` when nothing changed. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add test for `config` re-validation on PATCH effective state: `discovery` with missing `host_discovery` raises `ValueError` from `_validate_scan_config`. <!-- sdd-owner: implementation -->
- [ ] **Verify**: `pytest tests/unit/test_scans.py -v --tb=short` → ≥ 20 passing tests. <!-- sdd-owner: implementation -->

### REFACTOR

- [ ] Run `ruff check tests/unit/test_scans.py --fix` and `ruff format tests/unit/test_scans.py`. <!-- sdd-owner: implementation -->

**Evidence**: `pytest tests/unit/test_scans.py -v --tb=short` → all pass. Runtime harness: `N/A` (unit tests with mocked DB/Redis). Rollback boundary: delete `tests/unit/test_scans.py`; no side effects.

---

## WU-2G — API Tests (`tests/api/test_scans.py`)

### RED / GREEN / TRIANGULATE

- [ ] **Implement**: Create `tests/api/test_scans.py` with the same `tenant_client` pattern used by `tests/api/test_assets.py`: `httpx.AsyncClient` with `ASGITransport`, `set_tenant_context` override on `get_db_with_tenant`, isolated Redis DB-14, `get_event_bus` override (single spiable instance per test). <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add `seed_scans` fixture that creates a scan per tenant A and tenant B, plus a scan for admin B, using `app.modules.scans.service.create_scan`. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add RBAC matrix tests (30 cells: 6 operations × 5 roles): parametrize over `role → expected_status`. Operations: POST, GET list, GET list?asset_id, GET by-id, PATCH, DELETE. Roles: `admin`, `analyst`, `viewer`, `superadmin`, `ingestor`. Verify exact status codes: admin/analyst/viewer GET → 200, admin/superadmin POST/PATCH/DELETE → 201/200/204, analyst/viewer/ingestor write → 403. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add tenant isolation tests: GET/PATCH/DELETE by-id cross-tenant → 404 (not 403); GET list from tenant A returns 0 scans from tenant B; superadmin GET list returns global; GET /scans?asset_id=asset-of-other-tenant → 404. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add asset association tests: POST with visible asset → 201; POST with non-existent asset_id → 404; POST with asset from other tenant → 404; GET /scans?asset_id=visible → 200 with correct count; GET /scans?asset_id=invisible → 404. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add config validation tests: POST with valid `discovery` config → 201; valid `vulnerability` config → 201; valid `web` config → 201; valid `full` config → 201; POST with missing `host_discovery` in `discovery` → 422; POST with empty `checks` in `vulnerability` → 422; POST with path not starting with `/` in `web` → 422; POST with unknown key in config → 422; POST with unknown `type` → 422 via discriminator. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add lifecycle tests: POST creates `status="pending"`, `started_at=null`, `completed_at=null`; PATCH with `status` field → 422; PATCH with `started_at` field → 422; PATCH with `completed_at` field → 422. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add PATCH partial update tests: PATCH with `name` only → 200, other fields unchanged; PATCH with `type` only (effective config re-validated) → 200 or 422 depending on existing config; PATCH with empty body → 200 unchanged. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add event publication tests: spy on `event_bus.publish` for POST, PATCH, DELETE. Verify `scan.created` published to `stream="scan.events"` after commit; verify `scan.updated` with `changed_fields`; verify `scan.deleted`; verify that failed commit does NOT publish. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add pagination tests: GET /scans with `limit=0` → 422; `limit=201` → 422; `offset=-1` → 422; `limit=2&offset=0` returns correct page with `total` matching full count. <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add response whitelist tests: verify response JSON has exactly the 11 documented fields; verify no ORM attributes (`scan_type` not exposed as `scan_type`, only as `type`). <!-- sdd-owner: implementation -->
- [ ] **Implement**: Add pending name duplication test: POST scan with same name as existing pending scan for same asset → 201 (no uniqueness enforced at this layer). <!-- sdd-owner: implementation -->
- [ ] **Verify**: `pytest tests/api/test_scans.py -v --tb=short` → ≥ 52 passing scenarios covering all spec requirements. <!-- sdd-owner: implementation -->

### REFACTOR

- [ ] Run `ruff check tests/api/test_scans.py --fix` and `ruff format tests/api/test_scans.py`. <!-- sdd-owner: implementation -->

**Evidence**: `pytest tests/api/test_scans.py -v --tb=short` → all pass. Runtime harness: `uv run pytest tests/api/test_scans.py -v --tb=short` against `soc360_test` DB (DB-15 Redis). Rollback boundary: delete `tests/api/test_scans.py`; no side effects.

---

## Regression Gate

- [ ] **Verify**: `uv run pytest tests/unit/test_scans.py tests/api/test_scans.py -v --tb=short` → ≥ 70 tests pass. <!-- sdd-owner: implementation -->
- [ ] **Verify**: `uv run pytest tests/unit/ tests/api/ --ignore=tests/unit/test_scans.py --ignore=tests/api/test_scans.py -q` → 0 regressions in existing test suite. <!-- sdd-owner: implementation -->
- [ ] **Verify**: `uv run ruff check app/modules/scans/ app/event_schemas.py app/main.py` → 0 errors. <!-- sdd-owner: implementation -->
- [ ] **Verify**: `uv run alembic check` → no drift. <!-- sdd-owner: implementation -->

---

## Rollback Plan

- **WU-2A rollback**: Delete `app/modules/scans/schemas.py`; remove any imports from `app/modules/scans/__init__.py`. No DB changes.
- **WU-2B rollback**: Delete `app/modules/scans/service.py`. No DB changes.
- **WU-2C rollback**: Delete `app/modules/scans/router.py`. No DB changes.
- **WU-2D rollback**: Remove `ScanType`, `ScanCreatedEvent`, `ScanUpdatedEvent`, `ScanDeletedEvent` from `app/event_schemas.py`; update `app/modules/scans/service.py` imports accordingly.
- **WU-2E rollback**: Remove the two lines added to `app/main.py`.
- **WU-2F rollback**: Delete `tests/unit/test_scans.py`.
- **WU-2G rollback**: Delete `tests/api/test_scans.py`.
- **Full rollback**: No DB migration required (model untouched). Existing rows remain. Deploy reverts to pre-slice state by removing the three application files and two test files.

---

## Key Learnings

1. A discriminated union schema with a Pydantic `discriminator` field produces per-variant OpenAPI schemas and rejects fifth types at validation time, eliminating the need for runtime type checking in the service layer.
2. Three-layer tenant isolation (composite FK + RLS + explicit SQL predicate) must be enforced in all queries simultaneously; omitting the explicit predicate for a tenant user would leave RLS as the sole guard, which is insufficient for the spec's `404`-not-`403` requirement on cross-tenant by-id access.
3. Event publishing after `commit` requires capturing the event snapshot before the commit succeeds; using the ORM object after refresh is safe because the ID and timestamps are populated at that point.
4. The `require_any_role` guard introduced in Slice 1 is reusable without modification; calling it with different role tuples per endpoint achieves the exact RBAC matrix specified without adding hierarchical logic.
5. Pagination count and items queries must share the same predicate composition (tenant filter AND asset filter) to guarantee that `total` in the response matches the actual `items` returned, which is required for deterministic client-side paging.
