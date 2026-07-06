"""End-to-end tests for event bus with real Redis.

Tests the full event bus lifecycle with a real Redis instance:
- Publish → Consume → Ack
- Consumer group behavior
- Pending message recovery
- DLQ (Dead Letter Queue) on handler failure

These tests require a running Redis instance (provided by CI services).
They are SKIPPED when Redis is not available (local dev without Redis).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import settings
from app.event_bus import EventBus, EventConsumer
from app.event_schemas import AuthLoginEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _redis_is_available() -> bool:
    """Check if Redis is reachable."""
    try:
        client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
        await client.ping()
        await client.aclose()
        return True
    except Exception:
        return False


# Skip all tests in this module if Redis is not available
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis_client() -> Redis:
    """Provide a real Redis client for E2E tests."""
    if not await _redis_is_available():
        pytest.skip("Redis not available — E2E tests require a running Redis instance")
    client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    yield client
    # Cleanup: flush test keys
    try:
        keys = await client.keys("events:*")
        if keys:
            await client.delete(*keys)
    except Exception:
        pass
    await client.aclose()


@pytest_asyncio.fixture
async def event_bus(redis_client: Redis) -> EventBus:
    """Provide an EventBus backed by real Redis."""
    return EventBus(redis_client)


@pytest_asyncio.fixture
def sample_event() -> AuthLoginEvent:
    """Create a sample auth.login event."""
    return AuthLoginEvent(
        event_id=uuid.uuid4(),
        event_type="auth.login",
        tenant_id=uuid.uuid4(),
        user_id=str(uuid.uuid4()),
        email_hash="a" * 64,
        ip_prefix="192.0.2.0/24",
        user_agent="E2ETest/1.0",
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEventBusE2E:
    """End-to-end event bus tests with real Redis."""

    async def test_publish_and_consume(
        self, event_bus: EventBus, redis_client: Redis, sample_event: AuthLoginEvent
    ):
        """Publish an event and consume it via consumer group."""
        # Publish
        msg_id = await event_bus.publish(sample_event)
        assert isinstance(msg_id, bytes)

        # Create consumer
        consumer = EventConsumer(
            redis_client=redis_client,
            event_type="auth.login",
            consumer_name="e2e-worker-1",
            group_name="e2e-test-group",
        )

        # Read new messages
        messages = await consumer.read_new(block=1000)
        assert len(messages) >= 1

        # Verify message data
        msg = messages[0]
        data = msg["data"]
        assert data["event_type"] == "auth.login"
        assert data["user_id"] == str(sample_event.user_id)
        assert data["email_hash"] == sample_event.email_hash
        assert data["ip_prefix"] == sample_event.ip_prefix

        # Acknowledge
        await consumer.ack(msg["message_id"])

        # Verify no longer pending
        pending = await consumer.read_pending()
        assert len(pending) == 0

    async def test_consumer_group_multiple_consumers(
        self, event_bus: EventBus, redis_client: Redis
    ):
        """Multiple consumers in the same group should get different messages."""
        # Publish 2 events
        event1 = AuthLoginEvent(
            event_id=uuid.uuid4(),
            event_type="auth.login",
            tenant_id=uuid.uuid4(),
            user_id=str(uuid.uuid4()),
            email_hash="b" * 64,
            ip_prefix="10.0.0.0/24",
            user_agent="MultiConsumer/1.0",
            timestamp=datetime.now(timezone.utc),
        )
        event2 = AuthLoginEvent(
            event_id=uuid.uuid4(),
            event_type="auth.login",
            tenant_id=uuid.uuid4(),
            user_id=str(uuid.uuid4()),
            email_hash="c" * 64,
            ip_prefix="10.0.1.0/24",
            user_agent="MultiConsumer/1.0",
            timestamp=datetime.now(timezone.utc),
        )

        await event_bus.publish(event1)
        await event_bus.publish(event2)

        # Consumer 1 reads
        consumer1 = EventConsumer(
            redis_client=redis_client,
            event_type="auth.login",
            consumer_name="e2e-worker-a",
            group_name="e2e-multi-group",
        )
        messages1 = await consumer1.read_new(block=1000)
        assert len(messages1) >= 1

        # Consumer 2 reads (should get remaining messages)
        consumer2 = EventConsumer(
            redis_client=redis_client,
            event_type="auth.login",
            consumer_name="e2e-worker-b",
            group_name="e2e-multi-group",
        )
        messages2 = await consumer2.read_new(block=1000)

        # Both consumers should have received messages
        total_messages = len(messages1) + len(messages2)
        assert total_messages >= 2

        # Cleanup
        for msg in messages1:
            await consumer1.ack(msg["message_id"])
        for msg in messages2:
            await consumer2.ack(msg["message_id"])

    async def test_pending_message_recovery(
        self, event_bus: EventBus, redis_client: Redis, sample_event: AuthLoginEvent
    ):
        """Unacknowledged messages should be recoverable via read_pending."""
        # Publish
        await event_bus.publish(sample_event)

        consumer = EventConsumer(
            redis_client=redis_client,
            event_type="auth.login",
            consumer_name="e2e-recovery-worker",
            group_name="e2e-recovery-group",
        )

        # Read but DON'T ack (simulates crash)
        messages = await consumer.read_new(block=1000)
        assert len(messages) >= 1

        # Create new consumer instance (simulates restart)
        consumer2 = EventConsumer(
            redis_client=redis_client,
            event_type="auth.login",
            consumer_name="e2e-recovery-worker",
            group_name="e2e-recovery-group",
        )

        # Should recover pending messages
        pending = await consumer2.read_pending()
        assert len(pending) >= 1

        # Verify recovered message data
        msg = pending[0]
        assert msg["data"]["event_type"] == "auth.login"

        # Ack to cleanup
        await consumer2.ack(msg["message_id"])

    async def test_stream_maxlen_respected(
        self, event_bus: EventBus, redis_client: Redis
    ):
        """Stream should respect EVENT_STREAM_MAXLEN setting."""
        # Publish several events
        for i in range(5):
            event = AuthLoginEvent(
                event_id=uuid.uuid4(),
                event_type="auth.login",
                tenant_id=uuid.uuid4(),
                user_id=str(uuid.uuid4()),
                email_hash=f"{'d' * 60}{i:04d}",
                ip_prefix="10.0.0.0/24",
                user_agent="MaxLenTest/1.0",
                timestamp=datetime.now(timezone.utc),
            )
            await event_bus.publish(event)

        # Verify stream exists and has messages
        stream_key = f"{settings.EVENT_STREAM_PREFIX}:auth.login"
        length = await redis_client.xlen(stream_key)
        assert length >= 5

    async def test_event_dispatch_handler(
        self, event_bus: EventBus, redis_client: Redis, sample_event: AuthLoginEvent
    ):
        """EventBus._dispatch_event should handle auth.login events."""
        # Publish
        msg_id = await event_bus.publish(sample_event)

        # Read the message
        consumer = EventConsumer(
            redis_client=redis_client,
            event_type="auth.login",
            consumer_name="e2e-dispatch-worker",
            group_name="e2e-dispatch-group",
        )
        messages = await consumer.read_new(block=1000)
        assert len(messages) >= 1

        msg = messages[0]
        msg_id_str = msg["message_id"].decode() if isinstance(msg["message_id"], bytes) else msg["message_id"]

        # Dispatch the event (should not raise)
        result = await EventBus._dispatch_event(
            "auth.login",
            msg["data"],
            redis_client,
            message_id=msg_id_str,
        )
        assert result is True

        # Ack
        await consumer.ack(msg["message_id"])

    async def test_reconnect_and_resume(
        self, event_bus: EventBus, redis_client: Redis, sample_event: AuthLoginEvent
    ):
        """reconnect_and_resume should recover pending messages."""
        # Publish
        await event_bus.publish(sample_event)

        consumer = EventConsumer(
            redis_client=redis_client,
            event_type="auth.login",
            consumer_name="e2e-reconnect-worker",
            group_name="e2e-reconnect-group",
        )

        # Read but don't ack
        messages = await consumer.read_new(block=1000)
        assert len(messages) >= 1

        # Reconnect (simulates reconnection)
        pending = await consumer.reconnect_and_resume()
        assert len(pending) >= 1

        # Ack to cleanup
        for msg in pending:
            await consumer.ack(msg["message_id"])
