"""Cancellation remains available even when execution is disabled."""

from uuid import uuid4

import pytest

from app.core.config import settings
from tests.api.test_scans_run import seed
from tests.conftest import TENANT_B_ID


@pytest.mark.parametrize(
    "status", ["pending", "running", "completed", "failed", "cancelled"]
)
async def test_cancel_status(
    status, tenant_client, admin_a_headers, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "SCAN_EXECUTION_ENABLED", False)
    scan = await seed(db_session, status=status)
    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/cancel", headers=admin_a_headers
    )
    assert response.status_code == (200 if status in ("pending", "running") else 409)
    if response.status_code == 200:
        assert response.json()["status"] == "cancelled"
        assert response.json()["completed_at"] is not None
    else:
        assert response.json()["detail"] == "scan is not cancellable"


async def test_cancel_missing_cross_tenant(tenant_client, admin_a_headers, db_session):
    scan = await seed(db_session, tenant_id=TENANT_B_ID)
    for scan_id in (scan.id, uuid4()):
        response = await tenant_client.post(
            f"/api/v1/scans/{scan_id}/cancel", headers=admin_a_headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "scan not found"


@pytest.mark.parametrize("role", ["analyst", "viewer", "ingestor"])
async def test_cancel_rbac(
    role,
    tenant_client,
    db_session,
    analyst_a_headers,
    viewer_a_headers,
    ingestor_a_headers,
):
    scan = await seed(db_session)
    headers = {
        "analyst": analyst_a_headers,
        "viewer": viewer_a_headers,
        "ingestor": ingestor_a_headers,
    }[role]
    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/cancel", headers=headers
    )
    assert response.status_code == 403


async def test_cancel_superadmin_foreign(tenant_client, superadmin_headers, db_session):
    scan = await seed(db_session, tenant_id=TENANT_B_ID)
    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/cancel", headers=superadmin_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
