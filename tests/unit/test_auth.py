from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession


class TestAuthSchemas:
    """Test auth schema validation."""
    
    def test_login_request_normalizes_email(self):
        """Test email is normalized to lowercase."""
        from app.modules.auth.schemas import LoginRequest
        
        request = LoginRequest(email="  Test@EXAMPLE.COM  ", password="password123")
        assert request.email == "test@example.com"
    
    def test_change_password_validates_strength(self):
        """Test password strength validation."""
        from app.modules.auth.schemas import ChangePasswordRequest
        
        # Too short
        with pytest.raises(ValueError, match="12 caracteres"):
            ChangePasswordRequest(current_password="oldpass", new_password="Short1!")
        
        # No uppercase
        with pytest.raises(ValueError, match="mayuscula"):
            ChangePasswordRequest(current_password="oldpass", new_password="lowercase123!")
        
        # No lowercase
        with pytest.raises(ValueError, match="minuscula"):
            ChangePasswordRequest(current_password="oldpass", new_password="UPPERCASE123!")
        
        # No number
        with pytest.raises(ValueError, match="numero"):
            ChangePasswordRequest(current_password="oldpass", new_password="NoNumbersHere!")
        
        # Valid password
        valid = ChangePasswordRequest(current_password="oldpass", new_password="ValidPass123!")
        assert valid.new_password == "ValidPass123!"


