"""Best-effort, bounded enrichment publishing for scans and API callers."""
from __future__ import annotations

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)
PUBLISH_TIMEOUT_SECONDS = 3.0


async def enqueue_enrichment(
    vulnerability_id: str,
    tenant_id: str,
    only_functions: list[str] | None = None,
) -> bool:
    if not settings.ENRICHMENT_ENABLED:
        return False
    try:
        from app.worker.celery_app import ENRICHMENT_QUEUE
        from app.worker.enrichment_tasks import enrich

        await asyncio.wait_for(
            asyncio.to_thread(
                enrich.apply_async,
                args=[vulnerability_id, tenant_id, only_functions],
                queue=ENRICHMENT_QUEUE,
                retry=True,
                retry_policy={
                    "max_retries": 2, "interval_start": 0,
                    "interval_step": 0.5, "interval_max": 1,
                },
            ),
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        return True
    except Exception:
        logger.warning("Enrichment publishing failed")
        return False
