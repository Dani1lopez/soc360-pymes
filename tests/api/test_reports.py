"""Slice 4 (F2) — Reports API tests.

Proportionate scope per the active freeze on overengineering: happy path per
endpoint and cross-tenant 404. Not the exhaustive matrix
``tests/api/test_scans.py`` carries.
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
from app.modules.reports.models import Report
from tests.conftest import TENANT_A_ID, TENANT_B_ID


def _report_payload(tenant_id: str, asset_id: object) -> dict:
    """A minimal valid report create body."""
    return {
        "tenant_id": tenant_id,
        "asset_id": str(asset_id),
        "name": "api-smoke-report",
        "report_type": "vulnerability",
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


async def _seed_report(
    db_session: AsyncSession,
    *,
    asset_id: str,
    name: str,
    tenant_id: str = TENANT_A_ID,
    report_type: str = "vulnerability",
) -> Report:
    await _set_superadmin_context(db_session)
    report = Report(
        tenant_id=UUID(tenant_id),
        asset_id=UUID(asset_id),
        name=name,
        report_type=report_type,
        status="pending",
    )
    db_session.add(report)
    await db_session.flush()
    await db_session.commit()
    return report


async def _fetch_report(db_session: AsyncSession, report_id: str | UUID) -> Report:
    await _set_superadmin_context(db_session)
    stmt = select(Report).where(Report.id == UUID(str(report_id)))
    return (await db_session.execute(stmt)).scalar_one()


def test_reports_router_is_registered_under_api_v1() -> None:
    """``create_app()`` must expose the reports collection and by-id routes."""
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/reports/" in paths
    assert "/api/v1/reports/{report_id}" in paths


# ---------------------------------------------------------------------------
# Happy path per endpoint
# ---------------------------------------------------------------------------
class TestHappyPath:
    @pytest.mark.asyncio
    async def test_post_creates_a_pending_report(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "198.51.100.1")

        resp = await tenant_client.post(
            "/api/v1/reports/",
            headers=admin_a_headers,
            json=_report_payload(TENANT_A_ID, asset_id),
        )
        assert resp.status_code == 201, (
            f"expected 201, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["status"] == "pending"
        assert body["generated_at"] is None
        assert body["asset_id"] == asset_id
        assert body["tenant_id"] == TENANT_A_ID

    @pytest.mark.asyncio
    async def test_get_by_id_returns_the_report(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "198.51.100.2")
        report = await _seed_report(db_session, asset_id=asset_id, name="happy-get")

        resp = await tenant_client.get(
            f"/api/v1/reports/{report.id}", headers=admin_a_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "happy-get"

    @pytest.mark.asyncio
    async def test_list_filters_by_asset_and_report_type(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_1 = await _seed_asset(db_session, "198.51.100.3")
        asset_2 = await _seed_asset(db_session, "198.51.100.4")
        wanted = await _seed_report(
            db_session, asset_id=asset_1, name="list-1", report_type="executive"
        )
        await _seed_report(db_session, asset_id=asset_1, name="list-2")
        await _seed_report(
            db_session, asset_id=asset_2, name="list-3", report_type="executive"
        )

        resp = await tenant_client.get(
            f"/api/v1/reports/?asset_id={asset_1}&report_type=executive&status=pending",
            headers=admin_a_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(wanted.id)

    @pytest.mark.asyncio
    async def test_patch_marks_the_report_completed(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "198.51.100.5")
        report = await _seed_report(db_session, asset_id=asset_id, name="happy-patch")
        url = f"/api/v1/reports/{report.id}"

        resp = await tenant_client.patch(
            url,
            headers=admin_a_headers,
            json={"status": "completed", "generated_at": "2026-09-26T12:00:00Z"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "completed"
        assert body["generated_at"] is not None
        assert body["report_type"] == "vulnerability"

        rejected = await tenant_client.patch(
            url, headers=admin_a_headers, json={"status": None}
        )
        assert rejected.status_code == 422, rejected.text

    @pytest.mark.asyncio
    async def test_delete_removes_the_report(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "198.51.100.6")
        report = await _seed_report(db_session, asset_id=asset_id, name="happy-delete")

        resp = await tenant_client.delete(
            f"/api/v1/reports/{report.id}", headers=admin_a_headers
        )
        assert resp.status_code == 204, resp.text

        follow_up = await tenant_client.get(
            f"/api/v1/reports/{report.id}", headers=admin_a_headers
        )
        assert follow_up.status_code == 404


# ---------------------------------------------------------------------------
# Cross-tenant access — always 404, never 403
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_cross_tenant_get_by_id_is_404(
        self,
        tenant_client: AsyncClient,
        admin_b_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "198.51.100.7")
        report = await _seed_report(db_session, asset_id=asset_id, name="iso-get")

        resp = await tenant_client.get(
            f"/api/v1/reports/{report.id}", headers=admin_b_headers
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "report not found"

    @pytest.mark.asyncio
    async def test_cross_tenant_patch_is_404_and_leaves_the_row_unchanged(
        self,
        tenant_client: AsyncClient,
        admin_b_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "198.51.100.8")
        report = await _seed_report(db_session, asset_id=asset_id, name="iso-patch")

        resp = await tenant_client.patch(
            f"/api/v1/reports/{report.id}",
            headers=admin_b_headers,
            json={"status": "completed"},
        )
        assert resp.status_code == 404, resp.text
        row = await _fetch_report(db_session, report.id)
        assert row.status == "pending"

    @pytest.mark.asyncio
    async def test_cross_tenant_delete_is_404(
        self,
        tenant_client: AsyncClient,
        admin_b_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_id = await _seed_asset(db_session, "198.51.100.9")
        report = await _seed_report(db_session, asset_id=asset_id, name="iso-delete")

        resp = await tenant_client.delete(
            f"/api/v1/reports/{report.id}", headers=admin_b_headers
        )
        assert resp.status_code == 404, resp.text
        row = await _fetch_report(db_session, report.id)
        assert row.id == report.id

    @pytest.mark.asyncio
    async def test_cross_tenant_asset_id_on_create_is_404(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_b = await _seed_asset(db_session, "198.51.100.10", tenant_id=TENANT_B_ID)

        resp = await tenant_client.post(
            "/api/v1/reports/",
            headers=admin_a_headers,
            json=_report_payload(TENANT_A_ID, asset_b),
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "report asset not found"

    @pytest.mark.asyncio
    async def test_create_with_a_missing_asset_is_404(
        self, tenant_client: AsyncClient, admin_a_headers: dict
    ) -> None:
        resp = await tenant_client.post(
            "/api/v1/reports/",
            headers=admin_a_headers,
            json=_report_payload(TENANT_A_ID, uuid4()),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_list_returns_only_own_tenant_rows(
        self,
        tenant_client: AsyncClient,
        admin_a_headers: dict,
        db_session: AsyncSession,
    ) -> None:
        asset_a = await _seed_asset(db_session, "198.51.100.11")
        asset_b = await _seed_asset(db_session, "198.51.100.12", tenant_id=TENANT_B_ID)
        report_a = await _seed_report(db_session, asset_id=asset_a, name="iso-list-a")
        await _seed_report(
            db_session, asset_id=asset_b, name="iso-list-b", tenant_id=TENANT_B_ID
        )

        resp = await tenant_client.get("/api/v1/reports/", headers=admin_a_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(report_a.id)