class TestAuthService:
    """Test auth service functions with mocked dependencies."""
    
    @pytest.mark.asyncio
    async def test_login_success(self):
        """Test successful login returns tokens."""
        from app.modules.auth import service
        
        # Mock user
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = "tenant-123"
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True
        
        # Mock DB and Redis
        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()
        
        # Mock the helper functions
        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', return_value=(mock_user, mock_tenant)):
                with patch('app.modules.auth.service.verify_password_async', return_value=True):
                    with patch.object(service, '_check_tenant_active', return_value=None):
                        with patch.object(service, '_clear_login_attempts', return_value=None):
                            with patch('app.modules.auth.service.create_access_token', return_value=("access_token", "jti-123")):
                                with patch.object(service, '_create_refresh_token', return_value="refresh_token"):
                                    result = await service.login(
                                        email="test@example.com",
                                        password="password",
                                        db=mock_db,
                                        redis=mock_redis,
                                    )
        
        token_response, refresh_token = result
        assert token_response.access_token == "access_token"
        assert refresh_token == "refresh_token"
    
    @pytest.mark.asyncio
    async def test_login_invalid_password(self):
        """Test login with wrong password fails."""
        from app.modules.auth import service
        from app.core.exceptions import AuthError
        
        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.hashed_password = "hashed_password"
        mock_tenant = MagicMock()
        mock_tenant.is_active = True
        
        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()
        
        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', return_value=(mock_user, mock_tenant)):
                with patch('app.modules.auth.service.verify_password_async', return_value=False):
                    with patch.object(service, '_record_failed_attempt', return_value=None):
                        with pytest.raises(AuthError) as exc_info:
                            await service.login(
                                email="test@example.com",
                                password="wrong_password",
                                db=mock_db,
                                redis=mock_redis,
                            )
        
        assert exc_info.value.status_code == 401
    
    @pytest.mark.asyncio
    async def test_logout_revokes_tokens(self):
        """Test logout revokes access and refresh tokens."""
        from app.modules.auth import service
        
        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_redis = AsyncMock()
        
        # Mock refresh token record
        mock_refresh_token = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_refresh_token
        mock_db.execute.return_value = mock_result
        
        with patch('app.modules.auth.service.revoke_access_token', return_value=None), \
             patch('app.modules.auth.service.untrack_jti', return_value=None):
            await service.logout(
                user_id="user-123",
                jti="jti-123",
                refresh_token="refresh_token",
                db=mock_db,
                redis=mock_redis,
            )
        
        # Verify the refresh token was revoked
        assert mock_refresh_token.revoked_at is not None

    @pytest.mark.asyncio
    async def test_login_elevates_to_superadmin_for_rls_bootstrap(self):
        """Regression #125: login() must call set_tenant_context(..., is_superadmin=True)
        before any RLS-protected query, because the email-based user lookup cannot
        know the tenant at bootstrap. Without this, RLS returns 0 rows and login
        fails in production with a 401 that masks the real cause.
        """
        from app.modules.auth import service

        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.hashed_password = "hashed_password"
        mock_user.tenant_id = "tenant-123"
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()

        with patch.object(service, '_check_account_lockout', return_value=None), \
             patch.object(service, '_get_active_user', return_value=(mock_user, mock_tenant)), \
             patch('app.modules.auth.service.verify_password_async', return_value=True), \
             patch.object(service, '_check_tenant_active', return_value=None), \
             patch.object(service, '_clear_login_attempts', return_value=None), \
             patch('app.modules.auth.service.create_access_token', return_value=("access_token", "jti-123")), \
             patch.object(service, '_create_refresh_token', return_value="refresh_token"), \
             patch('app.modules.auth.service.set_tenant_context', new=AsyncMock()) as mock_set_ctx:
            await service.login(
                email="test@example.com",
                password="password",
                db=mock_db,
                redis=mock_redis,
            )

        # The fix: set_tenant_context must be called exactly once with
        # tenant_id=None and is_superadmin=True to bootstrap RLS bypass.
        mock_set_ctx.assert_awaited_once()
        call_kwargs = mock_set_ctx.await_args.kwargs
        assert call_kwargs.get("tenant_id") is None, (
            f"login() must bootstrap with tenant_id=None; got {call_kwargs.get('tenant_id')!r}"
        )
        assert call_kwargs.get("is_superadmin") is True, (
            f"login() must bootstrap with is_superadmin=True to bypass RLS; "
            f"got is_superadmin={call_kwargs.get('is_superadmin')!r}"
        )

    @pytest.mark.asyncio
    async def test_refresh_tokens_elevates_to_superadmin_for_rls_bootstrap(self):
        """Regression #125: refresh_tokens() must call set_tenant_context(..., is_superadmin=True)
        before the RefreshToken SELECT, because the lookup is by token_hash and
        no tenant context is available at this point.
        """
        from app.modules.auth import service
        from app.core.exceptions import AuthError
        from uuid import UUID

        mock_user = MagicMock()
        mock_user.id = UUID("00000000-0000-0000-0000-000000000001")
        mock_user.tenant_id = UUID("00000000-0000-0000-0000-000000000002")
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()

        # Mock the RefreshToken SELECT to return a valid record
        mock_record = MagicMock()
        mock_record.user_id = mock_user.id
        mock_record.revoked_at = None

        async def fake_scalar(stmt):
            return mock_record

        mock_db.scalar = fake_scalar
        mock_db.in_transaction = MagicMock(return_value=True)

        with patch('app.modules.auth.service.create_access_token', return_value=("access_token", "new-jti")), \
             patch('app.modules.auth.service.track_jti', new=AsyncMock()), \
             patch('app.modules.auth.service._get_active_user_by_id', new=AsyncMock(return_value=(mock_user, MagicMock(is_active=True)))), \
             patch('app.modules.auth.service._check_tenant_active', new=AsyncMock()), \
             patch('app.modules.auth.service._create_refresh_token', new=AsyncMock(return_value="new_refresh")), \
             patch('app.modules.auth.service.set_tenant_context', new=AsyncMock()) as mock_set_ctx:
            await service.refresh_tokens(
                refresh_token="some_refresh_token",
                db=mock_db,
                redis=mock_redis,
            )

        mock_set_ctx.assert_awaited_once()
        call_kwargs = mock_set_ctx.await_args.kwargs
        assert call_kwargs.get("tenant_id") is None
        assert call_kwargs.get("is_superadmin") is True


class TestAuthRouterHelpers:
    """Test auth router helper functions."""
    
    def test_set_refresh_cookie_http_only(self):
        """Test refresh cookie is set with HttpOnly flag."""
        from app.modules.auth.router import _set_refresh_cookie
        
        mock_response = MagicMock()
        _set_refresh_cookie(mock_response, "test_refresh_token")
        
        call_args = mock_response.set_cookie.call_args
        assert call_args.kwargs['httponly'] is True
        assert call_args.kwargs['path'] == "/api/v1/auth"
        assert call_args.kwargs['max_age'] == 7 * 24 * 3600  # 7 days
    
    def test_clear_refresh_cookie(self):
        """Test refresh cookie is cleared on logout."""
        from app.modules.auth.router import _clear_refresh_cookie
        
        mock_response = MagicMock()
        _clear_refresh_cookie(mock_response)
        
        call_args = mock_response.delete_cookie.call_args
        assert call_args.kwargs['path'] == "/api/v1/auth"


