"""Internal helpers for the event bus: retry tracking keys and DLQ drain."""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger

logger = get_logger(__name__)


# Retry tracking key stored in event data
_RETRY_COUNT_KEY = "_retry_count"


# Field name used inside the per-message retry hash (issue #127).
_RETRY_HASH_FIELD = "retry_count"


def _retry_key(event_type: str, message_id: str) -> str:
    """Build the per-message retry counter Redis key.

    Event-type prefix avoids collisions if the same message_id is ever reused
    across streams (e.g. stream MAXLEN trimming that produces a recycled id).
    """
    return f"event_retry:{event_type}:{message_id}"


# Module-level registry of in-flight DLQ write tasks. Holding a strong
# reference here is what prevents the GC from collecting the asyncio.Task
# returned by `asyncio.ensure_future` before the underlying xadd coroutine
# completes — see issue #126.
_INFLIGHT_DLQ: set[asyncio.Task] = set()


async def drain_dlq_tasks(timeout: float = 2.0) -> None:
    """Wait for any in-flight DLQ write tasks to complete.

    Called from the lifespan shutdown path so a fast app shutdown does not
    lose the last DLQ entry. Uses a bounded timeout so a hung Redis write
    cannot block the shutdown forever.
    """
    if not _INFLIGHT_DLQ:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*list(_INFLIGHT_DLQ), return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.error("dlq_drain_timeout", pending=len(_INFLIGHT_DLQ), timeout=timeout)
