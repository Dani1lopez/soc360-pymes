"""Tests for app/dependencies.py — T3.1: EventBus dependency injection."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fakeredis.aioredis import FakeRedis


class TestGetEventBus:
    """Validate get_event_bus() dependency."""

    @pytest.mark.asyncio
    async def test_get_event_bus_returns_event_bus_instance(self):
        """get_event_bus() MUST return an EventBus instance with a redis client."""
        # Patch get_redis_client so we don't need real Redis
        mock_redis = FakeRedis()
        with patch("app.dependencies.get_redis_client", AsyncMock(return_value=mock_redis)):
            # Import inside to allow patching first
            from app.dependencies import get_event_bus

            result = await get_event_bus()
            from app.event_bus import EventBus

            assert isinstance(result, EventBus)
            assert result._redis is mock_redis
        await mock_redis.aclose()

    @pytest.mark.asyncio
    async def test_get_event_bus_returns_singleton(self):
        """get_event_bus() MUST return the SAME instance on repeated calls."""
        mock_redis = FakeRedis()
        with patch("app.dependencies.get_redis_client", AsyncMock(return_value=mock_redis)):
            from app.dependencies import get_event_bus

            instance1 = await get_event_bus()
            instance2 = await get_event_bus()
            assert instance1 is instance2
        await mock_redis.aclose()

    @pytest.mark.asyncio
    async def test_get_event_bus_singleton_across_multiple_calls(self):
        """get_event_bus() singleton MUST hold across >2 calls."""
        mock_redis = FakeRedis()
        with patch("app.dependencies.get_redis_client", AsyncMock(return_value=mock_redis)):
            from app.dependencies import get_event_bus

            instances = [await get_event_bus() for _ in range(5)]
            assert all(inst is instances[0] for inst in instances)
        await mock_redis.aclose()