class TestTokenResponseSchema:
    """Test TokenResponse schema."""

    def test_token_response_defaults(self):
        """Test TokenResponse has correct defaults."""
        from app.modules.auth.schemas import TokenResponse

        response = TokenResponse(access_token="test_token", expires_in=900)
        assert response.access_token == "test_token"
        assert response.token_type == "bearer"
        assert response.expires_in == 900


class TestLoginEnumerationResistance:
    """#19 — Login failures MUST be indistinguishable.

    Unknown user, wrong password, and locked account must return the same
    public 401 shape so an attacker cannot enumerate valid accounts.
    """

    GENERIC_AUTH_FAILURE_MSG = "Credenciales incorrectas"

    @pytest.mark.asyncio
    async def test_login_unknown_user_returns_generic_401(self):
        """Unknown email returns 401 with generic non-enumerating message."""
        from app.modules.auth import service
        from app.core.exceptions import AuthError

        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()

        # User does not exist
        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', side_effect=AuthError(
                    status_code=401, detail="Credenciales incorrectas"
            )):
                with pytest.raises(AuthError) as exc_info:
                    await service.login(
                        email="noexiste@test.test",
                        password="AnyPassword123!",
                        db=mock_db,
                        redis=mock_redis,
                    )

        assert exc_info.value.status_code == 401
        # Message must NOT reveal whether user exists
        assert "no existe" not in exc_info.value.detail.lower()
        assert "no encontrado" not in exc_info.value.detail.lower()
        assert "locked" not in exc_info.value.detail.lower()
        assert "bloqueada" not in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_generic_401(self):
        """Wrong password returns 401 with same generic message as unknown user."""
        from app.modules.auth import service
        from app.core.exceptions import AuthError

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.hashed_password = "hashed_password"
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()

        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', return_value=(mock_user, mock_tenant)):
                with patch('app.modules.auth.service.verify_password_async', return_value=False):
                    with patch.object(service, '_record_failed_attempt', return_value=None):
                        with pytest.raises(AuthError) as exc_info:
                            await service.login(
                                email="admin@alpha.test",
                                password="WrongPassword!",
                                db=mock_db,
                                redis=mock_redis,
                            )

        assert exc_info.value.status_code == 401
        # Message must NOT reveal it was a password problem specifically
        assert "password" not in exc_info.value.detail.lower()
        assert "contraseña" not in exc_info.value.detail.lower()
        assert "incorrecta" in exc_info.value.detail.lower() or \
               "inválidas" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_login_locked_account_returns_401_not_429(self):
        """Locked account returns 401 (NOT 429) to avoid account-existence enumeration.

        A 429 tells the attacker "this account IS locked, hence it EXISTS".
        A 401 is indistinguishable from wrong password / unknown user.
        Internal lockout tracking remains intact.
        """
        from app.modules.auth import service
        from app.core.exceptions import AuthError

        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()

        # Simulate lockout triggered — must NOT return 429 publicly
        with patch.object(
            service, '_check_account_lockout', side_effect=AuthError(
                status_code=401, detail="Credenciales incorrectas"
            )
        ):
            with pytest.raises(AuthError) as exc_info:
                await service.login(
                    email="admin@alpha.test",
                    password="AnyPassword123!",
                    db=mock_db,
                    redis=mock_redis,
                )

        # Critical: must be 401, not 429
        assert exc_info.value.status_code == 401, \
            "Lockout must return 401 to avoid enumeration"
        # Must be same generic message
        assert "locked" not in exc_info.value.detail.lower()
        assert "bloqueada" not in exc_info.value.detail.lower()
        assert "429" not in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_login_all_failures_return_identical_public_shape(self):
        """Unknown user, wrong password, and locked account return identical 401 body.

        The public {status_code, detail} tuple must be identical across all three
        failure modes so no information about account state leaks.
        """
        from app.modules.auth import service
        from app.core.exceptions import AuthError

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.hashed_password = "hashed_password"
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()

        # --- Case 1: Unknown user ---
        unknown_user_exc = AuthError(status_code=401, detail="Credenciales incorrectas")
        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', side_effect=unknown_user_exc):
                with pytest.raises(AuthError) as exc1:
                    await service.login(
                        email="noexiste@test.test",
                        password="WrongPass!",
                        db=mock_db,
                        redis=mock_redis,
                    )

        # --- Case 2: Wrong password ---
        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', return_value=(mock_user, mock_tenant)):
                with patch('app.modules.auth.service.verify_password_async', return_value=False):
                    with patch.object(service, '_record_failed_attempt', return_value=None):
                        with pytest.raises(AuthError) as exc2:
                            await service.login(
                                email="admin@alpha.test",
                                password="WrongPass!",
                                db=mock_db,
                                redis=mock_redis,
                            )

        # --- Case 3: Locked account ---
        locked_exc = AuthError(status_code=401, detail="Credenciales incorrectas")
        with patch.object(service, '_check_account_lockout', side_effect=locked_exc):
            with pytest.raises(AuthError) as exc3:
                await service.login(
                    email="admin@alpha.test",
                    password="AnyPass!",
                    db=mock_db,
                    redis=mock_redis,
                )

        # All three must be 401
        assert exc1.value.status_code == 401
        assert exc2.value.status_code == 401
        assert exc3.value.status_code == 401

        # All three must have identical public shape
        assert exc1.value.detail == exc2.value.detail == exc3.value.detail, \
            f"All failures must return identical detail. Got: {exc1.value.detail}, {exc2.value.detail}, {exc3.value.detail}"

    @pytest.mark.asyncio
    async def test_login_inactive_user_returns_same_generic_401(self):
        """Inactive (soft-deleted) user returns same generic 401 as unknown user."""
        from app.modules.auth import service
        from app.core.exceptions import AuthError

        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()

        # User exists but is_active=False — same generic message as unknown
        inactive_exc = AuthError(status_code=401, detail="Credenciales incorrectas")
        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', side_effect=inactive_exc):
                with pytest.raises(AuthError) as exc_info:
                    await service.login(
                        email="inactive@alpha.test",
                        password="AnyPassword!",
                        db=mock_db,
                        redis=mock_redis,
                    )

        assert exc_info.value.status_code == 401
        assert "inactivo" not in exc_info.value.detail.lower()
        assert "activo" not in exc_info.value.detail.lower()


