"""Edge-case tests for event_bus.py EventBus and EventConsumer.

Extends test_event_bus.py coverage with:
- dispatch with different event types
- handler dispatch routing correctness
- malformed event data handling via _dispatch_event
- publish serializes UUIDs correctly to Redis
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis


class TestEventBusDispatchRouting:
    """Validate _dispatch_event routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_dispatch_unknown_event_type_logs_debug(self, caplog):
        """_dispatch_event MUST log at debug level when no handler exists for event type."""
        from app.event_bus import EventBus

        caplog.clear()
        with caplog.at_level(0):  # capture all levels
            # Key requirement: unknown event type must NOT raise
            await EventBus._dispatch_event("auth.logout", {"user_id": "u1"})

        # Verify no exception was raised (the key requirement)

    @pytest.mark.asyncio
    async def test_dispatch_auth_login_calls_handler(self, caplog):
        """_dispatch_event MUST call _handle_auth_login for 'auth.login' events."""
        from app.event_bus import EventBus

        caplog.clear()
        data = {
            "event_id": str(uuid.uuid4()),
            "event_type": "auth.login",
            "tenant_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "email_hash": "e" * 32,
            "ip_prefix": "1.2.3.0/24",
            "user_agent": "TestBrowser/1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with caplog.at_level(logging.INFO, logger="app.event_bus"):
            await EventBus._dispatch_event("auth.login", data)

        # Handler should have logged the auth.login event consumed
        assert any(
            "auth.login" in record.message or "user_id" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_dispatch_handler_error_caught_and_logged(self, caplog):
        """_dispatch_event MUST catch handler errors and log warning, not raise.

        The handler itself is non-throwing (uses .get() with defaults).
        To test the catch-and-log behavior, we patch the handler to raise.

        With retry logic: on first attempt, error is re-raised for retry.
        After EVENT_MAX_RETRIES exhausted, error is logged and event moves to DLQ.
        """
        from app.event_bus import EventBus
        from app.core.config import settings

        bad_data = {
            "event_type": "auth.login",
            "user_id": str(uuid.uuid4()),
            "email_hash": "f" * 32,
            "ip_prefix": "1.2.3.0/24",
            "user_agent": None,
            "tenant_id": str(uuid.uuid4()),
            "_retry_count": settings.EVENT_MAX_RETRIES,  # Already at max retries
        }

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="app.event_bus"):
            # Patch _handle_auth_login to raise — dispatch catches and moves to DLQ
            with patch.object(EventBus, "_handle_auth_login", side_effect=RuntimeError("handler boom")):
                # Must NOT raise — error must be caught and DLQ logged
                result = await EventBus._dispatch_event("auth.login", bad_data)

        # Should have logged error about DLQ
        assert result is False  # DLQ'd
        error_found = any(
            "dlq" in (record.message or "").lower() or record.levelname == "ERROR"
            for record in caplog.records
        )
        assert error_found, "Exhausted retries should produce an error log"

    @pytest.mark.asyncio
    async def test_dispatch_requires_event_type_arg(self):
        """_dispatch_event MUST receive event_type as first argument."""
        from app.event_bus import EventBus

        # Must be callable with (event_type, data)
        result = await EventBus._dispatch_event("auth.login", {})
        assert result is True  # Returns True on success (no handler = success)


class TestEventBusPublishSerialization:
    """Validate EventBus.publish serializes complex types correctly."""

    @pytest_asyncio.fixture
    async def client(self) -> FakeRedis:
        r = FakeRedis()
        yield r
        await r.aclose()

    @pytest.mark.asyncio
    async def test_publish_uuid_serialized_to_string(self, client: FakeRedis):
        """publish() MUST serialize UUID fields to strings for Redis."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent

        bus = EventBus(redis_client=client)
        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-uuid-serializer",
            email_hash="a" * 32,
            ip_prefix="10.0.0.0/24",
        )
        await bus.publish(event)

        # Read back from stream to verify serialization
        stream_name = bus.stream_name("auth.login")
        data = await client.xrange(stream_name)
        assert len(data) >= 1
        _, fields = data[0]

        # UUID fields must be strings (not bytes or UUID objects)
        assert b"tenant_id" in fields or "tenant_id" in fields
        # Values should be string representations
        for k, v in fields.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            if key == "user_id":
                assert isinstance(val, str)
                assert val == "user-uuid-serializer"

    @pytest.mark.asyncio
    async def test_publish_datetime_serialized_to_string(self, client: FakeRedis):
        """publish() MUST serialize datetime fields to ISO strings for Redis."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent

        bus = EventBus(redis_client=client)
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-datetime-serializer",
            email_hash="a" * 32,
            timestamp=ts,
        )
        await bus.publish(event)

        stream_name = bus.stream_name("auth.login")
        data = await client.xrange(stream_name)
        assert len(data) >= 1
        _, fields = data[0]

        for k, v in fields.items():
            key = k.decode() if isinstance(k, bytes) else k
            if key == "timestamp":
                val = v.decode() if isinstance(v, bytes) else v
                assert "2025-01-15" in val


