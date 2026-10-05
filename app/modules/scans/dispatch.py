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
    """Ring the doorbell; the message carries no data."""

    async def dispatch(self, scan_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        from app.worker.tasks import wake

        await asyncio.to_thread(
            wake.apply_async,
            args=[],
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
