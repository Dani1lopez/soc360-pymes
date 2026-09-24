"""Slice 2 (F2) — Scans API tests (PR3 part 1: HTTP surface).

Small focused suite proving the scans router is wired into ``create_app()``
and that the RBAC/tenant contract basics hold at the HTTP boundary:

* router registration under ``/api/v1/scans``
* unauthenticated POST is 401
* ``ingestor`` is 403 on every scans operation (before any existence check)
* POST with an asset invisible to the caller is 404 and persists nothing
* POST with a cross-tenant ``tenant_id`` is 422 ``tenant_id mismatch``
* out-of-range pagination is 422

PR3 part 2 (the classes below ``TestRbacMatrix``) completes the FULL
contract matrix at the same HTTP boundary:

* the complete 30-cell RBAC matrix (6 operations x 5 canonical roles)
* tenant isolation (cross-tenant 404s, tenant-scoped lists, superadmin)
* asset association (visible / missing / cross-tenant, immutable identity)
* the per-type config contract with the offending key named in ``detail``
* the read-only lifecycle (``pending`` + null timestamps)
* duplicate open-name 409s, including the partial-predicate release
* pagination limits and ``created_at DESC, id DESC`` ordering
* the exact eleven-field response whitelist
* ``scan.created`` / ``scan.updated`` / ``scan.deleted`` on ``scan.events``
  after the commit, and nothing published when the commit fails.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from app.main import create_app
from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from tests.conftest import TENANT_A_ID, TENANT_B_ID


def _scan_payload(tenant_id: str, asset_id: object | None = None) -> dict:
    """A minimal valid discovery-scan create body."""
    return {
        "tenant_id": tenant_id,
        "asset_id": str(asset_id or uuid4()),
        "name": "api-smoke-scan",
        "type": "discovery",
        "config": {"host_discovery": True},
    }


def test_scans_router_is_registered_under_api_v1() -> None:
    """``create_app()`` must expose the scans collection and by-id routes."""
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/scans/" in paths
    assert "/api/v1/scans/{scan_id}" in paths


@pytest.mark.asyncio
async def test_post_scan_requires_authentication(tenant_client: AsyncClient) -> None:
    """An unauthenticated POST must be rejected with 401."""
    resp = await tenant_client.post(
        "/api/v1/scans/", json=_scan_payload(TENANT_A_ID)
    )
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_ingestor_is_denied_on_every_scans_operation(
    tenant_client: AsyncClient,
    ingestor_a_headers: dict,
) -> None:
    """``ingestor`` is in NO allowlist: 403 on all three read/write verbs.

    The by-id probe uses a random id to prove the denial happens BEFORE any
    existence or tenant check.
    """
    post = await tenant_client.post(
        "/api/v1/scans/",
        headers=ingestor_a_headers,
        json=_scan_payload(TENANT_A_ID),
    )
    assert post.status_code == 403, f"POST expected 403, got {post.status_code}"

    get_list = await tenant_client.get(
        "/api/v1/scans/", headers=ingestor_a_headers
    )
    assert get_list.status_code == 403, (
        f"GET list expected 403, got {get_list.status_code}"
    )

    get_by_id = await tenant_client.get(
        f"/api/v1/scans/{uuid4()}", headers=ingestor_a_headers
    )
    assert get_by_id.status_code == 403, (
        f"GET by-id expected 403, got {get_by_id.status_code}"
    )


@pytest.mark.asyncio
async def test_post_scan_with_an_invisible_asset_is_404_and_persists_nothing(
    tenant_client: AsyncClient,
    admin_a_headers: dict,
    db_session,
) -> None:
    """A POST whose ``asset_id`` does not resolve is 404 and no row is written."""
    invisible_asset_id = uuid4()
    resp = await tenant_client.post(
        "/api/v1/scans/",
        headers=admin_a_headers,
        json=_scan_payload(TENANT_A_ID, asset_id=invisible_asset_id),
    )
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}"
    assert resp.json()["detail"] == "scan asset not found"

    # Nothing persisted — count as superadmin so no RLS predicate can hide a row.
    from app.core.database import set_tenant_context

    await set_tenant_context(db_session, None, True)
    total = (
        await db_session.execute(select(func.count()).select_from(Scan))
    ).scalar_one()
    assert total == 0, f"no scan may be persisted, found {total}"


@pytest.mark.asyncio
async def test_post_scan_with_a_tenant_id_mismatch_is_422(
    tenant_client: AsyncClient,
    admin_a_headers: dict,
) -> None:
    """A tenant user naming another tenant gets 422 ``tenant_id mismatch``."""
    resp = await tenant_client.post(
        "/api/v1/scans/",
        headers=admin_a_headers,
        json=_scan_payload(TENANT_B_ID),
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}"
    assert resp.json()["detail"] == "tenant_id mismatch"


@pytest.mark.asyncio
async def test_list_scans_rejects_out_of_range_pagination(
    tenant_client: AsyncClient,
    admin_a_headers: dict,
) -> None:
    """``limit=0``, ``limit=201`` and ``offset=-1`` are each 422."""
    for query in ("limit=0", "limit=201", "offset=-1"):
        resp = await tenant_client.get(
            f"/api/v1/scans/?{query}", headers=admin_a_headers
        )
        assert resp.status_code == 422, (
            f"?{query} expected 422, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# PR3 part 2 — the full contract matrix
# ---------------------------------------------------------------------------
# Conventions mirrored from tests/api/test_assets.py:
#
# * every test drives the function-scoped ``tenant_client`` fixture, which
#   overrides ``get_db`` / ``get_db_with_tenant`` / ``get_redis`` AND calls
#   ``set_tenant_context`` with the requester's identity, so the RLS
#   predicates match the caller at the HTTP boundary.
# * direct seed/read helpers run under an explicit superadmin RLS context
#   (``set_tenant_context(db, None, True)``) so no row can hide behind RLS
#   and no seed can fail a tenant insert policy.
# * events are observed by wrapping ``publish`` on the SAME ``EventBus``
#   singleton the routes resolve through ``get_event_bus``.

_VALID_CONFIGS: dict[str, dict[str, Any]] = {
    "discovery": {"host_discovery": True},
    "vulnerability": {"checks": ["ssh-login-bruteforce"]},
    "web": {"paths": ["/admin"]},
    "full": {
        "host_discovery": True,
        "checks": ["ssh-login-bruteforce"],
        "paths": ["/admin"],
    },
}

# One required config key removed per scan type.
_MISSING_KEY_CONFIGS: dict[str, dict[str, Any]] = {
    "discovery": {},
    "vulnerability": {},
    "web": {},
    "full": {"host_discovery": True, "checks": ["ssh-login-bruteforce"]},
}

# The required config key each type would miss in ``_MISSING_KEY_CONFIGS``.
_MISSING_KEY_NAME: dict[str, str] = {
    "discovery": "host_discovery",
    "vulnerability": "checks",
    "web": "paths",
    "full": "paths",
}

# The exact eleven-field public whitelist (ScanResponse).
_SCAN_RESPONSE_FIELDS = {
    "id",
    "tenant_id",
    "asset_id",
    "name",
    "type",
    "status",
    "config",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
}


def _typed_scan_payload(
    tenant_id: str,
    asset_id: str,
    scan_type: str,
    config: dict[str, Any],
    name: str = "api-matrix-scan",
) -> dict[str, Any]:
    """A create body for an arbitrary scan ``type`` with its ``config``."""
    return {
        "tenant_id": tenant_id,
        "asset_id": asset_id,
        "name": name,
        "type": scan_type,
        "config": config,
    }


def _detail_text(resp: Any) -> str:
    """The response ``detail`` rendered as text, whatever its JSON shape.

    FastAPI validation errors produce a list of ``{loc, msg, ...}`` dicts,
    while service contract errors produce a plain string; both must name the
    offending key, which is what the matrix asserts on.
    """
    detail = resp.json().get("detail")
    return detail if isinstance(detail, str) else json.dumps(detail)


async def _set_superadmin_context(db_session: AsyncSession) -> None:
    """Bypass RLS for the remainder of the test's outer transaction."""
    await set_tenant_context(db_session, None, True)