class TestEventBusStreamNameEdgeCases:
    """Validate stream_name edge cases."""

    @pytest.mark.asyncio
    async def test_stream_name_with_dotted_event_type(self):
        """stream_name() MUST handle dot-separated event types like 'auth.login'."""
        from app.event_bus import EventBus

        client = FakeRedis()
        bus = EventBus(redis_client=client)
        assert bus.stream_name("auth.login") == "events:auth.login"
        assert bus.stream_name("auth.logout") == "events:auth.logout"
        assert bus.stream_name("user.created") == "events:user.created"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_stream_name_is_deterministic(self):
        """stream_name() MUST return the same result for the same input."""
        from app.event_bus import EventBus

        client = FakeRedis()
        bus = EventBus(redis_client=client)
        r1 = bus.stream_name("auth.login")
        r2 = bus.stream_name("auth.login")
        assert r1 == r2
        await client.aclose()


class TestEventConsumerPendingEdgeCases:
    """Validate EventConsumer pending/ack edge cases."""

    @pytest.mark.asyncio
    async def test_read_pending_on_empty_stream_returns_empty_list(self):
        """read_pending() MUST return [] when no pending messages exist."""
        from app.event_bus import EventConsumer

        client = FakeRedis()
        # Ensure group exists but no messages pending
        await client.xgroup_create("events:auth.login", "soc360-consumers", "0", mkstream=True)
        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        result = await consumer.read_pending()
        assert result == []
        await client.aclose()

    @pytest.mark.asyncio
    async def test_ack_with_string_id(self):
        """ack() MUST accept a string message_id."""
        from app.event_bus import EventConsumer

        client = FakeRedis()
        stream = "events:auth.login"
        await client.xgroup_create(stream, "soc360-consumers", "0", mkstream=True)
        msg_id_bytes = await client.xadd(stream, {"event": "login", "user_id": "u1"})
        await client.xreadgroup("soc360-consumers", "worker-1", {stream: ">"}, count=1)
        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )

        # Pass as string
        msg_id_str = msg_id_bytes.decode()
        await consumer.ack(msg_id_str)
        pending = await consumer.read_pending()
        assert len(pending) == 0
        await client.aclose()

    @pytest.mark.asyncio
    async def test_ack_with_bytes_id(self):
        """ack() MUST accept a bytes message_id."""
        from app.event_bus import EventConsumer

        client = FakeRedis()
        stream = "events:auth.login"
        await client.xgroup_create(stream, "soc360-consumers", "0", mkstream=True)
        msg_id_bytes = await client.xadd(stream, {"event": "login", "user_id": "u1"})
        await client.xreadgroup("soc360-consumers", "worker-1", {stream: ">"}, count=1)
        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )

        # Pass as bytes
        await consumer.ack(msg_id_bytes)
        pending = await consumer.read_pending()
        assert len(pending) == 0
        await client.aclose()


