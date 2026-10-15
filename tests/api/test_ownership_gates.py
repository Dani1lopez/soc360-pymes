"""H2-T4: the dispatch gate.

A scan whose asset has no verified ownership declaration must never become
claimable: the dispatch is the early guarantee, so it must not fix
``dispatched_at`` and must answer a stable error.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.modules.scans.models import Scan
from tests.api.test_scans import (
    _declare_ownership,
    _seed_asset,
    _seed_scan,
    _set_superadmin_context,
)
from tests.conftest import TENANT_A_ID

ERROR_DETAIL = "asset ownership is not verified"


@pytest.fixture(autouse=True)
def execution_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SCAN_EXECUTION_ENABLED", True)


@pytest.fixture
async def dispatcher(tenant_client):
    from app.modules.scans.dispatch import get_scan_dispatcher

    class Fake:
        calls: list = []

        async def dispatch(self, scan_id, tenant_id):
            self.calls.append((scan_id, tenant_id))

    fake = Fake()
    tenant_client.app.dependency_overrides[get_scan_dispatcher] = lambda: fake
    yield fake
    tenant_client.app.dependency_overrides.pop(get_scan_dispatcher, None)


async def _row(db, scan_id):
    await _set_superadmin_context(db)
    return (
        await db.execute(
            select(Scan.status, Scan.dispatched_at).where(Scan.id == scan_id)
        )
    ).one()


async def _declare(db, asset_id: str, *, status: str) -> None:
    await _declare_ownership(db, asset_id, status=status)


async def _seed(db) -> tuple[str, Scan]:
    asset_id = await _seed_asset(db, "10.0.0.20", tenant_id=TENANT_A_ID)
    scan = await _seed_scan(db, asset_id=asset_id, name="ownership-gate")
    return asset_id, scan


@pytest.mark.parametrize("declaration", ["missing", "pending", "revoked", "failed"])
async def test_run_without_a_verified_declaration_is_forbidden(
    tenant_client,
    admin_a_headers,
    db_session,
    dispatcher,
    declaration: str,
) -> None:
    asset_id, scan = await _seed(db_session)
    if declaration != "missing":
        await _declare(db_session, asset_id, status=declaration)

    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=admin_a_headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == ERROR_DETAIL
    assert dispatcher.calls == []
    assert tuple(await _row(db_session, scan.id)) == ("pending", None)


async def test_run_with_a_verified_declaration_dispatches(
    tenant_client, admin_a_headers, db_session, dispatcher
) -> None:
    asset_id, scan = await _seed(db_session)
    await _declare(db_session, asset_id, status="verified")

    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=admin_a_headers
    )

    assert response.status_code == 202, response.text
    status, dispatched_at = await _row(db_session, scan.id)
    assert status == "pending"
    assert dispatched_at is not None
    assert [call[0] for call in dispatcher.calls] == [scan.id]
