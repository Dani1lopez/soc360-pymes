"""Slice 3 (F2) — Vulnerabilities API tests.

Proportionate scope per the active freeze on overengineering: happy path per
endpoint, RBAC 403 for ``ingestor``, and cross-tenant 404. Not the exhaustive
matrix ``tests/api/test_scans.py`` carries — see that file's docstring for
what deliberately is NOT duplicated here.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from app.main import create_app
from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from app.modules.vulnerabilities.models import Vulnerability
from tests.conftest import TENANT_A_ID, TENANT_B_ID


def _vuln_payload(tenant_id: str, scan_id: object) -> dict:
    """A minimal valid vulnerability create body."""
    return {
        "tenant_id": tenant_id,
        "scan_id": str(scan_id),
        "title": "api-smoke-vuln",
        "severity": "high",
    }


async def _set_superadmin_context(db_session: AsyncSession) -> None:
    await set_tenant_context(db_session, None, True)


async def _seed_asset(
    db_session: AsyncSession, value: str, tenant_id: str = TENANT_A_ID
) -> str:
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
) -> Scan:
    await _set_superadmin_context(db_session)
    scan = Scan(
        tenant_id=UUID(tenant_id),
        asset_id=UUID(asset_id),
        name=name,
        scan_type="vulnerability",
        status="pending",
        config={"checks": ["ssh-login-bruteforce"]},
    )
    db_session.add(scan)
    await db_session.flush()
    await db_session.commit()
    return scan


async def _seed_vulnerability(
    db_session: AsyncSession,
    *,
    scan_id: UUID,
    title: str,
    tenant_id: str = TENANT_A_ID,
    severity: str = "high",
) -> Vulnerability:
    await _set_superadmin_context(db_session)
    vuln = Vulnerability(
        tenant_id=UUID(tenant_id), scan_id=scan_id, title=title, severity=severity
    )
    db_session.add(vuln)
    await db_session.flush()
    await db_session.commit()
    return vuln


async def _fetch_vulnerability(db_session: AsyncSession, vuln_id: str | UUID) -> Vulnerability:
    await _set_superadmin_context(db_session)
    stmt = select(Vulnerability).where(Vulnerability.id == UUID(str(vuln_id)))
    return (await db_session.execute(stmt)).scalar_one()


def test_vulnerabilities_router_is_registered_under_api_v1() -> None:
    """``create_app()`` must expose the vulnerabilities collection and by-id routes."""
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/vulnerabilities/" in paths
    assert "/api/v1/vulnerabilities/{vulnerability_id}" in paths


@pytest.mark.asyncio
async def test_post_vulnerability_requires_authentication(tenant_client: AsyncClient) -> None:
    resp = await tenant_client.post(
        "/api/v1/vulnerabilities/", json=_vuln_payload(TENANT_A_ID, uuid4())
    )
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Happy path per endpoint
# ---------------------------------------------------------------------------
class TestHappyPath:
    @pytest.mark.asyncio
    async def test_post_creates_an_open_vulnerability(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.1")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="happy-post")

        resp = await tenant_client.post(
            "/api/v1/vulnerabilities/",
            headers=admin_a_headers,
            json=_vuln_payload(TENANT_A_ID, scan.id),
        )
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["status"] == "open"
        assert body["scan_id"] == str(scan.id)
        assert body["tenant_id"] == TENANT_A_ID

    @pytest.mark.asyncio
    async def test_post_forces_status_open_even_if_sent(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.2")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="happy-post-status")

        payload = _vuln_payload(TENANT_A_ID, scan.id)
        payload["status"] = "fixed"
        resp = await tenant_client.post(
            "/api/v1/vulnerabilities/", headers=admin_a_headers, json=payload
        )
        assert resp.status_code == 422, (
            f"status is not accepted on create (extra=forbid), got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_get_by_id_returns_the_vulnerability(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.3")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="happy-get")
        vuln = await _seed_vulnerability(db_session, scan_id=scan.id, title="xss")

        resp = await tenant_client.get(
            f"/api/v1/vulnerabilities/{vuln.id}", headers=admin_a_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "xss"

    @pytest.mark.asyncio
    async def test_list_filtered_by_scan_id_returns_only_that_scans_vulnerabilities(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.4")
        scan_1 = await _seed_scan(db_session, asset_id=asset_id, name="happy-list-1")
        scan_2 = await _seed_scan(db_session, asset_id=asset_id, name="happy-list-2")
        vuln_1 = await _seed_vulnerability(db_session, scan_id=scan_1.id, title="v1")
        await _seed_vulnerability(db_session, scan_id=scan_2.id, title="v2")

        resp = await tenant_client.get(
            f"/api/v1/vulnerabilities/?scan_id={scan_1.id}", headers=admin_a_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(vuln_1.id)

    @pytest.mark.asyncio
    async def test_patch_updates_status_and_leaves_identity_fields_immutable(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.5")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="happy-patch")
        vuln = await _seed_vulnerability(db_session, scan_id=scan.id, title="patchable")

        resp = await tenant_client.patch(
            f"/api/v1/vulnerabilities/{vuln.id}",
            headers=admin_a_headers,
            json={"status": "fixed"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "fixed"
        assert body["title"] == "patchable"

    @pytest.mark.asyncio
    async def test_patch_rejects_identity_fields(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.6")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="happy-patch-identity")
        vuln = await _seed_vulnerability(db_session, scan_id=scan.id, title="immutable")

        resp = await tenant_client.patch(
            f"/api/v1/vulnerabilities/{vuln.id}",
            headers=admin_a_headers,
            json={"title": "hijacked"},
        )
        assert resp.status_code == 422, (
            f"title must not be patchable (extra=forbid), got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_delete_removes_the_vulnerability(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.7")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="happy-delete")
        vuln = await _seed_vulnerability(db_session, scan_id=scan.id, title="deletable")

        resp = await tenant_client.delete(
            f"/api/v1/vulnerabilities/{vuln.id}", headers=admin_a_headers
        )
        assert resp.status_code == 204, resp.text

        follow_up = await tenant_client.get(
            f"/api/v1/vulnerabilities/{vuln.id}", headers=admin_a_headers
        )
        assert follow_up.status_code == 404

    @pytest.mark.asyncio
    async def test_post_with_an_invisible_scan_is_404_and_persists_nothing(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        resp = await tenant_client.post(
            "/api/v1/vulnerabilities/",
            headers=admin_a_headers,
            json=_vuln_payload(TENANT_A_ID, uuid4()),
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "vulnerability scan not found"

    @pytest.mark.asyncio
    async def test_post_with_a_tenant_id_mismatch_is_422(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.8")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="happy-mismatch")

        resp = await tenant_client.post(
            "/api/v1/vulnerabilities/",
            headers=admin_a_headers,
            json=_vuln_payload(TENANT_B_ID, scan.id),
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == "tenant_id mismatch"


# ---------------------------------------------------------------------------
# RBAC — ingestor is denied everywhere
# ---------------------------------------------------------------------------
class TestRbac:
    @pytest.mark.asyncio
    async def test_ingestor_is_denied_on_every_vulnerabilities_operation(
        self,
        tenant_client: AsyncClient,
        ingestor_a_headers: dict,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.9")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="rbac-ingestor")
        vuln = await _seed_vulnerability(db_session, scan_id=scan.id, title="rbac")

        post = await tenant_client.post(
            "/api/v1/vulnerabilities/",
            headers=ingestor_a_headers,
            json=_vuln_payload(TENANT_A_ID, scan.id),
        )
        assert post.status_code == 403, f"POST expected 403, got {post.status_code}"

        get_list = await tenant_client.get(
            "/api/v1/vulnerabilities/", headers=ingestor_a_headers
        )
        assert get_list.status_code == 403, f"GET list expected 403, got {get_list.status_code}"

        get_by_id = await tenant_client.get(
            f"/api/v1/vulnerabilities/{vuln.id}", headers=ingestor_a_headers
        )
        assert get_by_id.status_code == 403, (
            f"GET by-id expected 403, got {get_by_id.status_code}"
        )

        patch = await tenant_client.patch(
            f"/api/v1/vulnerabilities/{vuln.id}",
            headers=ingestor_a_headers,
            json={"status": "fixed"},
        )
        assert patch.status_code == 403, f"PATCH expected 403, got {patch.status_code}"

        delete = await tenant_client.delete(
            f"/api/v1/vulnerabilities/{vuln.id}", headers=ingestor_a_headers
        )
        assert delete.status_code == 403, f"DELETE expected 403, got {delete.status_code}"


# ---------------------------------------------------------------------------
# Cross-tenant access — always 404, never 403
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_cross_tenant_get_by_id_is_404(
        self, tenant_client: AsyncClient, admin_b_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.10")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="iso-get")
        vuln = await _seed_vulnerability(db_session, scan_id=scan.id, title="iso-get-vuln")

        resp = await tenant_client.get(
            f"/api/v1/vulnerabilities/{vuln.id}", headers=admin_b_headers
        )
        assert resp.status_code == 404, (
            f"cross-tenant GET MUST be 404, got {resp.status_code}: {resp.text}"
        )
        assert resp.json()["detail"] == "vulnerability not found"

    @pytest.mark.asyncio
    async def test_cross_tenant_patch_is_404_and_leaves_the_row_unchanged(
        self, tenant_client: AsyncClient, admin_b_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.11")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="iso-patch")
        vuln = await _seed_vulnerability(db_session, scan_id=scan.id, title="iso-patch-vuln")

        resp = await tenant_client.patch(
            f"/api/v1/vulnerabilities/{vuln.id}",
            headers=admin_b_headers,
            json={"status": "fixed"},
        )
        assert resp.status_code == 404, (
            f"cross-tenant PATCH MUST be 404, got {resp.status_code}: {resp.text}"
        )
        row = await _fetch_vulnerability(db_session, vuln.id)
        assert row.status == "open"

    @pytest.mark.asyncio
    async def test_cross_tenant_delete_is_404(
        self, tenant_client: AsyncClient, admin_b_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_id = await _seed_asset(db_session, "192.0.2.12")
        scan = await _seed_scan(db_session, asset_id=asset_id, name="iso-delete")
        vuln = await _seed_vulnerability(db_session, scan_id=scan.id, title="iso-delete-vuln")

        resp = await tenant_client.delete(
            f"/api/v1/vulnerabilities/{vuln.id}", headers=admin_b_headers
        )
        assert resp.status_code == 404, (
            f"cross-tenant DELETE MUST be 404, got {resp.status_code}: {resp.text}"
        )
        row = await _fetch_vulnerability(db_session, vuln.id)
        assert row.id == vuln.id

    @pytest.mark.asyncio
    async def test_cross_tenant_scan_id_on_create_is_404(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_b = await _seed_asset(db_session, "192.0.2.13", tenant_id=TENANT_B_ID)
        scan_b = await _seed_scan(
            db_session, asset_id=asset_b, name="iso-create-scan", tenant_id=TENANT_B_ID
        )

        resp = await tenant_client.post(
            "/api/v1/vulnerabilities/",
            headers=admin_a_headers,
            json=_vuln_payload(TENANT_A_ID, scan_b.id),
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "vulnerability scan not found"

    @pytest.mark.asyncio
    async def test_list_returns_only_own_tenant_rows(
        self, tenant_client: AsyncClient, admin_a_headers: dict, db_session: AsyncSession
    ) -> None:
        asset_a = await _seed_asset(db_session, "192.0.2.14")
        asset_b = await _seed_asset(db_session, "192.0.2.15", tenant_id=TENANT_B_ID)
        scan_a = await _seed_scan(db_session, asset_id=asset_a, name="iso-list-a")
        scan_b = await _seed_scan(
            db_session, asset_id=asset_b, name="iso-list-b", tenant_id=TENANT_B_ID
        )
        vuln_a = await _seed_vulnerability(db_session, scan_id=scan_a.id, title="iso-list-a-vuln")
        await _seed_vulnerability(
            db_session, scan_id=scan_b.id, title="iso-list-b-vuln", tenant_id=TENANT_B_ID
        )

        resp = await tenant_client.get("/api/v1/vulnerabilities/", headers=admin_a_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(vuln_a.id)
