"""Tests for app/main.py lifespan — T3.2: Consumer lifecycle in FastAPI lifespan."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fakeredis.aioredis import FakeRedis


@pytest.mark.asyncio
async def test_cancellation_closes_redis_once(monkeypatch):
    """SIGTERM (task.cancel) must close the Redis client exactly once and drain the pool.

    This is the canonical test for issue #129. It covers 4 invariants in a single
    function: (1) the loop starts via create_task, (2) SIGTERM arrives via task.cancel,
    (3) the finally block calls aclose exactly once (close_calls == [1]), and
    (4) the connection pool has no leaked connections (_created_connections == 0).
    """
    from app.main import _consumer_loop

    fakeredis_client = FakeRedis()
    close_calls = []
    monkeypatch.setattr(
        fakeredis_client,
        "aclose",
        AsyncMock(side_effect=lambda: close_calls.append(1)),
    )

    # Mock the consumer to do nothing (no pending messages, no acks)
    mock_consumer = MagicMock()
    mock_consumer.read_pending = AsyncMock(return_value=[])
    mock_consumer.ack = AsyncMock()

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _consumer_loop(
            redis_client=fakeredis_client,
            consumer=mock_consumer,
            stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.05)  # let it spin once

    # SIGTERM arrives
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # aclose was awaited exactly once
    assert close_calls == [1], f"aclose must be called exactly once, got {close_calls}"
    # No leaked connections in the pool
    created_connections = getattr(
        fakeredis_client.connection_pool,
        "_created_connections",
        len(fakeredis_client.connection_pool._in_use_connections),
    )
    assert created_connections == 0, (
        "Connection pool must be drained (no leaked connections)"
    )


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

        scheduled_tasks = []

        def fake_create_task(coro, *, name=None):
            # Capture the scheduled coroutine and discard it so the test does
            # not leak a real background task or an unawaited coroutine.
            scheduled_tasks.append((coro, name))
            coro.close()
            return MagicMock(done=True)

        with patch("app.main.ping_redis", AsyncMock(return_value=True)):
            with patch("app.main.get_redis_client", AsyncMock(return_value=mock_redis)):
                with patch("app.main.EventConsumer", MockEventConsumer):
                    with patch("app.main.asyncio.Event") as MockEvent:
                        mock_stop_event = MagicMock()
                        MockEvent.return_value = mock_stop_event
                        # Avoid a real background task; CI closes the per-test loop
                        # before an uncontrolled task finishes, raising
                        # "RuntimeError: Event loop is closed".
                        with patch("app.main.asyncio.create_task", side_effect=fake_create_task):
                            with patch("app.main.asyncio.wait_for", AsyncMock()):
                                # Do not touch the global Redis pool on shutdown; earlier tests
                                # may have created it on a now-closed event loop.
                                with patch("app.main.close_pool", AsyncMock()):
                                    app = MagicMock()
                                    async with lifespan(app):
                                        assert consumer_started, "EventConsumer should have been instantiated"
                                        assert scheduled_tasks, "Consumer background task must be scheduled"
                                        coro, task_name = scheduled_tasks[0]
                                        assert coro.__name__ == "_consumer_loop"
                                        assert task_name == "event-consumer"

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

        def make_fake_task(coro, *, name=None):
            # Discard the real consumer loop coroutine so it is not leaked as
            # an unawaited coroutine; return a mock task since wait_for is patched.
            coro.close()
            return MagicMock(done=True)

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

        def fake_create_task(coro, *, name=None):
            # Discard the consumer loop coroutine so it is not leaked.
            coro.close()
            return MagicMock(done=True)

        with patch("app.main.ping_redis", AsyncMock(return_value=True)):
            with patch("app.main.get_redis_client", AsyncMock(return_value=mock_redis)):
                with patch("app.main.EventConsumer"):
                    with patch("app.main.asyncio.create_task", side_effect=fake_create_task):
                        with patch("app.main.asyncio.wait_for", AsyncMock()):
                            with patch("app.main.asyncio.Event", return_value=MagicMock()):
                                with patch("app.main.close_pool", AsyncMock()) as mock_close_pool:
                                    app = MagicMock()
                                    async with lifespan(app):
                                        pass
                                    assert mock_close_pool.called, "close_pool must be called on shutdown"

        await mock_redis.aclose()
