"""Event bus dependency: singleton factory for EventBus."""
from __future__ import annotations

from app.core.redis import get_redis_client


_event_bus: "EventBus | None" = None


async def get_event_bus() -> "EventBus":
    """Singleton factory for the EventBus dependency."""
    global _event_bus
    if _event_bus is None:
        from app.event_bus import EventBus

        redis = await get_redis_client()
        _event_bus = EventBus(redis)
    return _event_bus
