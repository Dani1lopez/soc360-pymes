from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestUserSchemas:
    """Test user schema validation."""
    
    def test_user_create_validates_superadmin_consistency(self):
        """Test UserCreate validates superadmin fields."""
        from app.modules.users.schemas import UserCreate, RoleEnum
        
        # Superadmin with tenant - should fail
        with pytest.raises(ValueError, match="superadmin no puede pertenecer"):
            UserCreate(
                email="test@test.com",
                password="password123",
                full_name="Test User",
                role=RoleEnum.superadmin,
                tenant_id=uuid4(),
                is_superadmin=True,
            )
        
        # Normal user without tenant - should fail
        with pytest.raises(ValueError, match="usuario normal debe tener"):
            UserCreate(
                email="test@test.com",
                password="password123",
                full_name="Test User",
                role=RoleEnum.admin,
                tenant_id=None,
                is_superadmin=False,
            )
        
        # Superadmin with wrong role - should fail
        with pytest.raises(ValueError, match="is_superadmin=True requiere"):
            UserCreate(
                email="test@test.com",
                password="password123",
                full_name="Test User",
                role=RoleEnum.admin,
                tenant_id=None,
                is_superadmin=True,
            )
        
        # Valid normal user
        valid = UserCreate(
            email="test@test.com",
            password="password123",
            full_name="Test User",
            role=RoleEnum.admin,
            tenant_id=uuid4(),
            is_superadmin=False,
        )
        assert valid.email == "test@test.com"
    
    def test_user_update_prevents_superadmin_assignment(self):
        """Test UserUpdate prevents assigning superadmin role."""
        from app.modules.users.schemas import UserUpdate, RoleEnum
        
        with pytest.raises(ValueError, match="superadmin"):
            UserUpdate(role=RoleEnum.superadmin)
        
        # Valid update
        valid = UserUpdate(full_name="New Name")
        assert valid.full_name == "New Name"


class TestUserService:
    """Test user service functions."""
    
    @pytest.mark.asyncio
    async def test_create_user_email_taken(self):
        """Test creating user with taken email fails."""
        from app.modules.users import service
        from app.core.exceptions import UserError
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1  # Email exists
        mock_db.execute.return_value = mock_result
        
        from app.modules.users.schemas import UserCreate, RoleEnum
        data = UserCreate(
            email="taken@test.com",
            password="password123",
            full_name="Test User",
            role=RoleEnum.viewer,
            tenant_id=uuid4(),
        )
        
        with pytest.raises(UserError) as exc_info:
            await service.create_user(data=data, db=mock_db)
        
        assert exc_info.value.status_code == 409
        assert "email" in exc_info.value.detail.lower()
    
    @pytest.mark.asyncio
    async def test_get_user_by_id_found(self):
        """Test getting existing user by ID."""
        from app.modules.users import service
        
        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "found@test.com"
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result
        
        user = await service.get_user_by_id(user_id=mock_user.id, db=mock_db)
        
        assert user == mock_user
        assert user.email == "found@test.com"
    
    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self):
        """Test getting non-existent user returns None."""
        from app.modules.users import service
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        user = await service.get_user_by_id(user_id=uuid4(), db=mock_db)
        
        assert user is None
    
    @pytest.mark.asyncio
    async def test_update_user_not_found(self):
        """Test updating non-existent user fails."""
        from app.modules.users import service
        from app.core.exceptions import UserError
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        from app.modules.users.schemas import UserUpdate
        data = UserUpdate(full_name="New Name")
        
        with pytest.raises(UserError) as exc_info:
            await service.update_user(user_id=uuid4(), data=data, db=mock_db, redis=AsyncMock())
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_deactivate_user_already_inactive(self):
        """Test deactivating already inactive user fails."""
        from app.modules.users import service
        from app.core.exceptions import UserError
        
        mock_user = MagicMock()
        mock_user.is_active = False
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(UserError) as exc_info:
            await service.deactivate_user(user_id=uuid4(), db=mock_db, redis=AsyncMock())
        
        assert exc_info.value.status_code == 409


class TestUserRoleHierarchy:
    """Test role hierarchy logic."""
    
    def test_role_enum_values(self):
        """Test RoleEnum has expected values."""
        from app.modules.users.schemas import RoleEnum
        
        assert RoleEnum.viewer == "viewer"
        assert RoleEnum.analyst == "analyst"
        assert RoleEnum.ingestor == "ingestor"
        assert RoleEnum.admin == "admin"
        assert RoleEnum.superadmin == "superadmin"


