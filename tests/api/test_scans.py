"""Slice 2 (F2) — Scans API tests (PR3 part 1: HTTP surface).

Small focused suite proving the scans router is wired into ``create_app()``
and that the RBAC/tenant contract basics hold at the HTTP boundary:

* router registration under ``/api/v1/scans``
* unauthenticated POST is 401
* ``ingestor`` is 403 on every scans operation (before any existence check)
* POST with an asset invisible to the caller is 404 and persists nothing
* POST with a cross-tenant ``tenant_id`` is 422 ``tenant_id mismatch``
* out-of-range pagination is 422

The FULL 30-cell RBAC matrix, tenant isolation, config matrix, lifecycle,
409, events and pagination coverage is a SEPARATE later delegation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.main import create_app
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
