"""Best-effort, bounded enrichment publishing for scans and API callers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)
PUBLISH_TIMEOUT_SECONDS = 3.0


def enrichment_inflight_key(tenant_id: str, vulnerability_id: str) -> str:
    return f"enrichment:inflight:{tenant_id}:{vulnerability_id}"


def enrichment_dedup_ttl_seconds() -> int:
    return max(1, settings.ENRICHMENT_BUDGET_SECONDS + 30)


async def acquire_enrichment_slot(
    redis: Redis,
    tenant_id: str,
    vulnerability_id: str,
) -> bool:
    """Atomically reserve an in-flight enrichment slot for a vulnerability."""
    key = enrichment_inflight_key(tenant_id, vulnerability_id)
    try:
        acquired = await redis.set(
            key,
            "1",
            nx=True,
            ex=enrichment_dedup_ttl_seconds(),
        )
        return bool(acquired)
    except Exception:
        logger.warning("Enrichment dedup acquire failed; failing open")
        return True


async def release_enrichment_slot(
    redis: Redis,
    tenant_id: str,
    vulnerability_id: str,
) -> None:
    """Best-effort release of an in-flight slot after an enqueue failure."""
    key = enrichment_inflight_key(tenant_id, vulnerability_id)
    try:
        await redis.delete(key)
    except Exception:
        logger.warning("Enrichment dedup release failed")


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
                    "max_retries": 2,
                    "interval_start": 0,
                    "interval_step": 0.5,
                    "interval_max": 1,
                },
            ),
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        return True
    except Exception:
        logger.warning("Enrichment publishing failed")
        return False
