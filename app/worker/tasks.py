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
from app.modules.scans.state import claim_next_scan
from app.worker.celery_app import celery_app

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


@celery_app.task(name="scans.wake", ignore_result=True)
def wake() -> str:
    return asyncio.run(_wake())