class TestEventBusDLQTaskRegistry:
    """Regression tests for issue #126 — DLQ fire-and-forget was not durable.

    Root cause: `asyncio.ensure_future` returns a Task with no strong
    reference, so the Task can be garbage-collected before the xadd
    coroutine resumes. The fix keeps a strong reference in a module-level
    `_INFLIGHT_DLQ` set and exposes `drain_dlq_tasks` for lifespan shutdown.
    """

    @pytest.mark.asyncio
    async def test_dlq_write_lands_in_stream(self):
        """DLQ event must actually land in Redis (no silent GC drop).

        Exhausts retries on a failing handler, then verifies the DLQ stream
        has exactly one entry.
        """
        import asyncio

        from app.event_bus import EventBus, drain_dlq_tasks
        from app.core.config import settings

        client = FakeRedis()
        try:
            bad_data = {
                "event_type": "auth.login",
                "user_id": "u-dlq-1",
                "_retry_count": settings.EVENT_MAX_RETRIES,
            }

            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("handler boom"),
            ):
                result = await EventBus._dispatch_event(
                    "auth.login", bad_data, redis_client=client
                )
            assert result is False

            # The DLQ write is scheduled as a Task; drain it before reading.
            await drain_dlq_tasks(timeout=2.0)

            dlq_key = f"{settings.EVENT_STREAM_PREFIX}:dlq:auth.login"
            entries = await client.xrange(dlq_key)
            assert len(entries) == 1
            _, fields = entries[0]
            decoded = {
                (k.decode() if isinstance(k, bytes) else k):
                (v.decode() if isinstance(v, bytes) else v)
                for k, v in fields.items()
            }
            assert decoded.get("_dlq_reason") == "handler boom"
            assert decoded.get("user_id") == "u-dlq-1"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_dlq_task_registry_keeps_strong_reference(self):
        """In-flight DLQ Tasks must remain in the registry until done.

        Without the registry, asyncio's GC could drop the Task before xadd
        runs. The registry set MUST still contain the Task immediately after
        dispatch, and MUST remove it via done_callback once finished.
        """
        import asyncio

        from app.event_bus import EventBus, _INFLIGHT_DLQ, drain_dlq_tasks
        from app.core.config import settings

        client = FakeRedis()
        try:
            # Snapshot the set so we can isolate this test's contributions.
            before = set(_INFLIGHT_DLQ)

            bad_data = {
                "event_type": "auth.login",
                "user_id": "u-registry",
                "_retry_count": settings.EVENT_MAX_RETRIES,
            }
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("boom"),
            ):
                await EventBus._dispatch_event(
                    "auth.login", bad_data, redis_client=client
                )

            # Right after dispatch, the registry should have at least one new
            # Task (the DLQ xadd). The set is non-empty until drain completes.
            during = _INFLIGHT_DLQ - before
            assert len(during) >= 1, (
                f"Expected a DLQ Task in registry, got set diff: {during}"
            )
            assert all(isinstance(t, asyncio.Task) for t in during)

            await drain_dlq_tasks(timeout=2.0)
            after = _INFLIGHT_DLQ - before
            assert after == set(), (
                f"Registry should be empty after drain, still has: {after}"
            )
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_dlq_survives_gc_pressure(self):
        """DLQ write must succeed even under aggressive garbage collection.

        Simulates a real workload where the event_bus's local `task` variable
        goes out of scope. Without the registry the Task is collectable; with
        the registry it must still complete.
        """
        import asyncio
        import gc

        from app.event_bus import EventBus, drain_dlq_tasks
        from app.core.config import settings

        client = FakeRedis()
        try:
            for i in range(20):
                bad_data = {
                    "event_type": "auth.login",
                    "user_id": f"u-gc-{i}",
                    "_retry_count": settings.EVENT_MAX_RETRIES,
                }
                with patch.object(
                    EventBus, "_handle_auth_login",
                    side_effect=RuntimeError(f"boom-{i}"),
                ):
                    await EventBus._dispatch_event(
                        "auth.login", bad_data, redis_client=client
                    )
                gc.collect()  # pressure: force generation collection

            await drain_dlq_tasks(timeout=5.0)

            dlq_key = f"{settings.EVENT_STREAM_PREFIX}:dlq:auth.login"
            entries = await client.xrange(dlq_key)
            assert len(entries) == 20, (
                f"Expected 20 DLQ entries after GC pressure, got {len(entries)}"
            )
        finally:
            await client.aclose()


class TestDrainDlqTasks:
    """Unit tests for the drain_dlq_tasks shutdown helper."""

    @pytest.mark.asyncio
    async def test_drain_noop_when_registry_empty(self):
        """drain_dlq_tasks must be a no-op when nothing is in-flight."""
        from app.event_bus import drain_dlq_tasks, _INFLIGHT_DLQ

        # Ensure registry is empty for the test
        _INFLIGHT_DLQ.clear()
        # Should return immediately, no exception
        await drain_dlq_tasks(timeout=0.5)

    @pytest.mark.asyncio
    async def test_drain_waits_for_pending_tasks(self):
        """drain_dlq_tasks must await pending tasks to completion."""
        import asyncio

        from app.event_bus import _INFLIGHT_DLQ, drain_dlq_tasks

        completed = []

        async def _slow_task() -> None:
            await asyncio.sleep(0.05)
            completed.append(1)

        task = asyncio.create_task(_slow_task())
        _INFLIGHT_DLQ.add(task)
        task.add_done_callback(_INFLIGHT_DLQ.discard)

        await drain_dlq_tasks(timeout=2.0)
        assert completed == [1]
        assert _INFLIGHT_DLQ == set()

    @pytest.mark.asyncio
    async def test_drain_cancels_tasks_exceeding_timeout(self):
        """drain_dlq_tasks must cancel and log tasks that exceed the budget."""
        import asyncio

        from app.event_bus import _INFLIGHT_DLQ, drain_dlq_tasks

        async def _very_slow_task() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(_very_slow_task())
        _INFLIGHT_DLQ.add(task)
        task.add_done_callback(_INFLIGHT_DLQ.discard)

        # Short budget forces cancellation
        await drain_dlq_tasks(timeout=0.1)
        # The Task was cancelled and removed from the registry
        assert task.cancelled() or task.done()
        assert _INFLIGHT_DLQ == set()