class TestUserResponseSchema:
    """Test UserResponse schema."""
    
    def test_user_response_from_attributes(self):
        """Test UserResponse can be created from ORM object."""
        from app.modules.users.schemas import UserResponse, RoleEnum
        from datetime import datetime
        from uuid import UUID
        
        # Simulate ORM object
        class MockUser:
            id = UUID("12345678-1234-1234-1234-123456789abc")
            tenant_id = UUID("87654321-4321-4321-4321-cba987654321")
            email = "test@example.com"
            full_name = "Test User"
            role = RoleEnum.admin
            is_active = True
            is_superadmin = False
            created_at = datetime.now()
            updated_at = datetime.now()
        
        response = UserResponse.model_validate(MockUser())
        assert response.email == "test@example.com"
        assert response.role == RoleEnum.admin
        assert response.is_active is True


class TestUpdateUserTokenRevocation:
    """Test that update_user revokes tokens on deactivation transition."""

    @pytest.mark.asyncio
    async def test_update_user_deactivate_revokes_tokens(self):
        """update_user con is_active=True→False llama a revocacion de tokens."""
        from app.modules.users import service
        from app.modules.users.schemas import UserUpdate
        from uuid import uuid4

        user_id = uuid4()
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.is_active = True

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_redis = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        data = UserUpdate(is_active=False)

        with patch("app.modules.users.service._revoke_all_user_tokens", new_callable=AsyncMock) as mock_revoke_refresh, \
             patch("app.modules.users.service.revoke_all_user_access_tokens", new_callable=AsyncMock) as mock_revoke_access:
            await service.update_user(user_id=user_id, data=data, db=mock_db, redis=mock_redis)

            mock_revoke_refresh.assert_awaited_once_with(user_id, mock_db)
            mock_revoke_access.assert_awaited_once()
            call_kwargs = mock_revoke_access.await_args.kwargs
            assert call_kwargs["user_id"] == str(user_id)
            assert call_kwargs["redis"] == mock_redis

    @pytest.mark.asyncio
    async def test_update_user_deactivate_already_inactive_no_revocation(self):
        """update_user con is_active=False sobre usuario ya inactivo NO revoca tokens."""
        from app.modules.users import service
        from app.modules.users.schemas import UserUpdate
        from uuid import uuid4

        user_id = uuid4()
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.is_active = False  # ya inactivo

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_redis = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        data = UserUpdate(is_active=False)

        with patch("app.modules.users.service._revoke_all_user_tokens", new_callable=AsyncMock) as mock_revoke_refresh, \
             patch("app.modules.users.service.revoke_all_user_access_tokens", new_callable=AsyncMock) as mock_revoke_access:
            await service.update_user(user_id=user_id, data=data, db=mock_db, redis=mock_redis)

            mock_revoke_refresh.assert_not_awaited()
            mock_revoke_access.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_user_reactivate_no_revocation(self):
        """update_user con is_active=False→True NO revoca tokens (reactivacion)."""
        from app.modules.users import service
        from app.modules.users.schemas import UserUpdate
        from uuid import uuid4

        user_id = uuid4()
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.is_active = False  # inactivo, se va a reactivar

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_redis = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        data = UserUpdate(is_active=True)

        with patch("app.modules.users.service._revoke_all_user_tokens", new_callable=AsyncMock) as mock_revoke_refresh, \
             patch("app.modules.users.service.revoke_all_user_access_tokens", new_callable=AsyncMock) as mock_revoke_access:
            await service.update_user(user_id=user_id, data=data, db=mock_db, redis=mock_redis)

            mock_revoke_refresh.assert_not_awaited()
            mock_revoke_access.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_user_patch_without_is_active_no_revocation(self):
        """update_user sin cambio de is_active NO revoca tokens."""
        from app.modules.users import service
        from app.modules.users.schemas import UserUpdate
        from uuid import uuid4

        user_id = uuid4()
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.is_active = True

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_redis = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        data = UserUpdate(full_name="New Name")

        with patch("app.modules.users.service._revoke_all_user_tokens", new_callable=AsyncMock) as mock_revoke_refresh, \
             patch("app.modules.users.service.revoke_all_user_access_tokens", new_callable=AsyncMock) as mock_revoke_access:
            await service.update_user(user_id=user_id, data=data, db=mock_db, redis=mock_redis)

            mock_revoke_refresh.assert_not_awaited()
            mock_revoke_access.assert_not_awaited()
