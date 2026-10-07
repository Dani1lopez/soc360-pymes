"""Read-only, tenant-scoped dashboard aggregation."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.models import Asset
from app.modules.dashboard.schemas import (
    CoverageMetric,
    DashboardSummary,
    ScanSuccessMetric,
    SeverityCounts,
    TrendDay,
)
from app.modules.scans.models import Scan
from app.modules.vulnerabilities.models import Vulnerability


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


async def get_dashboard_summary(
    db: AsyncSession, tenant_id: uuid.UUID
) -> DashboardSummary:
    """Aggregate one tenant without relying on RLS or changing transaction state."""
    # One DB clock anchors every metric; Python intervals avoid SQL DST shifts.
    now = (await db.execute(select(func.now()))).scalar_one()
    since_24h = now - timedelta(hours=24)
    since_30d = now - timedelta(days=30)
    today = now.astimezone(timezone.utc).date()
    start_day = today - timedelta(days=29)
    window_start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)

    # Explicit predicates remain required when a superadmin bypasses RLS.
    assets_monitored = (
        await db.execute(
            select(func.count())
            .select_from(Asset)
            .where(Asset.tenant_id == tenant_id, Asset.status == "active")
        )
    ).scalar_one()

    severity_counts = dict(
        (
            await db.execute(
                select(Vulnerability.severity, func.count())
                .where(
                    Vulnerability.tenant_id == tenant_id,
                    Vulnerability.status == "open",
                )
                .group_by(Vulnerability.severity)
            )
        ).all()
    )

    covered = (
        await db.execute(
            select(func.count(func.distinct(Asset.id)))
            .select_from(Asset)
            .join(Scan, Scan.asset_id == Asset.id)
            .where(
                Asset.tenant_id == tenant_id,
                Scan.tenant_id == tenant_id,
                Asset.status == "active",
                Scan.status == "completed",
                Scan.completed_at >= since_24h,
            )
        )
    ).scalar_one()

    opened_day = func.date(func.timezone("UTC", Vulnerability.created_at))
    opened_counts = dict(
        (
            await db.execute(
                select(opened_day, func.count())
                .where(
                    Vulnerability.tenant_id == tenant_id,
                    Vulnerability.created_at >= window_start,
                )
                .group_by(opened_day)
            )
        ).all()
    )
    closed_day = func.date(func.timezone("UTC", Vulnerability.closed_at))
    closed_counts = dict(
        (
            await db.execute(
                select(closed_day, func.count())
                .where(
                    Vulnerability.tenant_id == tenant_id,
                    Vulnerability.closed_at >= window_start,
                )
                .group_by(closed_day)
            )
        ).all()
    )
    trend: list[TrendDay] = []
    for offset in range(30):
        day = start_day + timedelta(days=offset)
        trend.append(
            TrendDay(
                day=day,
                opened=opened_counts.get(day, 0),
                closed=closed_counts.get(day, 0),
            )
        )

    scan_counts = dict(
        (
            await db.execute(
                select(Scan.status, func.count())
                .where(
                    Scan.tenant_id == tenant_id,
                    Scan.completed_at >= since_30d,
                    Scan.status.in_(("completed", "failed")),
                )
                .group_by(Scan.status)
            )
        ).all()
    )
    completed = scan_counts.get("completed", 0)
    failed = scan_counts.get("failed", 0)

    return DashboardSummary(
        tenant_id=tenant_id,
        generated_at=now,
        assets_monitored=assets_monitored,
        open_by_severity=SeverityCounts(**severity_counts),
        coverage_24h=CoverageMetric(
            covered=covered,
            total=assets_monitored,
            ratio=_ratio(covered, assets_monitored),
            since=since_24h,
        ),
        trend_30d=trend,
        scan_success_30d=ScanSuccessMetric(
            completed=completed,
            failed=failed,
            ratio=_ratio(completed, completed + failed),
            since=since_30d,
        ),
    )
