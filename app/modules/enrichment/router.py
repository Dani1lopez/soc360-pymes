"""Read enrichment and request asynchronous enrichment for visible findings."""

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.dependencies import DBDep
from app.dependencies.auth import require_any_role
from app.modules.enrichment import queries
from app.modules.enrichment.dispatch import enqueue_enrichment
from app.modules.enrichment.prompts import functions_for_level
from app.modules.enrichment.schemas import (
    EnrichmentItemRead,
    EnrichmentQueued,
    ScanEnrichmentQueued,
    VulnerabilityEnrichmentRead,
)
from app.modules.users.models import User

router = APIRouter(tags=["enrichment"])


class EnrichmentEnqueuer(Protocol):
    async def __call__(
        self, vulnerability_id: str, tenant_id: str,
        only_functions: list[str] | None = None,
    ) -> bool: ...


def get_enrichment_enqueuer() -> EnrichmentEnqueuer:
    return enqueue_enrichment


EnqueuerDep = Annotated[EnrichmentEnqueuer, Depends(get_enrichment_enqueuer)]


def _caller_tenant_id(user: User) -> UUID | None:
    return None if user.is_superadmin else user.tenant_id


def _require_enabled() -> None:
    if not settings.ENRICHMENT_ENABLED:
        raise HTTPException(status_code=503, detail="Enrichment is disabled")


@router.get(
    "/vulnerabilities/{vulnerability_id}/enrichment",
    response_model=VulnerabilityEnrichmentRead,
)
async def get_enrichment(
    vulnerability_id: UUID,
    db: DBDep,
    current_user: User = Depends(require_any_role("admin", "analyst", "viewer", "superadmin")),
) -> VulnerabilityEnrichmentRead:
    vulnerability = await queries.visible_vulnerability(db, vulnerability_id, _caller_tenant_id(current_user))
    if vulnerability is None:
        raise HTTPException(status_code=404, detail="vulnerability not found")
    level = await queries.tenant_level(db, vulnerability.tenant_id)
    functions = functions_for_level(level)
    rows = await queries.enrichment_rows(db, vulnerability, functions)
    return VulnerabilityEnrichmentRead(
        vulnerability_id=vulnerability.id,
        level=level,
        items=[
            EnrichmentItemRead.model_validate(rows[function])
            if function in rows else EnrichmentItemRead(function=function, status="missing")
            for function in functions
        ],
    )


@router.post(
    "/vulnerabilities/{vulnerability_id}/enrichment",
    response_model=EnrichmentQueued,
    status_code=202,
)
async def request_enrichment(
    vulnerability_id: UUID,
    db: DBDep,
    enqueuer: EnqueuerDep,
    current_user: User = Depends(require_any_role("admin", "analyst", "superadmin")),
) -> EnrichmentQueued:
    vulnerability = await queries.visible_vulnerability(db, vulnerability_id, _caller_tenant_id(current_user))
    if vulnerability is None:
        raise HTTPException(status_code=404, detail="vulnerability not found")
    _require_enabled()
    if not await enqueuer(str(vulnerability.id), str(vulnerability.tenant_id)):
        raise HTTPException(status_code=503, detail="Enrichment queue unavailable")
    return EnrichmentQueued(queued=1)


@router.post(
    "/scans/{scan_id}/enrichment",
    response_model=ScanEnrichmentQueued,
    status_code=202,
)
async def request_scan_enrichment(
    scan_id: UUID,
    db: DBDep,
    enqueuer: EnqueuerDep,
    current_user: User = Depends(require_any_role("admin", "analyst", "superadmin")),
) -> ScanEnrichmentQueued:
    scan = await queries.visible_scan(db, scan_id, _caller_tenant_id(current_user))
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    _require_enabled()
    level = await queries.tenant_level(db, scan.tenant_id)
    pending, total = await queries.scan_pending(db, scan, functions_for_level(level))
    for vulnerability in pending:
        if not await enqueuer(str(vulnerability.id), str(vulnerability.tenant_id)):
            raise HTTPException(status_code=503, detail="Enrichment queue unavailable")
    return ScanEnrichmentQueued(queued=len(pending), total=total)
