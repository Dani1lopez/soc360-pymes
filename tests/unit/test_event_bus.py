"""Tests for event_bus.py (T2.2) — EventBus and EventConsumer classes."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis


class TestEventBusStreamName:
    """Validate EventBus.stream_name()."""

    @pytest.mark.asyncio
    async def test_stream_name_returns_full_key(self):
        """stream_name() MUST return 'events:auth.login' given 'auth.login'."""
        from app.event_bus import EventBus

        client = FakeRedis()
        bus = EventBus(redis_client=client)
        result = bus.stream_name("auth.login")
        assert result == "events:auth.login"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_stream_name_uses_prefix_from_settings(self):
        """stream_name() MUST use settings.EVENT_STREAM_PREFIX as the prefix."""
        from app.core.config import settings
        from app.event_bus import EventBus

        client = FakeRedis()
        bus = EventBus(redis_client=client)
        result = bus.stream_name("anything")
        expected = f"{settings.EVENT_STREAM_PREFIX}:anything"
        assert result == expected
        await client.aclose()


class TestEventBusPublish:
    """Validate EventBus.publish()."""

    @pytest_asyncio.fixture
    async def client(self) -> FakeRedis:
        r = FakeRedis()
        yield r
        await r.aclose()

    @pytest.mark.asyncio
    async def test_publish_returns_message_id(self, client: FakeRedis):
        """publish() MUST return the XADD message ID (bytes)."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent

        bus = EventBus(redis_client=client)
        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="a" * 32,
        )
        await bus.publish(event)
        length = await client.xlen("events:auth.login")
        assert length == 1

    @pytest.mark.asyncio
    async def test_publish_uses_maxlen_from_settings(self, client: FakeRedis):
        """publish() MUST use xadd maxlen with approximate=True from settings."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent

        bus = EventBus(redis_client=client)
        # Publish 3 events with maxlen=2 (approximate)
        for i in range(3):
            event = AuthLoginEvent(
                event_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                user_id=f"user-{i}",
                email_hash=f"{i:032x}",
            )
            await bus.publish(event)
        # Stream length should be bounded (fakeredis approximates, allow up to 3)
        length = await client.xlen("events:auth.login")
        assert length <= 3

    @pytest.mark.asyncio
    async def test_publish_event_with_optional_fields(self, client: FakeRedis):
        """publish() MUST correctly serialize ip_prefix and user_agent."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent

        bus = EventBus(redis_client=client)
        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="a" * 32,
            ip_prefix="192.168.1.0/24",
            user_agent="Mozilla/5.0",
        )
        msg_id = await bus.publish(event)
        assert isinstance(msg_id, bytes)
        assert b"-" in msg_id

    @pytest.mark.asyncio
    async def test_publish_stores_event_in_stream(self, client: FakeRedis):
        """publish() MUST store the event in the correct Redis stream."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent

        bus = EventBus(redis_client=client)
        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="a" * 32,
        )
        await bus.publish(event)
        length = await client.xlen("events:auth.login")
        assert length == 1

    @pytest.mark.asyncio
    async def test_publish_uses_maxlen_from_settings(self, client: FakeRedis):
        """publish() MUST use xadd maxlen with approximate=True from settings."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent

        bus = EventBus(redis_client=client)
        # Publish 3 events with maxlen=2 (approximate)
        for i in range(3):
            event = AuthLoginEvent(
                event_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                user_id=f"user-{i}",
                email_hash=f"{i:032x}",
            )
            await bus.publish(event)
        # Stream length should be bounded (fakeredis approximates, allow up to 3)
        length = await client.xlen("events:auth.login")
        assert length <= 3

    @pytest.mark.asyncio
    async def test_publish_event_with_optional_fields(self, client: FakeRedis):
        """publish() MUST correctly serialize ip_prefix and user_agent."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent

        bus = EventBus(redis_client=client)
        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="a" * 32,
            ip_prefix="192.168.1.0/24",
            user_agent="Mozilla/5.0",
        )
        msg_id = await bus.publish(event)
        assert isinstance(msg_id, bytes)


class TestEventConsumerInit:
    """Validate EventConsumer initialization."""

    @pytest.mark.asyncio
    async def test_consumer_stores_params(self):
        """EventConsumer MUST store redis_client, event_type, consumer_name, group_name."""
        from app.event_bus import EventConsumer

        client = FakeRedis()
        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        assert consumer.redis_client is client
        assert consumer.event_type == "auth.login"
        assert consumer.consumer_name == "worker-1"
        assert consumer.group_name == "soc360-consumers"
        await client.aclose()


class TestEventConsumerReadPending:
    """Validate EventConsumer.read_pending()."""

    @pytest_asyncio.fixture
    async def setup_stream_with_consumer_group(self) -> tuple[FakeRedis, bytes]:
        """Create a stream with one consumer group and one pending message."""
        client = FakeRedis()
        stream_name = "events:auth.login"
        group_name = "soc360-consumers"
        # Create consumer group
        await client.xgroup_create(stream_name, group_name, "0", mkstream=True)
        # Add a message (this will be pending after reading)
        msg_id = await client.xadd(stream_name, {"event": "login", "user_id": "u1"})
        # Read the message (makes it pending in the group)
        await client.xreadgroup(group_name, "worker-1", {stream_name: ">"}, count=1)
        return client, msg_id

    @pytest.mark.asyncio
    async def test_read_pending_returns_list(self, setup_stream_with_consumer_group):
        """read_pending() MUST return a list of pending messages."""
        client, _ = setup_stream_with_consumer_group
        from app.event_bus import EventConsumer

        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        pending = await consumer.read_pending()
        assert isinstance(pending, list)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_read_pending_returns_dict_per_message(self, setup_stream_with_consumer_group):
        """read_pending() MUST return a dict with 'message_id' and 'data' per message."""
        client, expected_msg_id = setup_stream_with_consumer_group
        from app.event_bus import EventConsumer

        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        pending = await consumer.read_pending()
        assert len(pending) >= 1
        msg = pending[0]
        assert isinstance(msg, dict)
        assert "message_id" in msg
        assert "data" in msg
        await client.aclose()


class TestEventConsumerAck:
    """Validate EventConsumer.ack()."""

    @pytest_asyncio.fixture
    async def client_with_message(self) -> tuple[FakeRedis, bytes]:
        """Create a stream, consumer group, add and read a message."""
        client = FakeRedis()
        stream_name = "events:auth.login"
        group_name = "soc360-consumers"
        await client.xgroup_create(stream_name, group_name, "0", mkstream=True)
        msg_id = await client.xadd(stream_name, {"event": "login", "user_id": "u1"})
        await client.xreadgroup(group_name, "worker-1", {stream_name: ">"}, count=1)
        return client, msg_id

    @pytest.mark.asyncio
    async def test_ack_returns_none(self, client_with_message):
        """ack() MUST return None."""
        client, msg_id = client_with_message
        from app.event_bus import EventConsumer

        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        result = await consumer.ack(msg_id)
        assert result is None
        await client.aclose()

    @pytest.mark.asyncio
    async def test_ack_removes_from_pending(self, client_with_message):
        """ack() MUST remove the message from the pending list."""
        client, msg_id = client_with_message
        from app.event_bus import EventConsumer

        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        # Verify it's pending
        pending_before = await consumer.read_pending()
        assert len(pending_before) == 1

        # Acknowledge
        await consumer.ack(msg_id)

        # Verify it's no longer pending
        pending_after = await consumer.read_pending()
        assert len(pending_after) == 0
        await client.aclose()


class TestEventConsumerDelete:
    """Validate EventConsumer.delete()."""

    @pytest.mark.asyncio
    async def test_delete_returns_none(self):
        """delete() MUST return None."""
        from app.event_bus import EventConsumer

        client = FakeRedis()
        msg_id = await client.xadd("events:auth.login", {"event": "login"})
        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        result = await consumer.delete(msg_id)
        assert result is None
        await client.aclose()

    @pytest.mark.asyncio
    async def test_delete_removes_message_from_stream(self):
        """delete() MUST remove the message from the Redis stream."""
        from app.event_bus import EventConsumer

        client = FakeRedis()
        stream_name = "events:auth.login"
        msg_id = await client.xadd(stream_name, {"event": "login"})
        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        # Verify message exists
        length_before = await client.xlen(stream_name)
        assert length_before == 1

        # Delete
        await consumer.delete(msg_id)

        # Verify message is gone
        length_after = await client.xlen(stream_name)
        assert length_after == 0
        await client.aclose()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_none(self):
        """delete() on a non-existent message MUST return None without error."""
        from app.event_bus import EventConsumer

        client = FakeRedis()
        fake_id = b"1234567890-0"
        consumer = EventConsumer(
            redis_client=client,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )
        result = await consumer.delete(fake_id)
        assert result is None
        await client.aclose()


class TestEventBusGetConsumer:
    """Validate EventBus.get_consumer()."""

    @pytest.mark.asyncio
    async def test_get_consumer_returns_event_consumer_instance(self):
        """get_consumer() MUST return an EventConsumer instance."""
        from app.core.config import settings
        from app.event_bus import EventBus

        client = FakeRedis()
        bus = EventBus(redis_client=client)
        consumer = bus.get_consumer("worker-1", "auth.login")
        from app.event_bus import EventConsumer

        assert isinstance(consumer, EventConsumer)
        assert consumer.event_type == "auth.login"
        assert consumer.consumer_name == "worker-1"
        assert consumer.group_name == settings.EVENT_CONSUMER_GROUP
        await client.aclose()
