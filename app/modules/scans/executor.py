"""Scan pipeline entry point for the Celery worker.

``POST /scans/{id}/run`` marks the scan as dispatched and rings the
``scans.wake`` bell; the worker claims the row and calls this module. The
pipeline itself lives in ``app.agents.scan_graph``; this module owns the scan
state machine around it: the ``running``/``completed``/``failed``/``cancelled``
transitions, the single commit and the shielded cleanup that survives
cancellation. Cancelling the task running the executor (the worker's
cancellation watcher) reaches the runner's cleanup and terminates the live Nmap
process.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runner import run_agent_safely
from app.agents.scan_graph import (
    NMAP_MAX_OUTPUT_BYTES,
    NMAP_TIMEOUT_SECONDS,
    build_scan_graph,
)
from app.core.database import set_tenant_context
from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from app.modules.scans.nmap.runner import NmapRunResult, run_nmap
from app.modules.scans.state import transition_scan
from app.modules.scans.targets import Resolver

logger = logging.getLogger(__name__)
T = TypeVar("T")
ScanOutcome = Literal["completed", "failed", "cancelled", "skipped"]

__all__ = [
    "NMAP_MAX_OUTPUT_BYTES",
    "NMAP_TIMEOUT_SECONDS",
    "ScanOutcome",
    "execute_scan",
]


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
    claimed: bool = False,
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

    try:
        await _db_phase(session, tenant_id)
        asset = await _load_scan(session, scan_id, tenant_id)
        if asset is None:
            if claimed:
                return await _shielded(fail("asset_missing"))
            return "skipped"
        if not claimed:
            await _db_phase(session, tenant_id)
            if not await transition_scan(session, scan_id, to="running"):
                return "skipped"
            claimed = True
        # A commit anywhere inside the run expires the transaction-local RLS
        # setting, so re-establish it before the graph touches the database.
        await _db_phase(session, tenant_id)
        graph = build_scan_graph(
            session=session,
            tenant_id=tenant_id,
            resolver=resolver,
            nmap_path=nmap_path,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            run=run,
        )
        state = await run_agent_safely(
            graph,
            {
                "scan_id": str(scan_id),
                "tenant_id": str(tenant_id),
                "asset": {"asset_type": asset[0], "value": asset[1]},
            },
        )
        if state.get("error"):
            return await _shielded(fail(state["error"]))
        ok = await transition_scan(
            session,
            scan_id,
            to="completed",
            raw_output=state.get("nmap_raw_xml", ""),
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
    except Exception:
        logger.exception("Unexpected scan failure scan_id=%s", scan_id)
        if not claimed:
            # Never fail a row this executor does not own; let the caller decide.
            raise
        return await _shielded(fail("internal_error"))