class TestLoginTenantJoinOptimization:
    """#103 — login() must NOT issue a separate Tenant SELECT.

    _get_active_user() JOINs Tenant in one SELECT, and _check_tenant_active()
    uses the pre-loaded tenant without any DB query.
    """

    @pytest.mark.asyncio
    async def test_get_active_user_issues_single_query_with_tenant_join(self):
        """_get_active_user must issue exactly ONE db.execute (the JOIN query)
        and must NOT call db.scalar — a regression adding db.scalar(select(Tenant))
        must fail this test."""
        from app.modules.auth.service import _get_active_user

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (mock_user, mock_tenant)

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(return_value=mock_result)

        user, tenant = await _get_active_user("test@example.com", mock_db)

        # Exactly ONE db.execute call (the JOIN query)
        assert mock_db.execute.await_count == 1, (
            f"_get_active_user must issue exactly 1 query (JOIN), "
            f"got {mock_db.execute.await_count}"
        )
        # No db.scalar — tenant must come from the JOIN, not a second query
        mock_db.scalar.assert_not_called()
        assert user is mock_user
        assert tenant is mock_tenant

        # Verify the statement uses an outerjoin with Tenant
        stmt = mock_db.execute.await_args.args[0]
        stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "JOIN" in stmt_str.upper(), (
            f"_get_active_user must use a JOIN query, got: {stmt_str}"
        )

    @pytest.mark.asyncio
    async def test_check_tenant_active_has_no_db_parameter(self):
        """_check_tenant_active signature must NOT accept db — it uses pre-loaded
        tenant data only. A regression re-adding db would change the signature."""
        import inspect
        from app.modules.auth.service import _check_tenant_active

        sig = inspect.signature(_check_tenant_active)
        param_names = list(sig.parameters.keys())
        assert "db" not in param_names, (
            f"_check_tenant_active must not accept 'db' parameter, "
            f"found params: {param_names}"
        )
        assert param_names == ["user", "tenant"], (
            f"_check_tenant_active must accept (user, tenant), "
            f"got: {param_names}"
        )

    @pytest.mark.asyncio
    async def test_check_tenant_active_rejects_inactive_tenant(self):
        """Inactive tenant is rejected using pre-loaded data."""
        from app.modules.auth.service import _check_tenant_active
        from app.core.exceptions import AuthError

        mock_user = MagicMock()
        mock_user.is_superadmin = False
        mock_tenant = MagicMock()
        mock_tenant.is_active = False

        with pytest.raises(AuthError) as exc_info:
            await _check_tenant_active(mock_user, mock_tenant)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_check_tenant_active_accepts_active_tenant(self):
        """Active tenant passes without error."""
        from app.modules.auth.service import _check_tenant_active

        mock_user = MagicMock()
        mock_user.is_superadmin = False
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        # Must not raise
        await _check_tenant_active(mock_user, mock_tenant)

    @pytest.mark.asyncio
    async def test_check_tenant_active_skips_for_superadmin(self):
        """Superadmin bypasses tenant check — tenant=None is fine."""
        from app.modules.auth.service import _check_tenant_active

        mock_user = MagicMock()
        mock_user.is_superadmin = True

        # Must not raise even with tenant=None
        await _check_tenant_active(mock_user, None)

    @pytest.mark.asyncio
    async def test_check_tenant_active_rejects_none_tenant_for_regular_user(self):
        """Regular user with tenant=None (e.g. tenant deleted) is rejected."""
        from app.modules.auth.service import _check_tenant_active
        from app.core.exceptions import AuthError

        mock_user = MagicMock()
        mock_user.is_superadmin = False

        with pytest.raises(AuthError) as exc_info:
            await _check_tenant_active(mock_user, None)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_path_issues_no_scalar_calls(self):
        """End-to-end login() must never call db.scalar — all data comes from
        the JOIN in _get_active_user. A regression adding db.scalar(select(Tenant))
        anywhere in the login path must fail this test."""
        from app.modules.auth import service

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.is_superadmin = False
        mock_user.hashed_password = "hashed"
        mock_user.id = "user-id-123"
        mock_user.tenant_id = "tenant-id-123"
        mock_user.role = "user"
        mock_user.email = "test@example.com"
        mock_user.last_login_at = None
        mock_tenant = MagicMock()
        mock_tenant.is_active = True
        mock_tenant.id = "tenant-id-123"

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (mock_user, mock_tenant)

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_redis = AsyncMock()

        with patch.object(service, "_check_account_lockout", return_value=None), \
             patch("app.modules.auth.service.verify_password_async", return_value=True), \
             patch.object(service, "_clear_login_attempts", return_value=None), \
             patch("app.modules.auth.service.create_access_token",
                   return_value=("access_token", "jti-123")), \
             patch.object(service, "_create_refresh_token",
                   return_value="refresh_token"), \
             patch("app.modules.auth.service.track_jti", new=AsyncMock()), \
             patch("app.modules.auth.service.set_tenant_context", new=AsyncMock()), \
             patch("app.modules.auth.service.check_redis_healthy",
                   new=AsyncMock(return_value=True)), \
             patch("app.modules.auth.service.get_event_bus",
                   new=AsyncMock(return_value=AsyncMock())):

            await service.login(
                email="test@example.com",
                password="password123",
                db=mock_db,
                redis=mock_redis,
            )

        # No db.scalar anywhere in the login path — tenant comes from JOIN
        mock_db.scalar.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_active_user_unknown_email_raises_without_tenant_query(self):
        """Unknown email raises 401 — only the single JOIN query is issued."""
        from app.modules.auth.service import _get_active_user
        from app.core.exceptions import AuthError

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthError) as exc_info:
            await _get_active_user("nobody@test.test", mock_db)

        assert exc_info.value.status_code == 401
        # Still exactly one query (the JOIN) — no fallback Tenant SELECT
        assert mock_db.execute.await_count == 1
        # No db.scalar — must not fall back to separate Tenant query
        mock_db.scalar.assert_not_called()


