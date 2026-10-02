"""Library entry point with no HTTP trigger.

DB-side cancellation is detected at atomic finish, discarding results; live
process termination on DB cancellation belongs to slice 6.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from app.modules.scans.nmap.command import build_nmap_command, split_by_family
from app.modules.scans.nmap.findings import extract_findings
from app.modules.scans.nmap.parser import (
    NmapParseError,
    parse_nmap_xml,
    verify_scan_types,
)
from app.modules.scans.nmap.runner import NmapRunError, NmapRunResult, run_nmap
from app.modules.scans.state import transition_scan
from app.modules.scans.targets import Resolver, TargetRejectedError, resolve_scan_target
from app.modules.vulnerabilities.models import Vulnerability

logger = logging.getLogger(__name__)
NMAP_TIMEOUT_SECONDS = 3600.0
NMAP_MAX_OUTPUT_BYTES = 10 * 1024 * 1024
T = TypeVar("T")
ScanOutcome = Literal["completed", "failed", "cancelled", "skipped"]


async def _db_phase(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    # set_config(..., true) expires after EVERY commit/rollback.
    await set_tenant_context(session, tenant_id)


async def _shielded(cleanup: Awaitable[T]) -> T:
    """Run terminal DB cleanup to completion even if the caller is cancelled.

    A cancellation that arrives meanwhile is re-raised once the cleanup is done,
    so a scan is never left ``running`` by an interrupted failure transition.
    """
    task = asyncio.ensure_future(cleanup)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


async def _load_scan(
    session: AsyncSession, scan_id: uuid.UUID, tenant_id: uuid.UUID
) -> tuple[str, str] | None:
    result = await session.execute(
        select(Asset.asset_type, Asset.value)
        .join(Scan, (Scan.asset_id == Asset.id) & (Scan.tenant_id == Asset.tenant_id))
        .where(Scan.id == scan_id, Scan.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row is not None else None


async def execute_scan(
    session: AsyncSession,
    scan_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
    resolver: Resolver | None = None,
    nmap_path: str = "nmap",
    timeout: float = NMAP_TIMEOUT_SECONDS,
    max_output_bytes: int = NMAP_MAX_OUTPUT_BYTES,
    run: Callable[..., Awaitable[NmapRunResult]] = run_nmap,
) -> ScanOutcome:
    async def fail(reason: str) -> ScanOutcome:
        await session.rollback()
        await _db_phase(session, tenant_id)
        ok = await transition_scan(session, scan_id, to="failed", failure_reason=reason)
        return "failed" if ok else "cancelled"

    async def cancel() -> None:
        await session.rollback()
        await _db_phase(session, tenant_id)
        await transition_scan(session, scan_id, to="cancelled")

    claimed = False
    try:
        await _db_phase(session, tenant_id)
        asset = await _load_scan(session, scan_id, tenant_id)
        if asset is None:
            return "skipped"
        await _db_phase(session, tenant_id)
        if not await transition_scan(session, scan_id, to="running"):
            return "skipped"
        claimed = True
        target = await resolve_scan_target(*asset, resolver=resolver)
        documents = []
        drafts = []
        for family in split_by_family(target):
            argv = build_nmap_command(family, nmap_path=nmap_path)
            result = await run(argv, timeout=timeout, max_output_bytes=max_output_bytes)
            report = parse_nmap_xml(result.stdout)
            verify_scan_types(report)
            documents.append(result.stdout.decode("utf-8", errors="replace"))
            drafts.extend(extract_findings(report))
        await _db_phase(session, tenant_id)
        for draft in drafts:
            session.add(
                Vulnerability(
                    tenant_id=tenant_id,
                    scan_id=scan_id,
                    title=draft.title,
                    description=draft.description,
                    severity=draft.severity,
                    cve_id=draft.cve_id,
                    cvss_score=draft.cvss_score,
                    vulnerability_metadata=draft.metadata,
                )
            )
        await session.flush()
        ok = await transition_scan(
            session,
            scan_id,
            to="completed",
            raw_output="\n".join(documents),
            commit=False,
        )
        if not ok:
            await session.rollback()
            return "cancelled"
        await session.commit()
        return "completed"
    except asyncio.CancelledError:
        # Only a scan this executor claimed may be cancelled; before the claim
        # the row is still pending (or owned by another executor) and untouched.
        if claimed:
            await _shielded(cancel())
        raise
    except NmapRunError as exc:
        logger.warning(
            "Nmap scan_id=%s reason=%s detail=%s", scan_id, exc.reason, exc.detail
        )
        return await _shielded(fail(exc.reason))
    except (TargetRejectedError, NmapParseError) as exc:
        return await _shielded(fail(exc.reason))
    except Exception:
        logger.exception("Unexpected scan failure scan_id=%s", scan_id)
        return await _shielded(fail("internal_error"))
