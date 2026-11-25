"""Tenant-scoped enrichment reads and scan completeness queries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scans.models import Scan
from app.modules.tenants.models import Tenant
from app.modules.vulnerabilities.enrichment_models import VulnerabilityEnrichment
from app.modules.vulnerabilities.models import Vulnerability


async def visible_vulnerability(
    db: AsyncSession, vulnerability_id: UUID, tenant_id: UUID | None,
) -> Vulnerability | None:
    stmt = select(Vulnerability).where(Vulnerability.id == vulnerability_id)
    if tenant_id is not None:
        stmt = stmt.where(Vulnerability.tenant_id == tenant_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def visible_scan(
    db: AsyncSession, scan_id: UUID, tenant_id: UUID | None,
) -> Scan | None:
    stmt = select(Scan).where(Scan.id == scan_id)
    if tenant_id is not None:
        stmt = stmt.where(Scan.tenant_id == tenant_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def tenant_level(db: AsyncSession, tenant_id: UUID) -> str:
    return (await db.execute(
        select(Tenant.ai_enrichment_level).where(Tenant.id == tenant_id)
    )).scalar_one()


async def enrichment_rows(
    db: AsyncSession, vulnerability: Vulnerability, functions: tuple[str, ...],
) -> dict[str, VulnerabilityEnrichment]:
    rows = (await db.execute(
        select(VulnerabilityEnrichment).where(
            VulnerabilityEnrichment.vulnerability_id == vulnerability.id,
            VulnerabilityEnrichment.tenant_id == vulnerability.tenant_id,
            VulnerabilityEnrichment.function.in_(functions),
        )
    )).scalars().all()
    return {row.function: row for row in rows}


async def scan_pending(
    db: AsyncSession, scan: Scan, functions: tuple[str, ...],
) -> tuple[list[Vulnerability], int]:
    scope = (Vulnerability.scan_id == scan.id, Vulnerability.tenant_id == scan.tenant_id)
    total = (await db.execute(
        select(func.count()).select_from(Vulnerability).where(*scope)
    )).scalar_one()
    ok_count = (
        select(func.count())
        .select_from(VulnerabilityEnrichment)
        .where(
            VulnerabilityEnrichment.vulnerability_id == Vulnerability.id,
            VulnerabilityEnrichment.tenant_id == Vulnerability.tenant_id,
            VulnerabilityEnrichment.function.in_(functions),
            VulnerabilityEnrichment.status == "ok",
        )
        .correlate(Vulnerability)
        .scalar_subquery()
    )
    pending = (await db.execute(
        select(Vulnerability).where(*scope, ok_count < len(functions)).order_by(Vulnerability.id)
    )).scalars().all()
    return list(pending), total
