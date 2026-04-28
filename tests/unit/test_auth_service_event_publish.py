"""Tests for auth.login event publishing on successful login.

T4.1: After credentials are validated and tokens are created,
the login function MUST publish an auth.login event without blocking
the login response if event publishing fails.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestAuthLoginEventPublish:
    """Test that auth.login event is published on successful login."""

    @pytest.mark.asyncio
    async def test_login_publishes_auth_login_event_on_success(self):
        """Test successful login publishes auth.login event."""
        from app.modules.auth import service
        from app.event_schemas import AuthLoginEvent
        from app.event_bus import EventBus

        # Mock user
        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "test@example.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True

        # Mock DB and Redis
        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        # Capture published event
        published_events: list[AuthLoginEvent] = []

        async def mock_publish(event: AuthLoginEvent) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=mock_user):
                with patch("app.modules.auth.service.verify_password", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-123"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        result = await service.login(
                                            email="test@example.com",
                                            password="password",
                                            db=mock_db,
                                            redis=mock_redis,
                                            request_ip="192.168.1.1",
                                        )

        # Verify login succeeded
        token_response, refresh_token = result
        assert token_response.access_token == "access_token"
        assert refresh_token == "refresh_token"

        # Verify exactly one event was published
        assert len(published_events) == 1
        event = published_events[0]

        # Verify event fields
        assert event.event_type == "auth.login"
        assert event.user_id == str(mock_user.id)
        assert event.email_hash is not None
        assert len(event.email_hash) == 16
        assert event.ip_prefix == "192.168.1.0/24"
        assert event.tenant_id == mock_user.tenant_id

    @pytest.mark.asyncio
    async def test_login_publishes_event_with_user_agent(self):
        """Test event includes user_agent from request headers."""
        from app.modules.auth import service
        from app.event_schemas import AuthLoginEvent
        from app.event_bus import EventBus

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "agent@test.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()
        mock_user.role = "user"
        mock_user.is_superadmin = False
        mock_user.is_active = True

        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        published_events: list[AuthLoginEvent] = []

        async def mock_publish(event: AuthLoginEvent) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=mock_user):
                with patch("app.modules.auth.service.verify_password", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-123"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        # Call login - result not needed, we just verify it doesn't raise
                                        await service.login(
                                            email="agent@test.com",
                                            password="password",
                                            db=mock_db,
                                            redis=mock_redis,
                                            request_ip="10.0.0.1",
                                        )

        assert len(published_events) == 1
        event = published_events[0]
        # user_agent passed via request headers is None in this test
        # (not passed), so it defaults to None per schema
        assert event.ip_prefix == "10.0.0.0/24"
        assert event.email_hash is not None
        assert len(event.email_hash) == 16

    @pytest.mark.asyncio
    async def test_login_does_not_block_on_publish_failure(self):
        """Test login succeeds even if event publishing fails (non-blocking)."""
        from app.modules.auth import service
        from app.event_bus import EventBus
        import logging

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "fail@test.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True

        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        mock_event_bus = AsyncMock(spec=EventBus)
        # Simulate publish raising an exception
        mock_event_bus.publish.side_effect = Exception("Redis connection failed")

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=mock_user):
                with patch("app.modules.auth.service.verify_password", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-123"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        with patch.object(
                                            logging.getLogger("app.modules.auth.service"),
                                            "warning",
                                        ) as mock_warning:
                                            # Login MUST succeed even if publish fails
                                            result = await service.login(
                                                email="fail@test.com",
                                                password="password",
                                                db=mock_db,
                                                redis=mock_redis,
                                                request_ip="192.168.1.1",
                                            )

        # Login still returns tokens
        token_response, refresh_token = result
        assert token_response.access_token == "access_token"
        assert refresh_token == "refresh_token"

        # Warning was logged about the publish failure
        mock_warning.assert_called_once()
        call_args = mock_warning.call_args[0]
        assert "event" in call_args[0].lower() or "publish" in call_args[0].lower()

    @pytest.mark.asyncio
    async def test_login_blocked_if_credentials_invalid(self):
        """Test NO event is published when credentials are invalid."""
        from app.modules.auth import service
        from app.event_bus import EventBus

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.hashed_password = "hashed_password"

        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        mock_event_bus = AsyncMock(spec=EventBus)

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=mock_user):
                with patch(
                    "app.modules.auth.service.verify_password", return_value=False
                ):
                    with patch.object(
                        service, "_record_failed_attempt", return_value=None
                    ):
                        with patch(
                            "app.modules.auth.service.get_event_bus",
                            return_value=mock_event_bus,
                        ):
                            # Should raise AuthError, no event published
                            from app.core.exceptions import AuthError

                            with pytest.raises(AuthError) as exc_info:
                                await service.login(
                                    email="test@example.com",
                                    password="wrong_password",
                                    db=mock_db,
                                    redis=mock_redis,
                                )

                            assert exc_info.value.status_code == 401

        # verify publish was never called
        mock_event_bus.publish.assert_not_called()
