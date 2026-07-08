"""Tests for auth.login event publishing on successful login.

T4.1: After credentials are validated and tokens are created,
the login function MUST publish an auth.login event without blocking
the login response if event publishing fails.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
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
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        # Mock DB and Redis
        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        # Capture published events
        published_events: list[AuthLoginEvent] = []

        async def mock_publish(event: AuthLoginEvent) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
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
        assert len(event.email_hash) == 32
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
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        published_events: list[AuthLoginEvent] = []

        async def mock_publish(event: AuthLoginEvent) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
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
        assert len(event.email_hash) == 32

    @pytest.mark.asyncio
    async def test_login_does_not_block_on_publish_failure(self):
        """Test login succeeds even if event publishing fails (non-blocking)."""
        from app.modules.auth import service
        from app.event_bus import EventBus
        from redis.exceptions import RedisError

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "fail@test.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        mock_event_bus = AsyncMock(spec=EventBus)
        # Simulate RedisError during publish (realistic failure scenario)
        mock_event_bus.publish.side_effect = RedisError("Connection refused")

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
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
                                        with patch.object(service.logger, "warning") as mock_warning:
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

        # RedisError → warning was logged about the publish failure
        mock_warning.assert_called_once_with(
            "event_publish_failed", event_type="auth.login", reason="redis_error"
        )

    @pytest.mark.asyncio
    async def test_login_blocked_if_credentials_invalid(self):
        """Test NO event is published when credentials are invalid."""
        from app.modules.auth import service
        from app.event_bus import EventBus

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.hashed_password = "hashed_password"
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        mock_event_bus = AsyncMock(spec=EventBus)

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch(
                    "app.modules.auth.service.verify_password_async", return_value=False
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


class TestAuthSuperadminLoginEventPublish:
    """Test that superadmin login publishes AuthSuperadminLoginEvent."""

    @pytest.mark.asyncio
    async def test_superadmin_login_publishes_system_auth_login_event(self):
        """Superadmin login MUST publish AuthSuperadminLoginEvent."""
        from app.modules.auth import service
        from app.event_schemas import AuthSuperadminLoginEvent
        from app.event_bus import EventBus

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "sa@example.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = None  # superadmins have no tenant
        mock_user.role = "superadmin"
        mock_user.is_superadmin = True
        mock_user.is_active = True
        mock_tenant = None  # superadmins have no tenant

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        published_events: list = []

        async def mock_publish(event) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-sa"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        result = await service.login(
                                            email="sa@example.com",
                                            password="password",
                                            db=mock_db,
                                            redis=mock_redis,
                                            request_ip="10.0.0.1",
                                        )

        # Login succeeded
        token_response, refresh_token = result
        assert token_response.access_token == "access_token"

        # Exactly one event published
        assert len(published_events) == 1
        event = published_events[0]

        # Must be an AuthSuperadminLoginEvent instance
        assert isinstance(event, AuthSuperadminLoginEvent), (
            f"Expected AuthSuperadminLoginEvent, got {type(event).__name__}"
        )
        # Must have system.auth.login event type
        assert event.event_type == "system.auth.login"
        # Must be tenantless
        assert event.tenant_id is None
        # Must have is_superadmin=True
        assert event.is_superadmin is True
        # Must have the user ID
        assert event.user_id == str(mock_user.id)
        # Must have email hash
        assert event.email_hash is not None
        assert len(event.email_hash) == 32

    @pytest.mark.asyncio
    async def test_regular_user_login_still_publishes_auth_login_event(self):
        """Regular (non-superadmin) login MUST still publish AuthLoginEvent."""
        from app.modules.auth import service
        from app.event_schemas import AuthLoginEvent
        from app.event_bus import EventBus

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "regular@example.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()  # regular users have a tenant
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        published_events: list = []

        async def mock_publish(event) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-reg"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        result = await service.login(
                                            email="regular@example.com",
                                            password="password",
                                            db=mock_db,
                                            redis=mock_redis,
                                            request_ip="192.168.1.1",
                                        )

        # Login succeeded
        token_response, refresh_token = result
        assert token_response.access_token == "access_token"

        # Exactly one event published
        assert len(published_events) == 1
        event = published_events[0]

        # Must be an AuthLoginEvent instance (NOT AuthSuperadminLoginEvent)
        assert isinstance(event, AuthLoginEvent), (
            f"Expected AuthLoginEvent, got {type(event).__name__}"
        )
        assert type(event).__name__ == "AuthLoginEvent", (
            f"Expected type AuthLoginEvent, got {type(event).__name__}"
        )
        # Must have auth.login event type
        assert event.event_type == "auth.login"
        # Must have a tenant_id (not None)
        assert event.tenant_id is not None
        assert event.tenant_id == mock_user.tenant_id


class TestLoginEventErrorHandling:
    """REQ-004: Differentiated exception handling in login event publishing.

    Login MUST always succeed (availability-first).
    RedisError → logger.warning (swallowed).
    Programming errors → logger.critical (NOT re-raised).
    """

    @pytest.mark.asyncio
    async def test_redis_error_during_publish_logs_warning(self):
        """RedisError during publish → logger.warning, login still succeeds."""
        from app.modules.auth import service
        from redis.exceptions import RedisError

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "redis-fail@test.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        mock_event_bus = AsyncMock()
        mock_event_bus.publish.side_effect = RedisError("Connection refused")

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-redis"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        with patch.object(service.logger, "warning") as mock_warning:
                                            with patch.object(
                                                service.logger, "critical"
                                            ) as mock_critical:
                                                result = await service.login(
                                                    email="redis-fail@test.com",
                                                    password="password",
                                                    db=mock_db,
                                                    redis=mock_redis,
                                                    request_ip="10.0.0.1",
                                                )

        # Login MUST succeed (availability-first)
        token_response, refresh_token = result
        assert token_response.access_token == "access_token"
        assert refresh_token == "refresh_token"

        # RedisError → logger.warning
        mock_warning.assert_called_once_with(
            "event_publish_failed", event_type="auth.login", reason="redis_error"
        )
        # critical must NOT have been called
        mock_critical.assert_not_called()

    @pytest.mark.asyncio
    async def test_programming_error_during_publish_logs_critical(self):
        """Non-Redis programming error during publish → logger.critical, login still succeeds."""
        from app.modules.auth import service

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "prog-error@test.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        mock_event_bus = AsyncMock()
        # Non-Redis exception → programming error
        mock_event_bus.publish.side_effect = ValueError("Unexpected schema mismatch")

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-prog"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        with patch.object(service.logger, "warning") as mock_warning:
                                            with patch.object(
                                                service.logger, "critical"
                                            ) as mock_critical:
                                                result = await service.login(
                                                    email="prog-error@test.com",
                                                    password="password",
                                                    db=mock_db,
                                                    redis=mock_redis,
                                                    request_ip="10.0.0.1",
                                                )

        # Login MUST succeed (availability-first)
        token_response, refresh_token = result
        assert token_response.access_token == "access_token"
        assert refresh_token == "refresh_token"

        # Programming error → logger.critical
        mock_critical.assert_called_once_with(
            "event_publish_programming_error", event_type="auth.login"
        )
        # warning must NOT have been called
        mock_warning.assert_not_called()

    def test_redis_error_importable(self):
        """RedisError is importable from redis.exceptions."""
        from redis.exceptions import RedisError

        assert RedisError is not None
        assert issubclass(RedisError, Exception)


class TestUserAgentSanitizationInEvents:
    """REQ-140-R08: User-Agent must be sanitized before event publication."""

    @pytest.mark.asyncio
    async def test_login_event_receives_sanitized_ua(self):
        """AuthLoginEvent MUST receive sanitized user_agent, not raw value."""
        from app.modules.auth import service
        from app.event_schemas import AuthLoginEvent
        from app.event_bus import EventBus

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "ua@test.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        published_events: list[AuthLoginEvent] = []

        async def mock_publish(event: AuthLoginEvent) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        raw_ua = "Mozilla/5.0\x00Malicious\x1fStuff\x7f   padding"

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-ua"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        await service.login(
                                            email="ua@test.com",
                                            password="password",
                                            db=mock_db,
                                            redis=mock_redis,
                                            request_ip="10.0.0.1",
                                            user_agent=raw_ua,
                                        )

        assert len(published_events) == 1
        event = published_events[0]
        # Control chars replaced, whitespace collapsed: "Mozilla/5.0 Malicious Stuff padding"
        assert event.user_agent == "Mozilla/5.0 Malicious Stuff padding"

    @pytest.mark.asyncio
    async def test_superadmin_event_receives_sanitized_ua(self):
        """AuthSuperadminLoginEvent MUST receive sanitized user_agent."""
        from app.modules.auth import service
        from app.event_schemas import AuthSuperadminLoginEvent
        from app.event_bus import EventBus

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "sa-ua@test.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = None
        mock_user.role = "superadmin"
        mock_user.is_superadmin = True
        mock_user.is_active = True
        mock_tenant = None

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        published_events: list = []

        async def mock_publish(event) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        raw_ua = "x" * 500  # very long UA with no control chars

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-sa-ua"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        await service.login(
                                            email="sa-ua@test.com",
                                            password="password",
                                            db=mock_db,
                                            redis=mock_redis,
                                            request_ip="10.0.0.1",
                                            user_agent=raw_ua,
                                        )

        assert len(published_events) == 1
        event = published_events[0]
        assert isinstance(event, AuthSuperadminLoginEvent)
        # Must be capped at 256
        assert event.user_agent is not None
        assert len(event.user_agent) == 256

    @pytest.mark.asyncio
    async def test_missing_ua_sends_none(self):
        """When User-Agent header is absent, event receives None."""
        from app.modules.auth import service
        from app.event_schemas import AuthLoginEvent
        from app.event_bus import EventBus

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "no-ua@test.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = uuid4()
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()

        published_events: list = []

        async def mock_publish(event) -> bytes:
            published_events.append(event)
            return b"1234567890123-0"

        mock_event_bus = AsyncMock(spec=EventBus)
        mock_event_bus.publish.side_effect = mock_publish

        with patch.object(service, "_check_account_lockout", return_value=None):
            with patch.object(service, "_get_active_user", return_value=(mock_user, mock_tenant)):
                with patch("app.modules.auth.service.verify_password_async", return_value=True):
                    with patch.object(service, "_check_tenant_active", return_value=None):
                        with patch.object(service, "_clear_login_attempts", return_value=None):
                            with patch(
                                "app.modules.auth.service.create_access_token",
                                return_value=("access_token", "jti-no-ua"),
                            ):
                                with patch.object(
                                    service, "_create_refresh_token", return_value="refresh_token"
                                ):
                                    with patch(
                                        "app.modules.auth.service.get_event_bus",
                                        return_value=mock_event_bus,
                                    ):
                                        await service.login(
                                            email="no-ua@test.com",
                                            password="password",
                                            db=mock_db,
                                            redis=mock_redis,
                                            request_ip="10.0.0.1",
                                            # No user_agent passed
                                        )

        assert len(published_events) == 1
        event = published_events[0]
        assert event.user_agent is None
