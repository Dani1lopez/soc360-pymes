"""Injectable broker boundary; worker imports stay off the API import path."""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol


class ScanDispatcher(Protocol):
    async def dispatch(self, scan_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Enqueue a scan, raising on delivery failure."""
        ...


class CeleryScanDispatcher:
    async def dispatch(self, scan_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        from app.worker.tasks import run_scan

        await asyncio.to_thread(
            run_scan.apply_async,
            args=[str(scan_id), str(tenant_id)],
            retry=True,
            retry_policy={
                "max_retries": 2,
                "interval_start": 0,
                "interval_step": 0.5,
                "interval_max": 1,
            },
        )


def get_scan_dispatcher() -> ScanDispatcher:
    return CeleryScanDispatcher()
