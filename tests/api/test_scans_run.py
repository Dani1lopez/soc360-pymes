"""HTTP dispatch contract, without a live Celery worker."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.modules.scans.models import Scan
from app.modules.tenants.models import Tenant
from tests.api.test_scans import _seed_asset, _seed_scan, _set_superadmin_context
from tests.conftest import TENANT_A_ID, TENANT_B_ID


@pytest.fixture(autouse=True)
def execution_enabled(monkeypatch):
    monkeypatch.setattr(settings, "SCAN_EXECUTION_ENABLED", True)


@pytest.fixture
async def dispatcher(tenant_client):
    from app.modules.scans.dispatch import get_scan_dispatcher

    class Fake:
        calls = []
        fail = False

        async def dispatch(self, scan_id, tenant_id):
            self.calls.append((scan_id, tenant_id))
            if self.fail:
                raise RuntimeError("unavailable")

    fake = Fake()
    tenant_client.app.dependency_overrides[get_scan_dispatcher] = lambda: fake
    yield fake
    tenant_client.app.dependency_overrides.pop(get_scan_dispatcher, None)


async def seed(db, **kwargs):
    tenant = kwargs.get("tenant_id", TENANT_A_ID)
    asset = await _seed_asset(db, "192.0.2.123", tenant_id=tenant)
    return await _seed_scan(db, asset_id=asset, name="run-test", **kwargs)


async def dispatched(db, scan_id):
    await _set_superadmin_context(db)
    return (
        await db.execute(select(Scan.dispatched_at).where(Scan.id == scan_id))
    ).scalar_one()


async def test_flag_off(tenant_client, admin_a_headers, db_session, monkeypatch):
    scan = await seed(db_session)
    monkeypatch.setattr(settings, "SCAN_EXECUTION_ENABLED", False)
    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=admin_a_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "scan execution is disabled"
    assert await dispatched(db_session, scan.id) is None


async def test_disabled_precedes_rbac(tenant_client, viewer_a_headers, monkeypatch):
    monkeypatch.setattr(settings, "SCAN_EXECUTION_ENABLED", False)
    response = await tenant_client.post(
        f"/api/v1/scans/{uuid4()}/run", headers=viewer_a_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "scan execution is disabled"


@pytest.mark.parametrize(
    "role,expected",
    [
        ("admin", 202),
        ("superadmin", 202),
        ("analyst", 403),
        ("viewer", 403),
        ("ingestor", 403),
    ],
)
async def test_rbac(
    role,
    expected,
    tenant_client,
    db_session,
    dispatcher,
    admin_a_headers,
    superadmin_headers,
    analyst_a_headers,
    viewer_a_headers,
    ingestor_a_headers,
):
    headers = {
        "admin": admin_a_headers,
        "superadmin": superadmin_headers,
        "analyst": analyst_a_headers,
        "viewer": viewer_a_headers,
        "ingestor": ingestor_a_headers,
    }[role]
    scan = await seed(db_session)
    response = await tenant_client.post(f"/api/v1/scans/{scan.id}/run", headers=headers)
    assert response.status_code == expected
    assert len(dispatcher.calls) == (expected == 202)


async def test_success_and_second_run(
    tenant_client, admin_a_headers, db_session, dispatcher
):
    scan = await seed(db_session)
    scan_id = scan.id
    url = f"/api/v1/scans/{scan_id}/run"
    response = await tenant_client.post(url, headers=admin_a_headers)
    assert response.status_code == 202
    assert response.json()["id"] == str(scan_id)
    assert await dispatched(db_session, scan_id) is not None
    assert dispatcher.calls == [(scan_id, UUID(TENANT_A_ID))]
    response = await tenant_client.post(url, headers=admin_a_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "scan is not dispatchable"
    assert len(dispatcher.calls) == 1


@pytest.mark.parametrize("status", ["running", "completed", "failed", "cancelled"])
async def test_non_pending(
    status, tenant_client, admin_a_headers, db_session, dispatcher
):
    scan = await seed(db_session, status=status)
    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=admin_a_headers
    )
    assert response.status_code == 409
    assert dispatcher.calls == []


async def test_missing_and_cross_tenant(
    tenant_client, admin_a_headers, db_session, dispatcher
):
    scan = await seed(db_session, tenant_id=TENANT_B_ID)
    for scan_id in [scan.id, uuid4()]:
        response = await tenant_client.post(
            f"/api/v1/scans/{scan_id}/run", headers=admin_a_headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "scan not found"
    assert dispatcher.calls == []


async def test_superadmin_foreign_tenant(
    tenant_client, superadmin_headers, db_session, dispatcher
):
    scan = await seed(db_session, tenant_id=TENANT_B_ID)
    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=superadmin_headers
    )
    assert response.status_code == 202
    assert dispatcher.calls == [(scan.id, UUID(TENANT_B_ID))]


@pytest.mark.parametrize(
    "status,started,yesterday,expected",
    [
        ("pending", False, False, 429),
        ("failed", False, False, 202),
        ("cancelled", False, False, 202),
        ("failed", True, False, 429),
        ("pending", False, True, 202),
    ],
)
async def test_quota(
    status,
    started,
    yesterday,
    expected,
    tenant_client,
    admin_a_headers,
    db_session,
    dispatcher,
):
    scan = await seed(db_session)
    scan_id = scan.id
    other = await _seed_scan(
        db_session, asset_id=str(scan.asset_id), name="other", status=status
    )
    now = datetime.now(timezone.utc)
    other.dispatched_at = now - timedelta(days=1) if yesterday else now
    other.started_at = now if started else None
    await db_session.execute(
        update(Tenant).where(Tenant.id == UUID(TENANT_A_ID)).values(scans_per_day=1)
    )
    await db_session.commit()
    response = await tenant_client.post(
        f"/api/v1/scans/{scan_id}/run", headers=admin_a_headers
    )
    assert response.status_code == expected
    if expected == 429:
        assert response.json()["detail"] == "daily scan quota exceeded"
        assert await dispatched(db_session, scan_id) is None
        assert dispatcher.calls == []


async def test_dispatch_failure_keeps_reservation(
    tenant_client, admin_a_headers, db_session, dispatcher
):
    scan = await seed(db_session)
    scan_id = scan.id
    dispatcher.fail = True
    url = f"/api/v1/scans/{scan_id}/run"
    response = await tenant_client.post(url, headers=admin_a_headers)
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert await dispatched(db_session, scan_id) is not None
    assert dispatcher.calls == [(scan_id, UUID(TENANT_A_ID))]
    assert (await tenant_client.post(url, headers=admin_a_headers)).status_code == 409


async def test_dispatch_uses_database_clock(
    tenant_client, admin_a_headers, db_session, dispatcher
):
    scan = await seed(db_session)
    scan_id = scan.id
    transaction_start = (await db_session.execute(select(func.now()))).scalar_one()
    response = await tenant_client.post(
        f"/api/v1/scans/{scan_id}/run", headers=admin_a_headers
    )
    assert response.status_code == 202
    assert await dispatched(db_session, scan_id) == transaction_start
