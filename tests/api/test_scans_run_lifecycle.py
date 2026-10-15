"""The dispatch endpoint under the PRODUCTION database session lifecycle.

``get_db`` wraps each request in ``session.begin()``, so a commit inside the
request closes that transaction: any statement after it raises
``InvalidRequestError: Can't operate on closed transaction inside context
manager``. ``dispatch_scan`` committed the dispatch and then re-applied the RLS
context and refreshed the row, so the endpoint answered 500 while its own
docstring promises 202, and the dispatch it had already committed was silently
recovered later by the periodic pump.

Every other test in the suite runs against the ``tenant_client`` override, which
yields a shared session with no transaction context manager: the production
shape is never exercised, so the defect stayed invisible. This module restores
it, exactly as the CSV lifecycle tests do, and pins the 202 contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, AsyncGenerator, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import (
    AsyncSessionLocal,
    engine,
    get_session_with_tenant,
    set_tenant_context,
)
from app.dependencies import get_db
from app.dependencies.auth import get_current_user
from app.modules.assets.models import Asset
from app.modules.assets.ownership.models import AssetOwnershipDeclaration
from app.modules.scans.dispatch import get_scan_dispatcher
from app.modules.scans.models import Scan
from app.modules.tenants.models import Tenant


@pytest.fixture(autouse=True)
async def _dispose_app_db_engine_pool() -> AsyncGenerator[None, None]:
    """Close pooled connections in this test's loop.

    The production engine pools connections and asyncpg binds them to the loop
    that created them, while pytest-asyncio gives each test its own loop.
    """
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _execution_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SCAN_EXECUTION_ENABLED", True)


async def _seed_committed() -> tuple[UUID, UUID, UUID]:
    """Commit a tenant, an asset and a pending scan, visible to any connection.

    One session and one commit, deliberately: this session is opened through
    ``get_session_with_tenant``, which wraps it in ``session.begin()`` exactly
    like the request dependency. A statement after a mid-way commit is illegal
    there, which is why the shared ``_seed_asset``/``_seed_scan`` helpers (each
    of which commits) cannot be combined in one such session.
    """
    tenant_id = uuid4()
    asset_id = uuid4()
    scan_id = uuid4()
    async with get_session_with_tenant(None, True) as session:
        # Explicit flush between parents and children: the unit of work would
        # otherwise try to insert the asset before its tenant.
        session.add(
            Tenant(
                id=tenant_id,
                name="lifecycle",
                slug="lifecycle-" + tenant_id.hex[:8],
            )
        )
        await session.flush()
        session.add(
            Asset(
                id=asset_id,
                tenant_id=tenant_id,
                asset_type="ip",
                value="203.0.113.77",
            )
        )
        await session.flush()
        session.add(
            Scan(
                id=scan_id,
                tenant_id=tenant_id,
                asset_id=asset_id,
                name="lifecycle",
                scan_type="discovery",
                status="pending",
                config={"host_discovery": True},
                started_at=None,
                completed_at=None,
            )
        )
        await session.flush()
        # H2-T4: the asset needs a verified declaration before it can be dispatched.
        session.add(
            AssetOwnershipDeclaration(
                tenant_id=tenant_id,
                asset_id=asset_id,
                method="declaration",
                token="lifecycle-token",
                status="verified",
                verified_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return tenant_id, asset_id, scan_id


async def _cleanup(tenant_id: UUID, asset_id: UUID, scan_id: UUID) -> None:
    async with get_session_with_tenant(None, True) as session:
        await session.execute(delete(Scan).where(Scan.id == scan_id))
        await session.execute(delete(Asset).where(Asset.id == asset_id))
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await session.commit()


async def _dispatched_at(scan_id: UUID) -> datetime | None:
    """Read the committed dispatch timestamp through a fresh session."""
    async with get_session_with_tenant(None, True) as session:
        return (
            await session.execute(select(Scan.dispatched_at).where(Scan.id == scan_id))
        ).scalar_one_or_none()


def _install_production_lifecycle(app: Any, identity: SimpleNamespace) -> None:
    """Restore the session shape production uses, and stub what it cannot see.

    The real ``get_current_user`` resolves the caller and sets the RLS context
    on the request session. The stub here stands in for it because the
    production-shaped session cannot see fixture rows, so the context it would
    have set is applied explicitly: without it RLS filters every row and the
    endpoint answers 404 for a scan that exists, which is a different bug in the
    test rather than a property of the code under test.
    """

    async def _production_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await set_tenant_context(
                    session,
                    identity.tenant_id,
                    is_superadmin=identity.is_superadmin,
                )
                yield session

    class _RecordingDispatcher:
        def __init__(self) -> None:
            self.calls: list[tuple[UUID, UUID | None]] = []

        async def dispatch(self, scan_id: UUID, tenant_id: UUID | None) -> None:
            self.calls.append((scan_id, tenant_id))

    async def _stub_current_user() -> SimpleNamespace:
        return identity

    dispatcher = _RecordingDispatcher()
    app.dependency_overrides[get_db] = _production_get_db
    app.dependency_overrides[get_current_user] = _stub_current_user
    app.dependency_overrides[get_scan_dispatcher] = lambda: dispatcher
    app.state.lifecycle_dispatcher = dispatcher


async def test_run_answers_202_under_the_production_session_shape(
    tenant_client: AsyncClient,
) -> None:
    """A committed dispatch must answer 202, never 500."""
    app = cast(ASGITransport, tenant_client._transport).app
    tenant_id, asset_id, scan_id = await _seed_committed()
    _install_production_lifecycle(
        app, SimpleNamespace(role="admin", tenant_id=tenant_id, is_superadmin=False)
    )
    try:
        response = await tenant_client.post(f"/api/v1/scans/{scan_id}/run")

        assert response.status_code == 202, response.text

        body = response.json()
        assert body["status"] == "pending"

        # ScanResponse deliberately omits the dispatch timestamp, so the durable
        # effect is verified where it matters: the committed row. Reading it back
        # also proves the commit preceded the bell, which is the ordering the
        # endpoint documents.
        assert (
            await _dispatched_at(scan_id) is not None
        ), "the dispatch must be committed, not merely ringed for"

        dispatcher = app.state.lifecycle_dispatcher
        assert dispatcher.calls == [
            (scan_id, tenant_id)
        ], "the bell is best-effort but it must still be rung"
    finally:
        await _cleanup(tenant_id, asset_id, scan_id)


async def test_cancel_answers_200_under_the_production_session_shape(
    tenant_client: AsyncClient,
) -> None:
    """Cancelling obeys the same rule: no statement after the commit."""
    app = cast(ASGITransport, tenant_client._transport).app
    tenant_id, asset_id, scan_id = await _seed_committed()
    _install_production_lifecycle(
        app, SimpleNamespace(role="admin", tenant_id=tenant_id, is_superadmin=False)
    )
    try:
        response = await tenant_client.post(f"/api/v1/scans/{scan_id}/cancel")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"
    finally:
        await _cleanup(tenant_id, asset_id, scan_id)