class TestGetActiveUserByIdTenantJoin:
    """#103 — _get_active_user_by_id must also use the JOIN optimization.

    This covers refresh_tokens and change_password paths.
    """

    @pytest.mark.asyncio
    async def test_get_active_user_by_id_issues_single_query_with_tenant_join(self):
        """_get_active_user_by_id must issue exactly ONE db.execute (the JOIN)
        and must NOT call db.scalar."""
        from app.modules.auth.service import _get_active_user_by_id
        import uuid

        user_id = uuid.uuid4()
        mock_user = MagicMock()
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (mock_user, mock_tenant)

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(return_value=mock_result)

        user, tenant = await _get_active_user_by_id(user_id, mock_db)

        assert mock_db.execute.await_count == 1
        mock_db.scalar.assert_not_called()
        assert user is mock_user
        assert tenant is mock_tenant

        # Verify the statement uses a JOIN with Tenant
        stmt = mock_db.execute.await_args.args[0]
        stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "JOIN" in stmt_str.upper(), (
            f"_get_active_user_by_id must use a JOIN query, got: {stmt_str}"
        )

    @pytest.mark.asyncio
    async def test_get_active_user_by_id_unknown_user_raises(self):
        """Unknown user_id raises 401 — only the single JOIN query is issued."""
        from app.modules.auth.service import _get_active_user_by_id
        from app.core.exceptions import AuthError
        import uuid

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthError) as exc_info:
            await _get_active_user_by_id(uuid.uuid4(), mock_db)

        assert exc_info.value.status_code == 401
        assert mock_db.execute.await_count == 1
        mock_db.scalar.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_active_user_by_id_inactive_user_raises(self):
        """Inactive user raises 401 — tenant is still loaded via JOIN."""
        from app.modules.auth.service import _get_active_user_by_id
        from app.core.exceptions import AuthError
        import uuid

        mock_user = MagicMock()
        mock_user.is_active = False
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (mock_user, mock_tenant)

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthError) as exc_info:
            await _get_active_user_by_id(uuid.uuid4(), mock_db)

        assert exc_info.value.status_code == 401
        assert mock_db.execute.await_count == 1
        mock_db.scalar.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_tokens_uses_preloaded_tenant(self):
        """refresh_tokens path: _get_active_user_by_id returns (user, tenant)
        and _check_tenant_active receives the pre-loaded tenant — not db."""
        from app.modules.auth import service
        from uuid import UUID

        mock_user = MagicMock()
        mock_user.id = UUID("00000000-0000-0000-0000-000000000001")
        mock_user.tenant_id = UUID("00000000-0000-0000-0000-000000000002")
        mock_user.role = "admin"
        mock_user.is_superadmin = False
        mock_user.is_active = True
        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_db = MagicMock(spec=AsyncSession)
        mock_redis = AsyncMock()

        # Mock the RefreshToken SELECT to return a valid record
        mock_record = MagicMock()
        mock_record.user_id = mock_user.id
        mock_record.revoked_at = None

        async def fake_scalar(stmt):
            return mock_record

        mock_db.scalar = fake_scalar
        mock_db.in_transaction = MagicMock(return_value=True)

        with patch("app.modules.auth.service.create_access_token",
                   return_value=("access_token", "new-jti")), \
             patch("app.modules.auth.service.track_jti", new=AsyncMock()), \
             patch("app.modules.auth.service._get_active_user_by_id",
                   new=AsyncMock(return_value=(mock_user, mock_tenant))) as mock_get, \
             patch("app.modules.auth.service._check_tenant_active",
                   new=AsyncMock()) as mock_check, \
             patch("app.modules.auth.service._create_refresh_token",
                   new=AsyncMock(return_value="new_refresh")), \
             patch("app.modules.auth.service.set_tenant_context",
                   new=AsyncMock()):

            await service.refresh_tokens(
                refresh_token="some_refresh_token",
                db=mock_db,
                redis=mock_redis,
            )

        mock_get.assert_awaited_once_with(mock_user.id, mock_db)
        mock_check.assert_awaited_once_with(mock_user, mock_tenant)