async def _seed_asset(
    db_session: AsyncSession,
    value: str,
    tenant_id: str = TENANT_A_ID,
) -> str:
    """Insert one asset directly; return its id as a string."""
    await _set_superadmin_context(db_session)
    asset = Asset(tenant_id=UUID(tenant_id), asset_type="ip", value=value)
    db_session.add(asset)
    await db_session.flush()
    await db_session.commit()
    return str(asset.id)


async def _seed_scan(
    db_session: AsyncSession,
    *,
    asset_id: str,
    name: str,
    tenant_id: str = TENANT_A_ID,
    scan_type: str = "discovery",
    config: dict[str, Any] | None = None,
    status: str = "pending",
    scan_id: UUID | None = None,
    created_at: datetime | None = None,
) -> Scan:
    """Insert one scan row directly, bypassing the API's forced defaults."""
    await _set_superadmin_context(db_session)
    scan = Scan(
        tenant_id=UUID(tenant_id),
        asset_id=UUID(asset_id),
        name=name,
        scan_type=scan_type,
        status=status,
        config=config if config is not None else {"host_discovery": True},
        started_at=None,
        completed_at=None,
    )
    if scan_id is not None:
        scan.id = scan_id
    if created_at is not None:
        scan.created_at = created_at
    db_session.add(scan)
    await db_session.flush()
    await db_session.commit()
    return scan


async def _count_scans(db_session: AsyncSession) -> int:
    """Count ALL scans as superadmin, so no RLS predicate can hide a row."""
    await _set_superadmin_context(db_session)
    total = (
        await db_session.execute(select(func.count()).select_from(Scan))
    ).scalar_one()
    return int(total)


async def _fetch_scan(db_session: AsyncSession, scan_id: str | UUID) -> Scan:
    """Fetch one scan row by id as superadmin (RLS bypass)."""
    await _set_superadmin_context(db_session)
    stmt = select(Scan).where(Scan.id == UUID(str(scan_id)))
    return (await db_session.execute(stmt)).scalar_one()


