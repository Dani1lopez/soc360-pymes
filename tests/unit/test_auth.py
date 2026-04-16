from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
        
        # Mock DB and Redis
        mock_db = AsyncMock()
        mock_redis = AsyncMock()
        
        # Mock the helper functions
        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', return_value=mock_user):
                with patch('app.modules.auth.service.verify_password', return_value=True):
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
        
        mock_db = AsyncMock()
        mock_redis = AsyncMock()
        
        with patch.object(service, '_check_account_lockout', return_value=None):
            with patch.object(service, '_get_active_user', return_value=mock_user):
                with patch('app.modules.auth.service.verify_password', return_value=False):
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
        
        mock_db = AsyncMock()
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
