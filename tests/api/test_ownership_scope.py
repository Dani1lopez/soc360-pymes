"""H2-T7: how far one declaration reaches (decision D4).

A declaration covers exactly the asset value that was declared: a subnet does
not cover the hosts inside it, a different subnet needs its own declaration, and
editing the asset value invalidates the declaration it was made for.
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
        def __init__(self) -> None:
            self.calls: list = []

        async def dispatch(self, scan_id, tenant_id):
            self.calls.append((scan_id, tenant_id))

    fake = Fake()
    tenant_client.app.dependency_overrides[get_scan_dispatcher] = lambda: fake
    yield fake
    tenant_client.app.dependency_overrides.pop(get_scan_dispatcher, None)


async def _scan_for(db, asset_id: str, name: str) -> Scan:
    return await _seed_scan(db, asset_id=asset_id, name=name)


@pytest.mark.parametrize(
    "asset_type,value",
    [("ip", "10.0.0.5"), ("subnet", "10.0.0.0/24")],
)
async def test_an_internal_asset_can_be_declared_and_dispatched(
    tenant_client, admin_a_headers, db_session, dispatcher, asset_type, value
) -> None:
    """The layer S5 defines for SSH, MySQL and internal ranges: no challenge."""
    asset_id = await _seed_asset(
        db_session, value, tenant_id=TENANT_A_ID, asset_type=asset_type
    )
    await _declare_ownership(db_session, asset_id, tenant_id=TENANT_A_ID)
    scan = await _scan_for(db_session, asset_id, f"internal-{asset_type}")

    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=admin_a_headers
    )

    assert response.status_code == 202, response.text


async def test_a_subnet_declaration_does_not_cover_an_interior_host(
    tenant_client, admin_a_headers, db_session, dispatcher
) -> None:
    subnet_id = await _seed_asset(db_session, "10.0.0.0/24", tenant_id=TENANT_A_ID)
    host_id = await _seed_asset(db_session, "10.0.0.5", tenant_id=TENANT_A_ID)
    await _declare_ownership(db_session, subnet_id, tenant_id=TENANT_A_ID)
    scan = await _scan_for(db_session, host_id, "interior-host")

    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=admin_a_headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == ERROR_DETAIL


async def test_a_different_subnet_needs_its_own_declaration(
    tenant_client, admin_a_headers, db_session, dispatcher
) -> None:
    declared_id = await _seed_asset(db_session, "10.0.0.0/24", tenant_id=TENANT_A_ID)
    other_id = await _seed_asset(db_session, "10.0.1.0/24", tenant_id=TENANT_A_ID)
    await _declare_ownership(db_session, declared_id, tenant_id=TENANT_A_ID)
    scan = await _scan_for(db_session, other_id, "other-subnet")

    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=admin_a_headers
    )

    assert response.status_code == 403, response.text


async def test_editing_the_asset_value_invalidates_the_declaration(
    tenant_client, admin_a_headers, db_session, dispatcher
) -> None:
    """D4: a wider subnet cannot reuse the declaration made for a narrower one."""
    asset_id = await _seed_asset(db_session, "10.0.0.0/24", tenant_id=TENANT_A_ID)
    await _declare_ownership(db_session, asset_id, tenant_id=TENANT_A_ID)

    widened = await tenant_client.patch(
        f"/api/v1/assets/{asset_id}",
        headers=admin_a_headers,
        json={"type": "subnet", "value": "10.0.0.0/16"},
    )
    assert widened.status_code == 200, widened.text

    scan = await _scan_for(db_session, asset_id, "widened-subnet")
    response = await tenant_client.post(
        f"/api/v1/scans/{scan.id}/run", headers=admin_a_headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == ERROR_DETAIL
    assert dispatcher.calls == []
    await _set_superadmin_context(db_session)
    assert (
        await db_session.scalar(select(Scan.dispatched_at).where(Scan.id == scan.id))
        is None
    )
