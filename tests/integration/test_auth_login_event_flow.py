"""Integration test: auth.login event published and consumed end-to-end.

T5.2: Verifies the entire pipeline:
  login → event published to Redis stream → consumed by consumer group.

Uses fakeredis to mock Redis and a mocked DB for user lookup.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from fakeredis.aioredis import FakeRedis


@pytest.mark.asyncio
async def test_auth_login_event_appears_in_redis_stream():
    """After successful login, an auth.login event MUST appear in the events:auth.login stream.

    This is a full pipeline integration test:
    1. FakeRedis acts as the Redis backing store
    2. User lookup is mocked
    3. login() is called (which internally publishes the event)
    4. We read the Redis stream and verify the event is present
    """
    from app.modules.auth import service
    from app.event_bus import EventBus

    # --- Setup fakeredis ---
    fake_redis = FakeRedis()

    # --- Setup mock user ---
    mock_user = MagicMock()
    mock_user.id = uuid4()
    mock_user.email = "integration@test.com"
    mock_user.hashed_password = "hashed_password"  # will be verified by mock
    mock_user.tenant_id = uuid4()
    mock_user.role = "admin"
    mock_user.is_superadmin = False
    mock_user.is_active = True

    mock_db = AsyncMock()

    # --- Mock all auth service internals ---
    with patch.object(service, "_check_account_lockout", return_value=None):
        with patch.object(service, "_get_active_user", return_value=mock_user):
            with patch("app.modules.auth.service.verify_password", return_value=True):
                with patch.object(service, "_check_tenant_active", return_value=None):
                    with patch.object(service, "_clear_login_attempts", return_value=None):
                        with patch(
                            "app.modules.auth.service.create_access_token",
                            return_value=("fake_access_token", "fake_jti"),
                        ):
                            with patch.object(
                                service, "_create_refresh_token", return_value="fake_refresh_token"
                            ):
                                # Patch get_event_bus so it uses our fakeredis-backed EventBus
                                with patch(
                                    "app.modules.auth.service.get_event_bus"
                                ) as mock_get_bus:
                                    event_bus = EventBus(fake_redis)
                                    mock_get_bus.return_value = event_bus

                                    # --- Execute login ---
                                    result = await service.login(
                                        email="integration@test.com",
                                        password="any_password",
                                        db=mock_db,
                                        redis=fake_redis,
                                        request_ip="203.0.113.50",
                                        request_headers={"user-agent": "IntegrationTest/1.0"},
                                    )

    # --- Verify login succeeded ---
    token_response, refresh_token = result
    assert token_response.access_token == "fake_access_token"
    assert refresh_token == "fake_refresh_token"

    # --- Verify auth.login event is in the Redis stream ---
    stream_name = "events:auth.login"
    stream_length = await fake_redis.xlen(stream_name)
    assert stream_length >= 1, f"Expected at least 1 message in {stream_name}, got {stream_length}"

    # Read all messages in the stream
    messages = await fake_redis.xrange(stream_name)
    assert len(messages) >= 1

    # Find the auth.login event in the stream
    found_event = False
    for msg_id, fields in messages:
        field_dict = {
            k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
            for k, v in fields.items()
        }
        if field_dict.get("event_type") == "auth.login":
            found_event = True
            # Verify key fields
            assert field_dict["user_id"] == str(mock_user.id), "user_id must match"
            assert "email_hash" in field_dict, "email_hash must be present"
            assert "email" not in field_dict, "raw email must NOT be present"
            assert "ip_prefix" in field_dict, "ip_prefix must be present"
            assert "ip_address" not in field_dict, "raw ip_address must NOT be present"
            assert field_dict["tenant_id"] == str(mock_user.tenant_id), "tenant_id must match"
            break

    assert found_event, "auth.login event not found in stream"

    # --- Cleanup ---
    await fake_redis.aclose()


@pytest.mark.asyncio
async def test_auth_login_event_consumed_by_consumer_group():
    """After event is published, consumer group can read it as a pending message.

    Verifies the full consumer group lifecycle:
    1. Event is published to stream
    2. Consumer group is created (with mkstream)
    3. Event is delivered to consumer via xreadgroup (makes it pending)
    4. Event is acknowledged via xack
    """
    from app.event_bus import EventBus, EventConsumer

    fake_redis = FakeRedis()
    event_bus = EventBus(fake_redis)

    # Create the event directly (bypass login)
    from app.event_schemas import AuthLoginEvent
    from datetime import datetime, timezone

    event = AuthLoginEvent(
        event_id=uuid4(),
        event_type="auth.login",
        tenant_id=uuid4(),
        user_id=str(uuid4()),
        email_hash="a" * 16,
        ip_prefix="192.0.2.0/24",
        user_agent="ConsumerGroupTest/1.0",
        timestamp=datetime.now(timezone.utc),
    )
    msg_id = await event_bus.publish(event)
    assert isinstance(msg_id, bytes)

    stream_name = "events:auth.login"
    group_name = "soc360-consumers"

    # Create consumer group (mkstream=True)
    await fake_redis.xgroup_create(stream_name, group_name, "0", mkstream=True)

    # Deliver message to consumer via xreadgroup (this makes it "pending")
    read_result = await fake_redis.xreadgroup(
        group_name, "integration-worker", {stream_name: ">"}, count=1
    )
    assert len(read_result) >= 1, "xreadgroup should return the published message"

    # Consumer group now shows it as pending
    consumer = EventConsumer(
        redis_client=fake_redis,
        event_type="auth.login",
        consumer_name="integration-worker",
        group_name=group_name,
    )

    pending = await consumer.read_pending()
    assert len(pending) >= 1, "At least one pending message should exist after xreadgroup"

    # Verify message data
    msg = pending[0]
    data = msg["data"]
    assert data["email_hash"] == "a" * 16
    assert data["ip_prefix"] == "192.0.2.0/24"

    # Acknowledge the message
    await consumer.ack(msg["message_id"])

    # Verify message is no longer pending
    pending_after_ack = await consumer.read_pending()
    assert len(pending_after_ack) == 0, "Message should be acked and no longer pending"

    await fake_redis.aclose()


@pytest.mark.asyncio
async def test_login_succeeds_even_if_redis_unavailable_for_event():
    """Login MUST succeed even when event publishing would fail (fire-and-forget).

    This test verifies the non-blocking behavior: login succeeds
    even if the event bus is unavailable.
    """
    from app.modules.auth import service
    from app.event_bus import EventBus

    mock_user = MagicMock()
    mock_user.id = uuid4()
    mock_user.email = "fireandforget@test.com"
    mock_user.hashed_password = "hashed_password"
    mock_user.tenant_id = uuid4()
    mock_user.role = "user"
    mock_user.is_superadmin = False
    mock_user.is_active = True

    mock_db = AsyncMock()
    fake_redis = FakeRedis()

    # EventBus that will fail on publish
    failing_event_bus = AsyncMock(spec=EventBus)
    failing_event_bus.publish.side_effect = ConnectionError("Redis unavailable")

    with patch.object(service, "_check_account_lockout", return_value=None):
        with patch.object(service, "_get_active_user", return_value=mock_user):
            with patch("app.modules.auth.service.verify_password", return_value=True):
                with patch.object(service, "_check_tenant_active", return_value=None):
                    with patch.object(service, "_clear_login_attempts", return_value=None):
                        with patch(
                            "app.modules.auth.service.create_access_token",
                            return_value=("access_token", "jti"),
                        ):
                            with patch.object(
                                service, "_create_refresh_token", return_value="refresh_token"
                            ):
                                with patch(
                                    "app.modules.auth.service.get_event_bus",
                                    return_value=failing_event_bus,
                                ):
                                    result = await service.login(
                                        email="fireandforget@test.com",
                                        password="password",
                                        db=mock_db,
                                        redis=fake_redis,
                                        request_ip="10.0.0.1",
                                    )

    # Login MUST succeed despite event publish failure
    token_response, refresh_token = result
    assert token_response.access_token == "access_token"
    assert refresh_token == "refresh_token"

    await fake_redis.aclose()
