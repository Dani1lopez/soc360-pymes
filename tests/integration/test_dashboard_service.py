"""Dashboard aggregates must remain tenant-scoped even when RLS is bypassed."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from app.modules.assets.models import Asset
from app.modules.dashboard.service import get_dashboard_summary
from app.modules.scans.models import Scan
from app.modules.vulnerabilities.models import Vulnerability
from tests.conftest import TENANT_A_ID, TENANT_B_ID

TENANT_A = UUID(TENANT_A_ID)
TENANT_B = UUID(TENANT_B_ID)
SEVERITIES = ("critical", "high", "medium", "low", "info")


@pytest_asyncio.fixture
async def dashboard_now(db_session: AsyncSession, seed_data) -> datetime:
    await set_tenant_context(db_session, None, is_superadmin=True)
    return (await db_session.execute(text("SELECT now()"))).scalar_one()


async def _asset(
    db: AsyncSession,
    now: datetime,
    *,
    tenant_id: UUID = TENANT_A,
    status: str = "active",
) -> Asset:
    asset = Asset(
        id=uuid4(),
        tenant_id=tenant_id,
        value=f"{uuid4()}.test",
        asset_type="hostname",
        status=status,
        created_at=now,
        updated_at=now,
    )
    db.add(asset)
    await db.flush()
    return asset


async def _scan(
    db: AsyncSession,
    asset: Asset,
    now: datetime,
    *,
    status: str = "completed",
    completed_at: datetime | None = None,
    failure_reason: str | None = None,
) -> Scan:
    scan = Scan(
        id=uuid4(),
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        name=f"scan-{uuid4()}",
        scan_type="vulnerability",
        status=status,
        completed_at=completed_at,
        failure_reason=failure_reason,
        created_at=now,
        updated_at=now,
    )
    db.add(scan)
    await db.flush()
    return scan


async def _vuln(
    db: AsyncSession,
    scan: Scan,
    created_at: datetime,
    *,
    severity: str = "high",
    status: str = "open",
    closed_at: datetime | None = None,
) -> Vulnerability:
    vuln = Vulnerability(
        id=uuid4(),
        tenant_id=scan.tenant_id,
        scan_id=scan.id,
        title="Dashboard finding",
        severity=severity,
        status=status,
        created_at=created_at,
        updated_at=created_at,
        closed_at=closed_at,
    )
    db.add(vuln)
    await db.flush()
    return vuln


async def test_empty_tenant_summary(db_session, dashboard_now):
    now = dashboard_now
    summary = await get_dashboard_summary(db_session, TENANT_A)
    today = now.astimezone(timezone.utc).date()
    assert summary.tenant_id == TENANT_A
    assert summary.generated_at == now
    assert summary.assets_monitored == 0
    assert summary.open_by_severity.model_dump() == dict.fromkeys(SEVERITIES, 0)
    assert (
        summary.coverage_24h.covered,
        summary.coverage_24h.total,
        summary.coverage_24h.ratio,
    ) == (0, 0, None)
    assert summary.coverage_24h.since == now - timedelta(hours=24)
    assert (
        summary.scan_success_30d.completed,
        summary.scan_success_30d.failed,
        summary.scan_success_30d.ratio,
    ) == (0, 0, None)
    assert summary.scan_success_30d.since == now - timedelta(days=30)
    assert [entry.day for entry in summary.trend_30d] == [
        today - timedelta(days=offset) for offset in range(29, -1, -1)
    ]
    assert all(entry.opened == entry.closed == 0 for entry in summary.trend_30d)


async def test_assets_monitored_counts_active_only(db_session, dashboard_now):
    for status in ("active", "active", "inactive", "archived"):
        await _asset(db_session, dashboard_now, status=status)
    summary = await get_dashboard_summary(db_session, TENANT_A)
    assert summary.assets_monitored == 2


async def test_open_by_severity_excludes_non_open_vulns(db_session, dashboard_now):
    asset = await _asset(db_session, dashboard_now)
    scan = await _scan(db_session, asset, dashboard_now)
    for count, severity in enumerate(SEVERITIES, start=1):
        for _ in range(count):
            await _vuln(db_session, scan, dashboard_now, severity=severity)
        for status in ("fixed", "accepted_risk", "false_positive"):
            await _vuln(
                db_session, scan, dashboard_now, severity=severity, status=status
            )
    summary = await get_dashboard_summary(db_session, TENANT_A)
    assert summary.open_by_severity.model_dump() == {
        severity: count for count, severity in enumerate(SEVERITIES, start=1)
    }


async def test_coverage_deduplicates_recent_completed_active_assets(
    db_session, dashboard_now
):
    now = dashboard_now
    covered = await _asset(db_session, now)
    stale = await _asset(db_session, now)
    failed = await _asset(db_session, now)
    inactive = await _asset(db_session, now, status="inactive")
    for hours in (1, 2):
        await _scan(db_session, covered, now, completed_at=now - timedelta(hours=hours))
    await _scan(db_session, stale, now, completed_at=now - timedelta(hours=25))
    await _scan(
        db_session, failed, now, status="failed", completed_at=now - timedelta(hours=1)
    )
    await _scan(db_session, inactive, now, completed_at=now - timedelta(hours=1))
    summary = await get_dashboard_summary(db_session, TENANT_A)
    metric = summary.coverage_24h
    assert (metric.covered, metric.total, metric.ratio) == (1, 3, 0.3333)
    assert metric.since == now - timedelta(hours=24)


async def test_trend_uses_utc_days_and_zero_fills(db_session, dashboard_now):
    now = dashboard_now
    today = now.astimezone(timezone.utc).date()
    asset = await _asset(db_session, now)
    scan = await _scan(db_session, asset, now)
    created = datetime.combine(
        today - timedelta(days=3), datetime.min.time(), timezone.utc
    )
    await _vuln(db_session, scan, created, status="fixed", closed_at=now)
    await _vuln(db_session, scan, now - timedelta(days=31))
    summary = await get_dashboard_summary(db_session, TENANT_A)
    assert [entry.day for entry in summary.trend_30d] == [
        today - timedelta(days=offset) for offset in range(29, -1, -1)
    ]
    for entry in summary.trend_30d:
        assert entry.opened == int(entry.day == today - timedelta(days=3))
        assert entry.closed == int(entry.day == today)


async def test_scan_success_counts_only_completed_and_failed_in_window(
    db_session, dashboard_now
):
    now = dashboard_now
    asset = await _asset(db_session, now)
    await _scan(db_session, asset, now, completed_at=now - timedelta(days=1))
    for reason in (None, "timeout"):
        await _scan(
            db_session,
            asset,
            now,
            status="failed",
            failure_reason=reason,
            completed_at=now - timedelta(days=2),
        )
    for status in ("cancelled", "pending", "running"):
        await _scan(db_session, asset, now, status=status, completed_at=now)
    await _scan(db_session, asset, now, completed_at=now - timedelta(days=31))
    await _scan(
        db_session, asset, now, status="failed", completed_at=now - timedelta(days=31)
    )
    await _scan(db_session, asset, now, status="completed", completed_at=None)
    summary = await get_dashboard_summary(db_session, TENANT_A)
    metric = summary.scan_success_30d
    assert (metric.completed, metric.failed, metric.ratio) == (1, 2, 0.3333)
    assert metric.since == now - timedelta(days=30)


async def test_summary_filters_tenant_explicitly_under_superadmin(
    db_session, dashboard_now
):
    now = dashboard_now
    asset_a = await _asset(db_session, now)
    scan_a = await _scan(db_session, asset_a, now, completed_at=now)
    await _vuln(db_session, scan_a, now, severity="low")
    before = await get_dashboard_summary(db_session, TENANT_A)
    for _ in range(2):
        asset_b = await _asset(db_session, now, tenant_id=TENANT_B)
        scan_b = await _scan(db_session, asset_b, now, completed_at=now)
        await _vuln(
            db_session, scan_b, now, severity="critical", status="fixed", closed_at=now
        )
        await _vuln(db_session, scan_b, now, severity="critical")
        await _scan(db_session, asset_b, now, status="failed", completed_at=now)
    after = await get_dashboard_summary(db_session, TENANT_A)
    assert after.model_dump() == before.model_dump()
    assert after.assets_monitored == 1
    assert after.open_by_severity.model_dump() == {
        **dict.fromkeys(SEVERITIES, 0),
        "low": 1,
    }
    assert (after.coverage_24h.covered, after.coverage_24h.total) == (1, 1)
    assert (after.scan_success_30d.completed, after.scan_success_30d.failed) == (1, 0)
    assert sum(entry.opened for entry in after.trend_30d) == 1
    assert sum(entry.closed for entry in after.trend_30d) == 0