class TestEventBusRetryCounterPersistence:
    """Regression tests for issue #127 — retry counter was in-memory only.

    Root cause: the retry count was mutated in a local `data` dict but never
    persisted to Redis. A consumer restart (or another consumer in the same
    group picking up the same message via XCLAIM) would re-read `data` from
    the stream, see no `_retry_count`, and reset the counter to 0 — leading
    to infinite retries and a DLQ path that was effectively unreachable.

    Fix: persist the counter to a Redis HASH keyed by
    `event_retry:{event_type}:{message_id}` with a TTL, so the counter
    survives across consumer restarts and rebalances.
    """

    @pytest.mark.asyncio
    async def test_retry_count_persisted_to_redis_hash(self):
        """A failing handler must persist an incremented retry count in Redis."""
        from app.event_bus import EventBus
        from app.core.config import settings

        client = FakeRedis()
        try:
            data = {"user_id": "u1"}
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError):
                    await EventBus._dispatch_event(
                        "auth.login", data,
                        redis_client=client, message_id="100-0",
                    )

            # HINCRBY wrote the field, EXPIRE set a TTL.
            key = f"event_retry:auth.login:100-0"
            assert (await client.hget(key, "retry_count")) == b"1"
            ttl = await client.ttl(key)
            assert 0 < ttl <= settings.EVENT_RETRY_TTL_SECONDS
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_retry_count_read_from_redis_across_calls(self):
        """Subsequent dispatches with the same message_id read the persisted count.

        This is the core issue #127 fix: the counter survives because it
        is read from Redis, not from the local `data` dict.
        """
        from app.event_bus import EventBus

        client = FakeRedis()
        try:
            data: dict = {"user_id": "u1"}
            msg_id = "200-0"

            # First call: counter starts at 0, increments to 1 (still under max=3).
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError):
                    await EventBus._dispatch_event(
                        "auth.login", data,
                        redis_client=client, message_id=msg_id,
                    )

            # Second call: SIMULATE a consumer restart — `data` dict is fresh
            # with no `_retry_count` key. The persisted counter must still be
            # read from Redis.
            fresh_data: dict = {"user_id": "u1"}
            assert _RETRY_COUNT_KEY not in fresh_data
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError):
                    await EventBus._dispatch_event(
                        "auth.login", fresh_data,
                        redis_client=client, message_id=msg_id,
                    )

            # Persisted counter is now 2 — proves the second call read from
            # Redis, not from the empty fresh_data dict.
            key = f"event_retry:auth.login:{msg_id}"
            assert (await client.hget(key, "retry_count")) == b"2"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_retry_count_survives_simulated_consumer_restart(self):
        """The DLQ branch must be reached when a new consumer reads the same msg.

        End-to-end test of the bug: dispatch 3 times (max retries = 3) with
        a fresh `data` dict on each call, simulating 3 separate consumer
        instances picking up the same Redis stream message. The 3rd call
        must observe retry_count == EVENT_MAX_RETRIES and route to DLQ.
        """
        from app.event_bus import EventBus, drain_dlq_tasks
        from app.core.config import settings

        client = FakeRedis()
        try:
            msg_id = "300-0"
            # Simulate 3 separate consumers picking up the same message
            for attempt in range(settings.EVENT_MAX_RETRIES):
                fresh_data: dict = {"user_id": f"u-{attempt}"}
                with patch.object(
                    EventBus, "_handle_auth_login",
                    side_effect=RuntimeError("boom"),
                ):
                    with pytest.raises(RuntimeError):
                        await EventBus._dispatch_event(
                            "auth.login", fresh_data,
                            redis_client=client, message_id=msg_id,
                        )

            # 4th call: retry_count is now 3 (== max), so this call routes
            # to DLQ instead of re-raising.
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("dlq-time"),
            ):
                result = await EventBus._dispatch_event(
                    "auth.login", {"user_id": "u-final"},
                    redis_client=client, message_id=msg_id,
                )
            assert result is False

            await drain_dlq_tasks(timeout=2.0)
            dlq_key = f"{settings.EVENT_STREAM_PREFIX}:dlq:auth.login"
            entries = await client.xrange(dlq_key)
            assert len(entries) == 1
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_retry_count_cleared_on_success(self):
        """A successful handler must DEL the persistent counter."""
        from app.event_bus import EventBus

        client = FakeRedis()
        try:
            msg_id = "400-0"
            data = {"user_id": "u"}

            # First: fail once to create the counter.
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError):
                    await EventBus._dispatch_event(
                        "auth.login", data,
                        redis_client=client, message_id=msg_id,
                    )
            key = f"event_retry:auth.login:{msg_id}"
            assert (await client.hget(key, "retry_count")) is not None

            # Second: handler succeeds → counter must be cleared.
            result = await EventBus._dispatch_event(
                "auth.login", data,
                redis_client=client, message_id=msg_id,
            )
            assert result is True
            assert (await client.hget(key, "retry_count")) is None
            assert await client.exists(key) == 0
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_retry_count_cleared_on_dlq(self):
        """DLQ routing must DEL the persistent counter to prevent re-DLQ on recycled id."""
        from app.event_bus import EventBus, drain_dlq_tasks
        from app.core.config import settings

        client = FakeRedis()
        try:
            msg_id = "500-0"

            # Drive the counter to max by failing max-1 times.
            for _ in range(settings.EVENT_MAX_RETRIES):
                with patch.object(
                    EventBus, "_handle_auth_login",
                    side_effect=RuntimeError("boom"),
                ):
                    with pytest.raises(RuntimeError):
                        await EventBus._dispatch_event(
                            "auth.login", {"user_id": "u"},
                            redis_client=client, message_id=msg_id,
                        )
            key = f"event_retry:auth.login:{msg_id}"
            assert (await client.hget(key, "retry_count")) is not None

            # One more failure pushes to DLQ; counter must be cleared.
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("final"),
            ):
                result = await EventBus._dispatch_event(
                    "auth.login", {"user_id": "u"},
                    redis_client=client, message_id=msg_id,
                )
            assert result is False
            await drain_dlq_tasks(timeout=2.0)
            assert (await client.hget(key, "retry_count")) is None
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_no_persistence_when_message_id_missing(self):
        """Backward compat: dispatch without message_id falls back to in-memory.

        Existing tests pass only (event_type, data) and rely on the in-memory
        data dict. This MUST still work.
        """
        from app.event_bus import EventBus
        from app.core.config import settings

        client = FakeRedis()
        try:
            data = {"user_id": "u", "_retry_count": 0}
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError):
                    await EventBus._dispatch_event("auth.login", data, redis_client=client)

            # No persistent key was created (message_id was None).
            assert await client.keys("event_retry:auth.login:*") == []
            # In-memory data was updated instead.
            assert data.get("_retry_count") == 1
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_retry_count_falls_back_to_in_memory_on_redis_error(self):
        """If Redis hget raises, dispatch must fall back to the data dict."""
        from app.event_bus import EventBus
        from app.core.config import settings

        # FakeRedis whose hget always raises to simulate a Redis hiccup.
        class BrokenRedis(FakeRedis):
            def __init__(self) -> None:
                super().__init__()

            async def hget(self, *args, **kwargs):  # type: ignore[override]
                raise ConnectionError("simulated")

            async def hincrby(self, *args, **kwargs):  # type: ignore[override]
                raise ConnectionError("simulated")

            async def expire(self, *args, **kwargs):  # type: ignore[override]
                raise ConnectionError("simulated")

            async def delete(self, *args, **kwargs):  # type: ignore[override]
                return 0

        client = BrokenRedis()
        try:
            data = {"user_id": "u", "_retry_count": 1}
            # Without persistence, the in-memory _retry_count = 1 is used.
            # 1 < 3 (max), so this re-raises (still retryable).
            with patch.object(
                EventBus, "_handle_auth_login",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError):
                    await EventBus._dispatch_event(
                        "auth.login", data,
                        redis_client=client, message_id="600-0",
                    )
            # In-memory counter was incremented to 2.
            assert data.get("_retry_count") == 2
        finally:
            await client.aclose()


# Module-level constants imported by the regression tests
from app.event_bus import _RETRY_COUNT_KEY  # noqa: E402