async def _create_scan_via_api(
    tenant_client: AsyncClient,
    headers: dict,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST a scan and return the decoded 201 body (asserting the 201)."""
    resp = await tenant_client.post("/api/v1/scans/", headers=headers, json=payload)
    assert resp.status_code == 201, (
        f"setup POST expected 201, got {resp.status_code}: {resp.text[:300]}"
    )
    return resp.json()


async def _spy_on_event_bus(
    monkeypatch: pytest.MonkeyPatch,
    sequence: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Wrap ``publish`` on the EventBus singleton the scans routes resolve.

    Returns the recorded publications as dicts with ``event_type``,
    ``stream``, ``changed_fields`` and ``scan_id``. When ``sequence`` is
    given, every observed publish appends ``"publish"`` to it so callers can
    prove commit-before-publish ordering alongside their own commit probe.
    """
    from app.dependencies import event_deps

    bus = await event_deps.get_event_bus()
    calls: list[dict[str, Any]] = []
    original_publish = bus.publish

    async def _spy(event: Any, **kwargs: Any) -> Any:
        calls.append(
            {
                "event_type": getattr(event, "event_type", None),
                "stream": kwargs.get("stream"),
                "changed_fields": getattr(event, "changed_fields", None),
                "scan_id": str(getattr(event, "scan_id", None)),
            }
        )
        if sequence is not None:
            sequence.append("publish")
        return await original_publish(event, **kwargs)

    monkeypatch.setattr(bus, "publish", _spy)
    return calls


# ---------------------------------------------------------------------------
# RBAC — the full 30-cell matrix (6 operations x 5 canonical roles)
# ---------------------------------------------------------------------------
_RBAC_ROLES: tuple[str, ...] = ("viewer", "analyst", "ingestor", "admin", "superadmin")
_RBAC_OPERATIONS: tuple[str, ...] = (
    "POST",
    "GET_LIST",
    "GET_LIST_FILTERED",
    "GET_BY_ID",
    "PATCH",
    "DELETE",
)
_WRITE_ROLES = frozenset({"admin", "superadmin"})
_READ_ROLES = frozenset({"admin", "analyst", "viewer", "superadmin"})


def _expected_rbac_status(operation: str, role: str) -> int:
    """The EXACT status the (operation, role) cell must produce.

    Writes (POST/PATCH/DELETE) allow only ``admin`` and ``superadmin``;
    reads allow ``admin``/``analyst``/``viewer``/``superadmin``; ``ingestor``
    is in no allowlist and is denied on every operation.
    """
    if operation == "POST":
        return 201 if role in _WRITE_ROLES else 403
    if operation == "PATCH":
        return 200 if role in _WRITE_ROLES else 403
    if operation == "DELETE":
        return 204 if role in _WRITE_ROLES else 403
    return 200 if role in _READ_ROLES else 403


_RBAC_CASES: list[tuple[str, str, int]] = [
    (operation, role, _expected_rbac_status(operation, role))
    for operation in _RBAC_OPERATIONS
    for role in _RBAC_ROLES
]
assert len(_RBAC_CASES) == 30, "the RBAC matrix must stay 6 operations x 5 roles"


class TestRbacMatrix:
    """Parametrized 30-cell RBAC matrix: 6 operations x 5 canonical roles.

    Each cell is an individual test reporting its own id
    (``<operation>_<role>_<expected>``) so a regression pinpoints the exact
    cell. The status code is asserted EXACTLY per cell, not merely "not 500".
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "operation,role,expected",
        _RBAC_CASES,
        ids=[f"{op.lower()}_{role}_{expected}" for op, role, expected in _RBAC_CASES],
    )
    async def test_rbac_cell(
        self,
        tenant_client: AsyncClient,
        db_session: AsyncSession,
        admin_a_headers: dict,
        analyst_a_headers: dict,
        viewer_a_headers: dict,
        superadmin_headers: dict,
        ingestor_a_headers: dict,
        operation: str,
        role: str,
        expected: int,
    ) -> None:
        headers = {
            "viewer": viewer_a_headers,
            "analyst": analyst_a_headers,
            "ingestor": ingestor_a_headers,
            "admin": admin_a_headers,
            "superadmin": superadmin_headers,
        }[role]

        asset_id = await _seed_asset(db_session, "192.0.2.7")
        scan_id: str | None = None
        if operation != "POST":
            scan = await _seed_scan(db_session, asset_id=asset_id, name="api-matrix-scan")
            scan_id = str(scan.id)

        if operation == "POST":
            resp = await tenant_client.post(
                "/api/v1/scans/",
                headers=headers,
                json=_scan_payload(TENANT_A_ID, asset_id=asset_id),
            )
        elif operation == "GET_LIST":
            resp = await tenant_client.get("/api/v1/scans/", headers=headers)
        elif operation == "GET_LIST_FILTERED":
            resp = await tenant_client.get(
                f"/api/v1/scans/?asset_id={asset_id}", headers=headers
            )
        elif operation == "GET_BY_ID":
            assert scan_id is not None
            resp = await tenant_client.get(f"/api/v1/scans/{scan_id}", headers=headers)
        elif operation == "PATCH":
            assert scan_id is not None
            resp = await tenant_client.patch(
                f"/api/v1/scans/{scan_id}",
                headers=headers,
                json={"name": "api-matrix-scan-renamed"},
            )
        else:
            assert scan_id is not None
            resp = await tenant_client.delete(
                f"/api/v1/scans/{scan_id}", headers=headers
            )

        assert resp.status_code == expected, (
            f"RBAC cell operation={operation} role={role} expected {expected}, "
            f"got {resp.status_code}: {resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    """Cross-tenant by-id access is 404 (never 403, no existence leak) and
    lists stay scoped to the caller's tenant; superadmin sees every tenant.
    """

    @pytest.mark.asyncio
    async def test_cross_tenant_get_by_id_is_404(
        self,
        tenant_client: AsyncClient,
        admin_b_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.30")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="iso-get")
        resp = await tenant_client.get(
            f"/api/v1/scans/{scan.id}", headers=admin_b_headers
        )
        assert resp.status_code == 404, (
            f"cross-tenant GET MUST be 404, got {resp.status_code}: {resp.text}"
        )
        assert resp.json()["detail"] == "scan not found"

    @pytest.mark.asyncio
    async def test_cross_tenant_patch_is_404(
        self,
        tenant_client: AsyncClient,
        admin_b_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.31")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="iso-patch")
        resp = await tenant_client.patch(
            f"/api/v1/scans/{scan.id}",
            headers=admin_b_headers,
            json={"name": "iso-patch-hijacked"},
        )
        assert resp.status_code == 404, (
            f"cross-tenant PATCH MUST be 404, got {resp.status_code}: {resp.text}"
        )
        # The row MUST be untouched: the 404 must come from scoping, and no
        # partial write may have been applied.
        row = await _fetch_scan(db_session, scan.id)
        assert row.name == "iso-patch"

    @pytest.mark.asyncio
    async def test_cross_tenant_delete_is_404(
        self,
        tenant_client: AsyncClient,
        admin_b_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.32")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="iso-delete")
        resp = await tenant_client.delete(
            f"/api/v1/scans/{scan.id}", headers=admin_b_headers
        )
        assert resp.status_code == 404, (
            f"cross-tenant DELETE MUST be 404, got {resp.status_code}: {resp.text}"
        )
        # The scan must still exist after the denied delete.
        row = await _fetch_scan(db_session, scan.id)
        assert row.id == scan.id

    @pytest.mark.asyncio
    async def test_list_returns_only_own_tenant_rows_in_items_and_total(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_a = await _seed_asset(db_session, "192.0.2.33")
        asset_b = await _seed_asset(db_session, "192.0.2.34", tenant_id=TENANT_B_ID)
        scan_a1 = await _seed_scan(db_session, asset_id=asset_a, name="iso-a1")
        scan_a2 = await _seed_scan(db_session, asset_id=asset_a, name="iso-a2")
        await _seed_scan(
            db_session,
            asset_id=asset_b,
            name="iso-b1",
            tenant_id=TENANT_B_ID,
        )

        resp = await tenant_client.get("/api/v1/scans/", headers=admin_a_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2, (
            f"tenant_a list MUST count only its own rows, got total={body['total']}"
        )
        assert {item["id"] for item in body["items"]} == {
            str(scan_a1.id),
            str(scan_a2.id),
        }
        assert {item["tenant_id"] for item in body["items"]} == {TENANT_A_ID}

    @pytest.mark.asyncio
    async def test_superadmin_list_sees_rows_from_every_tenant(
        self,
        tenant_client: AsyncClient,
        superadmin_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_a = await _seed_asset(db_session, "192.0.2.35")
        asset_b = await _seed_asset(db_session, "192.0.2.36", tenant_id=TENANT_B_ID)
        await _seed_scan(db_session, asset_id=asset_a, name="x-tenant-a1")
        await _seed_scan(db_session, asset_id=asset_a, name="x-tenant-a2")
        await _seed_scan(
            db_session,
            asset_id=asset_b,
            name="x-tenant-b1",
            tenant_id=TENANT_B_ID,
        )
        await _seed_scan(
            db_session,
            asset_id=asset_b,
            name="x-tenant-b2",
            tenant_id=TENANT_B_ID,
        )

        resp = await tenant_client.get("/api/v1/scans/", headers=superadmin_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 4, (
            f"superadmin list MUST see every tenant, got total={body['total']}"
        )
        seen_tenants = {item["tenant_id"] for item in body["items"]}
        assert seen_tenants == {TENANT_A_ID, TENANT_B_ID}


# ---------------------------------------------------------------------------
# Asset association
# ---------------------------------------------------------------------------
class TestAssetAssociation:
    """A scan is always anchored to a visible asset of the effective target
    tenant; its asset/tenant identity can never be moved after creation.
    """

    @pytest.mark.asyncio
    async def test_post_with_a_visible_asset_returns_201_and_the_callers_tenant(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.40")
        body = await _create_scan_via_api(
            tenant_client,
            admin_a_headers,
            _scan_payload(TENANT_A_ID, asset_id=asset_id),
        )
        assert body["tenant_id"] == TENANT_A_ID, (
            "the persisted scan MUST carry the caller's tenant"
        )
        assert body["asset_id"] == asset_id

    @pytest.mark.asyncio
    async def test_post_with_a_missing_asset_returns_404_and_persists_nothing(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        resp = await tenant_client.post(
            "/api/v1/scans/",
            headers=admin_a_headers,
            json=_scan_payload(TENANT_A_ID, asset_id=uuid4()),
        )
        assert resp.status_code == 404, f"expected 404, got {resp.status_code}"
        assert resp.json()["detail"] == "scan asset not found"
        assert await _count_scans(db_session) == 0

    @pytest.mark.asyncio
    async def test_post_with_an_asset_from_another_tenant_returns_404_and_persists_nothing(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        foreign_asset_id = await _seed_asset(
            db_session, "192.0.2.41", tenant_id=TENANT_B_ID
        )
        resp = await tenant_client.post(
            "/api/v1/scans/",
            headers=admin_a_headers,
            json=_scan_payload(TENANT_A_ID, asset_id=foreign_asset_id),
        )
        assert resp.status_code == 404, (
            f"a foreign-tenant asset MUST be invisible: 404, got {resp.status_code}"
        )
        assert resp.json()["detail"] == "scan asset not found"
        assert await _count_scans(db_session) == 0

    @pytest.mark.asyncio
    async def test_patch_rejects_asset_id_and_tenant_id_and_leaves_the_row_unchanged(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.42")
        other_asset_id = await _seed_asset(db_session, "192.0.2.43")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="identity-locked")

        resp = await tenant_client.patch(
            f"/api/v1/scans/{scan.id}",
            headers=admin_a_headers,
            json={"asset_id": other_asset_id, "tenant_id": TENANT_B_ID},
        )
        assert resp.status_code == 422, (
            f"PATCH MUST reject identity fields with 422, got {resp.status_code}"
        )
        detail = _detail_text(resp)
        assert "asset_id" in detail, f"422 detail MUST name asset_id: {detail!r}"
        assert "tenant_id" in detail, f"422 detail MUST name tenant_id: {detail!r}"

        row = await _fetch_scan(db_session, scan.id)
        assert str(row.asset_id) == asset_id, "the scan MUST keep its asset"
        assert str(row.tenant_id) == TENANT_A_ID, "the scan MUST keep its tenant"

    @pytest.mark.asyncio
    async def test_list_filtered_by_asset_id_returns_only_that_assets_scans(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_1 = await _seed_asset(db_session, "192.0.2.44")
        asset_2 = await _seed_asset(db_session, "192.0.2.45")
        scan_1 = await _seed_scan(db_session, asset_id=asset_1, name="filter-1")
        scan_2 = await _seed_scan(db_session, asset_id=asset_1, name="filter-2")
        await _seed_scan(db_session, asset_id=asset_2, name="filter-other")

        resp = await tenant_client.get(
            f"/api/v1/scans/?asset_id={asset_1}", headers=admin_a_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2, (
            f"the filter MUST count only that asset's scans, got {body['total']}"
        )
        assert {item["id"] for item in body["items"]} == {
            str(scan_1.id),
            str(scan_2.id),
        }
        assert {item["asset_id"] for item in body["items"]} == {asset_1}

    @pytest.mark.asyncio
    async def test_list_with_an_invisible_or_missing_asset_returns_404(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        missing = await tenant_client.get(
            f"/api/v1/scans/?asset_id={uuid4()}", headers=admin_a_headers
        )
        assert missing.status_code == 404, (
            f"a missing asset MUST be 404, got {missing.status_code}"
        )
        assert missing.json()["detail"] == "scan asset not found"

        foreign_asset_id = await _seed_asset(
            db_session, "192.0.2.46", tenant_id=TENANT_B_ID
        )
        invisible = await tenant_client.get(
            f"/api/v1/scans/?asset_id={foreign_asset_id}", headers=admin_a_headers
        )
        assert invisible.status_code == 404, (
            f"an invisible asset MUST be 404, got {invisible.status_code}"
        )
        assert invisible.json()["detail"] == "scan asset not found"


# ---------------------------------------------------------------------------
# Config contract — one valid shape per type, and every rejection names the
# offending key in the 422 ``detail``
# ---------------------------------------------------------------------------
class TestConfigContract:
    """Per-type config contract: a valid config persists; a missing required
    key, an unknown key, empty ``checks`` (vulnerability) and a path not
    beginning with ``/`` (web) are each 422 naming the offending key.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scan_type", sorted(_VALID_CONFIGS))
    async def test_valid_config_is_accepted(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        scan_type: str,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.50")
        resp = await tenant_client.post(
            "/api/v1/scans/",
            headers=admin_a_headers,
            json=_typed_scan_payload(
                TENANT_A_ID, asset_id, scan_type, _VALID_CONFIGS[scan_type]
            ),
        )
        assert resp.status_code == 201, (
            f"{scan_type} valid config MUST be 201, got {resp.status_code}: "
            f"{resp.text[:300]}"
        )
        assert resp.json()["type"] == scan_type

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scan_type", sorted(_MISSING_KEY_CONFIGS))
    async def test_config_missing_a_required_key_is_422_naming_the_key(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        scan_type: str,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.51")
        resp = await tenant_client.post(
            "/api/v1/scans/",
            headers=admin_a_headers,
            json=_typed_scan_payload(
                TENANT_A_ID, asset_id, scan_type, _MISSING_KEY_CONFIGS[scan_type]
            ),
        )
        assert resp.status_code == 422, (
            f"{scan_type} config missing {_MISSING_KEY_NAME[scan_type]!r} MUST be "
            f"422, got {resp.status_code}: {resp.text[:300]}"
        )
        assert _MISSING_KEY_NAME[scan_type] in _detail_text(resp), (
            "the 422 detail MUST name the offending key"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scan_type", sorted(_VALID_CONFIGS))
    async def test_config_with_an_unknown_key_is_422_naming_the_key(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        scan_type: str,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.52")
        config = {**_VALID_CONFIGS[scan_type], "unknown_key": "nope"}
        resp = await tenant_client.post(
            "/api/v1/scans/",
            headers=admin_a_headers,
            json=_typed_scan_payload(TENANT_A_ID, asset_id, scan_type, config),
        )
        assert resp.status_code == 422, (
            f"{scan_type} unknown config key MUST be 422, got {resp.status_code}: "
            f"{resp.text[:300]}"
        )
        assert "unknown_key" in _detail_text(resp), (
            "the 422 detail MUST name the offending key"
        )

    @pytest.mark.asyncio
    async def test_vulnerability_with_empty_checks_is_422_naming_checks(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.53")
        resp = await tenant_client.post(
            "/api/v1/scans/",
            headers=admin_a_headers,
            json=_typed_scan_payload(
                TENANT_A_ID, asset_id, "vulnerability", {"checks": []}
            ),
        )
        assert resp.status_code == 422, (
            f"empty checks MUST be 422, got {resp.status_code}: {resp.text[:300]}"
        )
        assert "checks" in _detail_text(resp), (
            "the 422 detail MUST name the offending key"
        )

    @pytest.mark.asyncio
    async def test_web_with_a_path_not_starting_with_slash_is_422_naming_paths(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.53")
        resp = await tenant_client.post(
            "/api/v1/scans/",
            headers=admin_a_headers,
            json=_typed_scan_payload(TENANT_A_ID, asset_id, "web", {"paths": ["admin"]}),
        )
        assert resp.status_code == 422, (
            f"a relative path MUST be 422, got {resp.status_code}: {resp.text[:300]}"
        )
        assert "config.paths" in _detail_text(resp), (
            "the 422 detail MUST name the offending key"
        )


# ---------------------------------------------------------------------------
# Lifecycle is read-only
# ---------------------------------------------------------------------------
class TestLifecycleIsReadOnly:
    """The lifecycle belongs to the execution slices, never to an HTTP client.

    A POST always persists ``status='pending'`` with null operational
    timestamps (the create schemas forbid lifecycle keys outright, so no
    client can even inject them); PATCH refuses them with 422 and the stored
    row stays untouched.
    """

    @pytest.mark.asyncio
    async def test_post_creates_a_pending_scan_with_null_started_and_completed_at(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.60")
        body = await _create_scan_via_api(
            tenant_client,
            admin_a_headers,
            _scan_payload(TENANT_A_ID, asset_id=asset_id),
        )
        assert body["status"] == "pending"
        assert body["started_at"] is None
        assert body["completed_at"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,value",
        [
            ("status", "completed"),
            ("started_at", "2024-01-01T00:00:00Z"),
            ("completed_at", "2024-01-02T00:00:00Z"),
        ],
    )
    async def test_post_body_cannot_carry_lifecycle_fields(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        field: str,
        value: Any,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.61")
        payload = {
            **_scan_payload(TENANT_A_ID, asset_id=asset_id),
            field: value,
        }
        resp = await tenant_client.post(
            "/api/v1/scans/", headers=admin_a_headers, json=payload
        )
        assert resp.status_code == 422, (
            f"POST body with {field!r} MUST be 422, got {resp.status_code}"
        )
        assert field in _detail_text(resp), (
            "the 422 detail MUST name the rejected lifecycle field"
        )
        assert await _count_scans(db_session) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,value",
        [
            ("status", "running"),
            ("started_at", "2024-01-01T00:00:00Z"),
            ("completed_at", "2024-01-02T00:00:00Z"),
        ],
    )
    async def test_patch_cannot_change_status_started_at_or_completed_at(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        field: str,
        value: Any,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.62")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="lifecycle-lock")

        resp = await tenant_client.patch(
            f"/api/v1/scans/{scan.id}",
            headers=admin_a_headers,
            json={field: value},
        )
        assert resp.status_code == 422, (
            f"PATCH with {field!r} MUST be 422, got {resp.status_code}"
        )
        assert field in _detail_text(resp), (
            "the 422 detail MUST name the rejected lifecycle field"
        )

        row = await _fetch_scan(db_session, scan.id)
        assert row.status == "pending", "the stored status MUST be unchanged"
        assert row.started_at is None, "started_at MUST stay null"
        assert row.completed_at is None, "completed_at MUST stay null"


# ---------------------------------------------------------------------------
# Duplicate open name — the partial-predicate guarantee
# ---------------------------------------------------------------------------
class TestDuplicateOpenName:
    """Only one OPEN (``pending``) scan may exist per (tenant, asset, name).

    The name is released as soon as the scan leaves ``pending``: that is the
    partial index predicate and it is asserted, not assumed.
    """

    @pytest.mark.asyncio
    async def test_second_pending_post_with_the_same_name_is_409(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.70")
        payload = _scan_payload(TENANT_A_ID, asset_id=asset_id)
        payload["name"] = "dup-open-name"

        first = await _create_scan_via_api(tenant_client, admin_a_headers, payload)
        assert first["status"] == "pending"

        second = await tenant_client.post(
            "/api/v1/scans/", headers=admin_a_headers, json=payload
        )
        assert second.status_code == 409, (
            f"a second pending scan with the same name MUST be 409, "
            f"got {second.status_code}: {second.text[:300]}"
        )
        assert "a pending scan named" in _detail_text(second)

        # The service's failed flush leaves the shared session's inner
        # transaction needing a rollback (the outer fixture transaction and
        # every committed savepoint survive it).
        await db_session.rollback()
        assert await _count_scans(db_session) == 1, "the duplicate MUST NOT persist"

    @pytest.mark.asyncio
    async def test_patch_rename_onto_an_occupied_open_name_is_409(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.71")
        kept = await _create_scan_via_api(
            tenant_client,
            admin_a_headers,
            _typed_scan_payload(
                TENANT_A_ID, asset_id, "discovery", _VALID_CONFIGS["discovery"],
                name="dup-keep",
            ),
        )
        mover = await _create_scan_via_api(
            tenant_client,
            admin_a_headers,
            _typed_scan_payload(
                TENANT_A_ID, asset_id, "discovery", _VALID_CONFIGS["discovery"],
                name="dup-mover",
            ),
        )

        resp = await tenant_client.patch(
            f"/api/v1/scans/{mover['id']}",
            headers=admin_a_headers,
            json={"name": "dup-keep"},
        )
        assert resp.status_code == 409, (
            f"renaming onto an occupied open name MUST be 409, "
            f"got {resp.status_code}: {resp.text[:300]}"
        )
        # Same post-flush-failure session hygiene as the POST duplicate test.
        await db_session.rollback()
        # The kept scan keeps its name and the mover keeps its own.
        row = await _fetch_scan(db_session, kept["id"])
        assert row.name == "dup-keep"
        row = await _fetch_scan(db_session, mover["id"])
        assert row.name == "dup-mover"

    @pytest.mark.asyncio
    async def test_post_with_the_same_name_is_allowed_once_the_first_is_no_longer_pending(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.72")
        payload = _scan_payload(TENANT_A_ID, asset_id=asset_id)
        payload["name"] = "recycled-name"

        first = await _create_scan_via_api(tenant_client, admin_a_headers, payload)

        # Release the name directly through the session: the API deliberately
        # refuses to set status, so the partial index predicate is moved by
        # taking the first scan OUT of ``pending`` here.
        row = await _fetch_scan(db_session, first["id"])
        row.status = "completed"
        await db_session.flush()
        await db_session.commit()

        second = await _create_scan_via_api(tenant_client, admin_a_headers, payload)
        assert second["status"] == "pending"
        assert second["id"] != first["id"]
        assert await _count_scans(db_session) == 2, (
            "BOTH scans must exist: the completed one AND the new pending one"
        )


# ---------------------------------------------------------------------------
# Pagination and ordering
# ---------------------------------------------------------------------------
class TestPaginationAndOrdering:
    """Out-of-range pages are 422; a page is the requested slice with a
    ``total`` matching the full count for the same filter; ordering is
    ``created_at DESC, id DESC``.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
    async def test_out_of_range_pagination_is_422(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        query: str,
    ) -> None:
        resp = await tenant_client.get(
            f"/api/v1/scans/?{query}", headers=admin_a_headers
        )
        assert resp.status_code == 422, (
            f"?{query} MUST be 422, got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_page_returns_the_requested_slice_with_total_matching_the_filter(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.80")
        base = datetime.now(timezone.utc)
        scans = [
            await _seed_scan(
                db_session,
                asset_id=asset_id,
                name=f"page-scan-{i}",
                created_at=base + timedelta(minutes=i),
            )
            for i in range(5)
        ]
        expected_order = [
            str(s.id)
            for s in sorted(scans, key=lambda s: (s.created_at, s.id.int), reverse=True)
        ]

        resp = await tenant_client.get(
            f"/api/v1/scans/?asset_id={asset_id}&limit=2&offset=1",
            headers=admin_a_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["limit"] == 2
        assert body["offset"] == 1
        assert body["total"] == 5, (
            f"total MUST match the full count for the same filter, got {body['total']}"
        )
        assert [item["id"] for item in body["items"]] == expected_order[1:3]

    @pytest.mark.asyncio
    async def test_list_is_ordered_by_created_at_desc_then_id_desc(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.81")
        base = datetime.now(timezone.utc)
        # Two rows SHARE a created_at so the ``id DESC`` tie-break is exercised.
        shared = base + timedelta(minutes=1)
        scans = [
            await _seed_scan(
                db_session, asset_id=asset_id, name="order-1", created_at=base
            ),
            await _seed_scan(
                db_session,
                asset_id=asset_id,
                name="order-2",
                created_at=shared,
                scan_id=uuid4(),
            ),
            await _seed_scan(
                db_session,
                asset_id=asset_id,
                name="order-3",
                created_at=shared,
                scan_id=uuid4(),
            ),
            await _seed_scan(
                db_session,
                asset_id=asset_id,
                name="order-4",
                created_at=base + timedelta(minutes=2),
            ),
        ]
        expected_order = [
            str(s.id)
            for s in sorted(scans, key=lambda s: (s.created_at, s.id.int), reverse=True)
        ]
        assert len({str(s.id) for s in scans}) == 4

        resp = await tenant_client.get(
            "/api/v1/scans/?limit=50", headers=admin_a_headers
        )
        assert resp.status_code == 200, resp.text
        assert [item["id"] for item in resp.json()["items"]] == expected_order


# ---------------------------------------------------------------------------
# Response whitelist
# ---------------------------------------------------------------------------
class TestResponseWhitelist:
    """Every scan representation exposes EXACTLY the eleven whitelisted
    fields; the ORM column name ``scan_type`` never appears on the wire.
    """

    @pytest.mark.asyncio
    async def test_create_get_and_patch_expose_exactly_the_eleven_whitelisted_fields(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.90")
        created = await _create_scan_via_api(
            tenant_client,
            admin_a_headers,
            _scan_payload(TENANT_A_ID, asset_id=asset_id),
        )
        fetched = await tenant_client.get(
            f"/api/v1/scans/{created['id']}", headers=admin_a_headers
        )
        assert fetched.status_code == 200, fetched.text
        patched = await tenant_client.patch(
            f"/api/v1/scans/{created['id']}",
            headers=admin_a_headers,
            json={"name": "whitelist-renamed"},
        )
        assert patched.status_code == 200, patched.text

        for label, body in (
            ("create", created),
            ("get", fetched.json()),
            ("patch", patched.json()),
        ):
            assert set(body.keys()) == _SCAN_RESPONSE_FIELDS, (
                f"{label} response MUST expose exactly the eleven whitelisted "
                f"fields; got {sorted(body.keys())!r}"
            )
            assert "scan_type" not in body, (
                "the ORM column name MUST never reach the wire"
            )

    @pytest.mark.asyncio
    async def test_list_items_expose_exactly_the_eleven_whitelisted_fields(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.91")
        await _seed_scan(db_session, asset_id=asset_id, name="whitelist-1")
        await _seed_scan(db_session, asset_id=asset_id, name="whitelist-2")

        resp = await tenant_client.get("/api/v1/scans/", headers=admin_a_headers)
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert len(items) == 2
        for item in items:
            assert set(item.keys()) == _SCAN_RESPONSE_FIELDS, (
                f"each list item MUST expose exactly the eleven whitelisted "
                f"fields; got {sorted(item.keys())!r}"
            )
            assert "scan_type" not in item, (
                "the ORM column name MUST never reach the wire"
            )


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
class TestEvents:
    """Mutating endpoints publish exactly one event on ``scan.events``, only
    AFTER the commit succeeds; a failed commit publishes NOTHING.
    """

    @pytest.mark.asyncio
    async def test_post_publishes_scan_created_on_scan_events_after_the_commit(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.100")

        sequence: list[str] = []
        calls = await _spy_on_event_bus(monkeypatch, sequence)

        # Probe the commit itself so publish-after-commit is proven at the
        # HTTP boundary too (the service ordering is unit-tested separately).
        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

        original_commit = _AsyncSession.commit

        async def _recording_commit(session: Any) -> Any:
            sequence.append("commit")
            return await original_commit(session)

        monkeypatch.setattr(_AsyncSession, "commit", _recording_commit, raising=True)

        created = await _create_scan_via_api(
            tenant_client,
            admin_a_headers,
            _scan_payload(TENANT_A_ID, asset_id=asset_id),
        )

        assert sequence == ["commit", "publish"], (
            f"the publish MUST happen after the commit, got {sequence!r}"
        )
        assert len(calls) == 1, f"expected exactly 1 publish, got {calls!r}"
        assert calls[0]["stream"] == "scan.events"
        assert calls[0]["event_type"] == "scan.created"
        assert calls[0]["scan_id"] == created["id"]

    @pytest.mark.asyncio
    async def test_patch_publishes_scan_updated_with_the_correct_changed_fields(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.101")
        created = await _create_scan_via_api(
            tenant_client,
            admin_a_headers,
            _scan_payload(TENANT_A_ID, asset_id=asset_id),
        )

        # Install the spy AFTER the POST so only the PATCH is observed.
        calls = await _spy_on_event_bus(monkeypatch)

        patched = await tenant_client.patch(
            f"/api/v1/scans/{created['id']}",
            headers=admin_a_headers,
            json={"name": "event-renamed", "config": {"host_discovery": False}},
        )
        assert patched.status_code == 200, patched.text

        assert len(calls) == 1, f"expected exactly 1 publish, got {calls!r}"
        assert calls[0]["stream"] == "scan.events"
        assert calls[0]["event_type"] == "scan.updated"
        assert calls[0]["scan_id"] == created["id"]
        assert calls[0]["changed_fields"] == ["name", "config"], (
            f"changed_fields MUST list exactly the changed public fields in the "
            f"fixed order, got {calls[0]['changed_fields']!r}"
        )

    @pytest.mark.asyncio
    async def test_delete_publishes_scan_deleted_on_scan_events(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.102")
        created = await _create_scan_via_api(
            tenant_client,
            admin_a_headers,
            _scan_payload(TENANT_A_ID, asset_id=asset_id),
        )

        calls = await _spy_on_event_bus(monkeypatch)

        deleted = await tenant_client.delete(
            f"/api/v1/scans/{created['id']}", headers=admin_a_headers
        )
        assert deleted.status_code == 204, deleted.text

        assert len(calls) == 1, f"expected exactly 1 publish, got {calls!r}"
        assert calls[0]["stream"] == "scan.events"
        assert calls[0]["event_type"] == "scan.deleted"
        assert calls[0]["scan_id"] == created["id"]

    @pytest.mark.asyncio
    async def test_failed_commit_publishes_nothing(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the session commit raises, NO event is published.

        The failure is forced by patching ``AsyncSession.commit`` on the class
        so the request-scoped shared session fails at commit time; the shared
        database stays clean because the flushed INSERT lives inside the
        fixture's savepoint and is discarded below.
        """
        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

        asset_id = await _seed_asset(db_session, "192.0.2.103")

        calls = await _spy_on_event_bus(monkeypatch)

        async def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("simulated commit failure for the scans event test")

        monkeypatch.setattr(_AsyncSession, "commit", _boom, raising=True)
        try:
            resp = await tenant_client.post(
                "/api/v1/scans/",
                headers=admin_a_headers,
                # A REAL visible asset: the request must reach the service and
                # its commit, not die earlier at the asset-resolution 404.
                json=_scan_payload(TENANT_A_ID, asset_id=asset_id),
            )
        except Exception:
            # ``ASGITransport`` re-raises the app error after the 5xx is on
            # the wire; either way the request reached the commit, which is
            # all this test needs.
            pass
        else:
            assert resp.status_code >= 500, (
                f"a commit failure MUST surface a 5xx, got {resp.status_code}: "
                f"{resp.text[:300]}"
            )

        # Leave the shared session clean: discard the flushed-but-never-
        # committed INSERT so nothing dirty survives into later assertions.
        await db_session.rollback()

        assert calls == [], (
            f"NO event MUST be published when the commit fails, got {calls!r}"
        )


# ---------------------------------------------------------------------------
# Service-error translation — the router must only translate contract errors
# ---------------------------------------------------------------------------
class TestServiceErrorTranslation:
    """The router translates ONLY the documented service contracts.

    The ``tenant_client`` fixture builds its ``AsyncClient`` WITHOUT
    ``raise_server_exceptions=False``, so the default is ``True``: an
    unhandled app exception is re-raised out of the request by
    ``ASGITransport``. That is the option this suite supports, so these tests
    assert on the raised exception instead of a 500 status.
    """

    @pytest.mark.asyncio
    async def test_a_non_contractual_value_error_is_not_translated_into_a_422(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unrelated ``ValueError`` from deeper code must NOT become a 422.

        The router must catch only ``service.ScanConfigError`` — the contract
        exception — not every ``ValueError``, whose internal message would
        otherwise be copied verbatim into the client-visible ``detail``.
        """
        import app.modules.scans.router as scans_router
        from unittest.mock import AsyncMock

        asset_id = await _seed_asset(db_session, "192.0.2.110")
        monkeypatch.setattr(
            scans_router.service,
            "create_scan",
            AsyncMock(side_effect=ValueError("boom")),
        )

        with pytest.raises(ValueError, match="boom"):
            await tenant_client.post(
                "/api/v1/scans/",
                headers=admin_a_headers,
                json=_scan_payload(TENANT_A_ID, asset_id=asset_id),
            )

    @pytest.mark.asyncio
    async def test_a_scan_asset_not_found_error_from_the_service_is_a_404(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The deleted-asset race (service-side FK violation) maps to 404.

        The detail message MUST stay identical to ``_resolve_scan_asset``'s
        pre-INSERT 404, so the two paths are indistinguishable to the caller.
        """
        import app.modules.scans.router as scans_router
        from unittest.mock import AsyncMock
        from app.modules.scans.service import ScanAssetNotFoundError

        asset_id = await _seed_asset(db_session, "192.0.2.111")
        monkeypatch.setattr(
            scans_router.service,
            "create_scan",
            AsyncMock(side_effect=ScanAssetNotFoundError("scan asset not found")),
        )

        resp = await tenant_client.post(
            "/api/v1/scans/",
            headers=admin_a_headers,
            json=_scan_payload(TENANT_A_ID, asset_id=asset_id),
        )

        assert resp.status_code == 404, (
            f"the deleted-asset race MUST be 404, got {resp.status_code}: "
            f"{resp.text[:300]}"
        )
        assert resp.json()["detail"] == "scan asset not found"
