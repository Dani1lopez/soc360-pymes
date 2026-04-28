"""Tests for app/main.py lifespan — T3.2: Consumer lifecycle in FastAPI lifespan."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fakeredis.aioredis import FakeRedis


class TestLifespanConsumerLifecycle:
    """Validate that the FastAPI lifespan starts/stops the event consumer correctly."""

    @pytest.mark.asyncio
    async def test_lifespan_starts_consumer_on_startup(self):
        """Lifespan MUST start the event consumer background task on startup."""
        from app.main import lifespan

        mock_redis = FakeRedis()

        # Track whether consumer was started
        consumer_started = False
        consumer_instance = None

        class MockEventConsumer:
            def __init__(self, **kwargs):
                nonlocal consumer_started, consumer_instance
                consumer_started = True
                consumer_instance = self
                # Store kwargs for verification
                self.kwargs = kwargs

        with patch("app.main.ping_redis", AsyncMock(return_value=True)):
            with patch("app.main.get_redis_client", AsyncMock(return_value=mock_redis)):
                with patch("app.main.EventConsumer", MockEventConsumer):
                    with patch("app.main.asyncio.Event") as MockEvent:
                        mock_stop_event = MagicMock()
                        MockEvent.return_value = mock_stop_event

                        app = MagicMock()
                        async with lifespan(app):
                            # Yield to event loop so background task is scheduled
                            await asyncio.sleep(0)
                            assert consumer_started, "EventConsumer should have been instantiated"

        await mock_redis.aclose()

    @pytest.mark.asyncio
    async def test_lifespan_stops_consumer_on_shutdown(self):
        """Lifespan MUST set the stop event and wait for consumer task on shutdown."""
        from app.main import lifespan

        mock_redis = FakeRedis()
        stop_event_set = False
        task_waited_for = False

        # Pre-create a real asyncio Event to coordinate is_set() across patches
        real_stop_event = asyncio.Event()

        class MockStopEvent:
            def set(self):
                nonlocal stop_event_set
                stop_event_set = True
                real_stop_event.set()
            def is_set(self):
                return real_stop_event.is_set()

        async def mock_wait_for(coro, timeout):
            nonlocal task_waited_for
            task_waited_for = True
            # Await a real task to avoid the TypeError
            return await asyncio.sleep(0)

        # Create a real task that finishes immediately
        async def make_fake_task(coro, *, name=None):
            async def noop():
                return None
            return asyncio.create_task(noop())

        with patch("app.main.ping_redis", AsyncMock(return_value=True)):
            with patch("app.main.get_redis_client", AsyncMock(return_value=mock_redis)):
                with patch("app.main.EventConsumer"):
                    with patch("app.main.asyncio.create_task", side_effect=make_fake_task):
                        with patch("app.main.asyncio.wait_for", mock_wait_for):
                            with patch("app.main.asyncio.Event", return_value=MockStopEvent()):
                                with patch("app.main.close_pool", AsyncMock()):
                                    app = MagicMock()
                                    async with lifespan(app):
                                        # Inside lifespan (startup done)
                                        pass
                                    # After exiting (shutdown done)
                                    assert stop_event_set, "Stop event must be set on shutdown"
                                    assert task_waited_for, "Consumer task must have been waited on"

        await mock_redis.aclose()

    @pytest.mark.asyncio
    async def test_lifespan_raises_if_redis_unavailable(self):
        """Lifespan MUST raise RuntimeError if Redis ping fails on startup."""
        from app.main import lifespan

        with patch("app.main.ping_redis", AsyncMock(return_value=False)):
            app = MagicMock()
            with pytest.raises(RuntimeError, match="No se puede conectar a Redis"):
                async with lifespan(app):
                    pass  # Should not reach here

    @pytest.mark.asyncio
    async def test_lifespan_close_pool_called_on_shutdown(self):
        """Lifespan MUST call close_pool() on shutdown."""
        from app.main import lifespan

        mock_redis = FakeRedis()

        with patch("app.main.ping_redis", AsyncMock(return_value=True)):
            with patch("app.main.get_redis_client", AsyncMock(return_value=mock_redis)):
                with patch("app.main.EventConsumer"):
                    with patch("app.main.asyncio.create_task", return_value=MagicMock(done=True)):
                        with patch("app.main.asyncio.wait_for", AsyncMock()):
                            with patch("app.main.asyncio.Event", return_value=MagicMock()):
                                with patch("app.main.close_pool", AsyncMock()) as mock_close_pool:
                                    app = MagicMock()
                                    async with lifespan(app):
                                        pass
                                    assert mock_close_pool.called, "close_pool must be called on shutdown"

        await mock_redis.aclose()
