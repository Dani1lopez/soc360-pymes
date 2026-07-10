from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.modules.assets.models import Asset
from app.modules.reports.models import Report
from app.modules.scans.models import Scan
from app.modules.vulnerabilities.models import Vulnerability
from tests.conftest import TENANT_A_ID, TENANT_B_ID


async def _enable_superadmin(session) -> None:
    await session.execute(text("SET LOCAL app.is_superadmin = 'true'"))


async def test_vulnerability_rejects_cross_tenant_scan(
    db_session,
    seed_data,
):
    """DB must reject a vulnerability whose tenant does not match its scan's tenant."""
    await _enable_superadmin(db_session)

    tenant_a = UUID(TENANT_A_ID)
    tenant_b = UUID(TENANT_B_ID)

    asset_b = Asset(
        id=uuid.uuid4(), tenant_id=tenant_b, name="asset-b", asset_type="host"
    )
    db_session.add(asset_b)
    await db_session.flush()

    scan_b = Scan(
        id=uuid.uuid4(),
        tenant_id=tenant_b,
        asset_id=asset_b.id,
        name="scan-b",
        scan_type="vulnerability",
    )
    db_session.add(scan_b)
    await db_session.flush()

    vuln = Vulnerability(
        id=uuid.uuid4(),
        tenant_id=tenant_a,
        scan_id=scan_b.id,
        title="cross-tenant vuln",
        severity="high",
    )
    db_session.add(vuln)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


async def test_report_rejects_cross_tenant_asset(
    db_session,
    seed_data,
):
    """DB must reject a report whose tenant does not match its asset's tenant."""
    await _enable_superadmin(db_session)

    tenant_a = UUID(TENANT_A_ID)
    tenant_b = UUID(TENANT_B_ID)

    asset_b = Asset(
        id=uuid.uuid4(), tenant_id=tenant_b, name="asset-b", asset_type="host"
    )
    db_session.add(asset_b)
    await db_session.flush()

    report = Report(
        id=uuid.uuid4(),
        tenant_id=tenant_a,
        asset_id=asset_b.id,
        name="cross-tenant report",
        report_type="vulnerability",
    )
    db_session.add(report)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


async def test_scan_rejects_cross_tenant_asset(db_session, seed_data):
    """DB must reject a scan whose tenant does not match its asset's tenant."""
    await _enable_superadmin(db_session)
    tenant_a = UUID(TENANT_A_ID)
    tenant_b = UUID(TENANT_B_ID)
    asset_b = Asset(
        id=uuid.uuid4(), tenant_id=tenant_b, name="asset-b", asset_type="host"
    )
    db_session.add(asset_b)
    await db_session.flush()
    db_session.add(
        Scan(
            id=uuid.uuid4(),
            tenant_id=tenant_a,
            asset_id=asset_b.id,
            name="cross-tenant scan",
            scan_type="vulnerability",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_scan_rejects_cross_tenant_asset_reassignment(db_session, seed_data):
    """DB must reject updating a scan's asset_id to another tenant's asset."""
    await _enable_superadmin(db_session)
    tenant_a = UUID(TENANT_A_ID)
    tenant_b = UUID(TENANT_B_ID)
    asset_a = Asset(
        id=uuid.uuid4(), tenant_id=tenant_a, name="asset-a", asset_type="host"
    )
    asset_b = Asset(
        id=uuid.uuid4(), tenant_id=tenant_b, name="asset-b", asset_type="host"
    )
    scan = Scan(
        id=uuid.uuid4(),
        tenant_id=tenant_a,
        asset_id=asset_a.id,
        name="reassign-scan",
        scan_type="vulnerability",
    )
    db_session.add_all([asset_a, asset_b, scan])
    await db_session.flush()
    scan.asset_id = asset_b.id
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_scan_same_tenant_asset_and_cascade(db_session, seed_data):
    """Same-tenant scans remain valid and cascade when their asset is deleted."""
    await _enable_superadmin(db_session)
    tenant_a = UUID(TENANT_A_ID)
    asset = Asset(
        id=uuid.uuid4(), tenant_id=tenant_a, name="asset-a", asset_type="host"
    )
    scan = Scan(
        id=uuid.uuid4(),
        tenant_id=tenant_a,
        asset_id=asset.id,
        name="same-tenant scan",
        scan_type="vulnerability",
    )
    db_session.add_all([asset, scan])
    await db_session.flush()
    await db_session.delete(asset)
    await db_session.flush()
    remaining_scan = await db_session.scalar(select(Scan).where(Scan.id == scan.id))
    assert remaining_scan is None
