"""Injectable broker boundary; worker imports stay off the API import path."""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

PUBLISH_TIMEOUT_SECONDS = 3.0


class ScanDispatcher(Protocol):
    async def dispatch(self, scan_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Enqueue a scan, raising on delivery failure."""
        ...


class CeleryScanDispatcher:
    """Ring the data-free bell with a bounded request deadline.

    The worker thread may linger until the broker socket timeout; the request
    does not. Retry delays total less than the publishing deadline.
    """

    async def dispatch(self, scan_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        from app.worker.tasks import wake

        await asyncio.wait_for(
            asyncio.to_thread(
                wake.apply_async,
                args=[],
                retry=True,
                retry_policy={
                    "max_retries": 2,
                    "interval_start": 0,
                    "interval_step": 0.5,
                    "interval_max": 1,
                },
            ),
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )


def get_scan_dispatcher() -> ScanDispatcher:
    return CeleryScanDispatcher()
