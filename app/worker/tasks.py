"""Run each task with a NullPool engine in its fresh event loop.

Pooled connections are bound to the event loop that created them, so sharing
an engine across tasks would reuse connections belonging to a closed loop.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import _build_connect_args, set_tenant_context
from app.modules.scans.models import Scan
from app.modules.scans.executor import ScanOutcome, execute_scan
from app.modules.scans.state import claim_next_scan, count_ready_scans, reap_stale_scans
from app.worker.celery_app import (
    MAINTENANCE_HARD_LIMIT_SECONDS,
    MAINTENANCE_SOFT_LIMIT_SECONDS,
    PUMP_MAX_BELLS,
    STALE_SCAN_SECONDS,
    celery_app,
)

logger = logging.getLogger(__name__)
CANCEL_POLL_SECONDS = 5.0


async def _wait_for_cancel(
    engine: AsyncEngine, scan_id: uuid.UUID, tenant_id: uuid.UUID, *, interval: float
) -> None:
    """Poll in short, independent transactions; transient errors are harmless."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    while True:
        try:
            async with maker() as session:
                await set_tenant_context(session, tenant_id, False)
                scan_status = await session.scalar(
                    select(Scan.status).where(Scan.id == scan_id)
                )
            if scan_status == "cancelled":
                return
        except Exception:
            logger.warning("Scan cancellation poll failed; retrying")
        await asyncio.sleep(interval)


class ScanExecutor(Protocol):
    def __call__(
        self,
        session: AsyncSession,
        scan_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        claimed: bool,
    ) -> Awaitable[ScanOutcome]: ...


def build_task_engine() -> AsyncEngine:
    return create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args=_build_connect_args(
            settings.DB_STATEMENT_TIMEOUT_MS, settings.DB_LOCK_TIMEOUT_MS
        ),
    )


async def _wake(
    *,
    engine_factory: Callable[[], AsyncEngine] | None = None,
    claim: Callable[[AsyncSession], Awaitable[tuple[uuid.UUID, uuid.UUID] | None]]
    | None = None,
    execute: ScanExecutor | None = None,
    cancel_poll_seconds: float = CANCEL_POLL_SECONDS,
) -> str:
    engine = (engine_factory or build_task_engine)()
    try:
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as session:
            row = await (claim or claim_next_scan)(session)
        if row is None:
            return "idle"
        scan_id, tenant_id = row
        async with maker() as session:
            executor = asyncio.create_task(
                (execute or execute_scan)(
                    session, scan_id, tenant_id=tenant_id, claimed=True
                )
            )
            watcher = asyncio.create_task(
                _wait_for_cancel(
                    engine, scan_id, tenant_id, interval=cancel_poll_seconds
                )
            )
            try:
                done, _ = await asyncio.wait(
                    (executor, watcher), return_when=asyncio.FIRST_COMPLETED
                )
                if executor in done:
                    return await executor
                executor.cancel()
                await asyncio.gather(executor, return_exceptions=True)
                return "cancelled"
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
                if not executor.done():
                    executor.cancel()
                    await asyncio.gather(executor, return_exceptions=True)
    finally:
        await engine.dispose()


async def _reap(*, engine_factory: Callable[[], AsyncEngine] | None = None) -> int:
    engine = (engine_factory or build_task_engine)()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            count = await reap_stale_scans(
                session, older_than_seconds=STALE_SCAN_SECONDS
            )
        if count > 0:
            logger.warning("Reaped %d stale running scans", count)
        return count
    finally:
        await engine.dispose()


async def _pump(
    *,
    engine_factory: Callable[[], AsyncEngine] | None = None,
    ring: Callable[[], None] | None = None,
) -> int:
    engine = (engine_factory or build_task_engine)()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            count = await count_ready_scans(session, limit=PUMP_MAX_BELLS)
        bell = ring if ring is not None else lambda: wake.apply_async(args=[])
        for _ in range(count):
            bell()
        if count > 0:
            logger.info("Rang %d bells for ready scans", count)
        return count
    finally:
        await engine.dispose()


@celery_app.task(
    name="scans.pump",
    ignore_result=True,
    soft_time_limit=MAINTENANCE_SOFT_LIMIT_SECONDS,
    time_limit=MAINTENANCE_HARD_LIMIT_SECONDS,
)
def pump() -> int:
    return asyncio.run(_pump())


@celery_app.task(
    name="scans.reap",
    ignore_result=True,
    soft_time_limit=MAINTENANCE_SOFT_LIMIT_SECONDS,
    time_limit=MAINTENANCE_HARD_LIMIT_SECONDS,
)
def reap() -> int:
    return asyncio.run(_reap())


@celery_app.task(name="scans.wake", ignore_result=True)
def wake() -> str:
    return asyncio.run(_wake())
