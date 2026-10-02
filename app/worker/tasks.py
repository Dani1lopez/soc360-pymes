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

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import _build_connect_args
from app.modules.scans.executor import ScanOutcome, execute_scan
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


class ScanExecutor(Protocol):
    def __call__(
        self, session: AsyncSession, scan_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Awaitable[ScanOutcome]: ...


def build_task_engine() -> AsyncEngine:
    return create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args=_build_connect_args(
            settings.DB_STATEMENT_TIMEOUT_MS, settings.DB_LOCK_TIMEOUT_MS
        ),
    )


async def _run_scan(
    scan_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    engine_factory: Callable[[], AsyncEngine] | None = None,
    execute: ScanExecutor | None = None,
) -> ScanOutcome:
    engine = (engine_factory or build_task_engine)()
    try:
        async with async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )() as session:
            return await (execute or execute_scan)(
                session, scan_id, tenant_id=tenant_id
            )
    finally:
        await engine.dispose()


@celery_app.task(name="scans.run_scan", ignore_result=True)
def run_scan(scan_id: str, tenant_id: str) -> str:
    # uuid.UUID raises AttributeError (not TypeError) for some non-str inputs.
    try:
        if not isinstance(scan_id, str) or not isinstance(tenant_id, str):
            raise TypeError("scan task ids must be strings")
        parsed_scan_id = uuid.UUID(scan_id)
        parsed_tenant_id = uuid.UUID(tenant_id)
    except (ValueError, TypeError):
        logger.warning("Skipping scan task with invalid UUID arguments")
        return "skipped"
    return asyncio.run(_run_scan(parsed_scan_id, parsed_tenant_id))
