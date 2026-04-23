from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestTenantSchemas:
    """Test tenant schema validation."""
    
    def test_tenant_create_validates_slug(self):
        """Test TenantCreate validates slug format."""
        from app.modules.tenants.schemas import TenantCreate
        
        # Invalid characters
        with pytest.raises(ValueError, match="minusculas"):
            TenantCreate(name="Test", slug="Invalid_Slug!")
        
        # Too short
        with pytest.raises(ValueError, match="3 y 100"):
            TenantCreate(name="Test", slug="ab")
        
        # Valid slug
        valid = TenantCreate(name="Test", slug="valid-slug-123")
        assert valid.slug == "valid-slug-123"
    
    def test_tenant_create_validates_name_not_blank(self):
        """Test TenantCreate validates name is not blank."""
        from app.modules.tenants.schemas import TenantCreate
        
        with pytest.raises(ValueError, match="vacio"):
            TenantCreate(name="   ", slug="valid-slug")
        
        valid = TenantCreate(name="  Valid Name  ", slug="valid-slug")
        assert valid.name == "Valid Name"
    
    def test_tenant_create_validates_max_assets(self):
        """Test TenantCreate validates max_assets is positive."""
        from app.modules.tenants.schemas import TenantCreate
        
        with pytest.raises(ValueError, match="al menos 1"):
            TenantCreate(name="Test", slug="test", max_assets=0)
        
        with pytest.raises(ValueError, match="al menos 1"):
            TenantCreate(name="Test", slug="test", max_assets=-1)
        
        valid = TenantCreate(name="Test", slug="test", max_assets=10)
        assert valid.max_assets == 10
    
    def test_tenant_update_validates_max_assets(self):
        """Test TenantUpdate validates max_assets if provided."""
        from app.modules.tenants.schemas import TenantUpdate
        
        with pytest.raises(ValueError, match="al menos 1"):
            TenantUpdate(max_assets=0)
        
        # None is valid (field not being updated)
        valid = TenantUpdate(max_assets=None)
        assert valid.max_assets is None
        
        # Valid positive value
        valid = TenantUpdate(max_assets=50)
        assert valid.max_assets == 50
    
    def test_tenant_settings_defaults(self):
        """Test TenantSettings has correct defaults."""
        from app.modules.tenants.schemas import TenantSettings, ScanLimits
        
        settings = TenantSettings()
        assert settings.timezone == "Europe/Madrid"
        assert settings.severity_threshold == "medium"
        assert settings.scan_schedule == "0 2 * * *"
        assert isinstance(settings.scan_limits, ScanLimits)
        assert settings.scan_limits.daily_max == 5
        assert settings.scan_limits.concurrent_max == 1


class TestTenantService:
    """Test tenant service functions."""
    
    def test_generate_slug_normalizes_name(self):
        """Test _generate_slug normalizes various inputs."""
        from app.modules.tenants.service import _generate_slug
        
        # Basic case
        assert _generate_slug("Test Tenant") == "test-tenant"
        
        # With accents
        assert _generate_slug("Tëst Ténánt") == "test-tenant"
        
        # With special chars
        assert _generate_slug("Test @ Company!") == "test-company"
        
        # Multiple spaces
        assert _generate_slug("Test    Tenant") == "test-tenant"
    
    def test_generate_slug_invalid_name(self):
        """Test _generate_slug raises error for invalid names."""
        from app.modules.tenants.service import _generate_slug, TenantError
        
        with pytest.raises(TenantError):
            _generate_slug("!!!@#$%")
    
    def test_plan_to_max_assets(self):
        """Test plan to max_assets mapping."""
        from app.modules.tenants.service import _plan_to_max_assets, TenantError
        
        assert _plan_to_max_assets("free") == 10
        assert _plan_to_max_assets("starter") == 25
        assert _plan_to_max_assets("pro") == 100
        assert _plan_to_max_assets("enterprise") == 500
        
        with pytest.raises(TenantError):
            _plan_to_max_assets("invalid_plan")
    
    @pytest.mark.asyncio
    async def test_is_slug_taken_true(self):
        """Test _is_slug_taken returns True when slug exists."""
        from app.modules.tenants import service
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1  # Slug exists
        mock_db.execute.return_value = mock_result
        
        is_taken = await service._is_slug_taken(mock_db, "existing-slug")
        
        assert is_taken is True
    
    @pytest.mark.asyncio
    async def test_is_slug_taken_false(self):
        """Test _is_slug_taken returns False when slug doesn't exist."""
        from app.modules.tenants import service
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0  # Slug doesn't exist
        mock_db.execute.return_value = mock_result
        
        is_taken = await service._is_slug_taken(mock_db, "new-slug")
        
        assert is_taken is False
    
    @pytest.mark.asyncio
    async def test_get_tenant_by_id_found(self):
        """Test getting existing tenant by ID."""
        from app.modules.tenants import service
        
        mock_tenant = MagicMock()
        mock_tenant.id = uuid4()
        mock_tenant.name = "Found Tenant"
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant
        mock_db.execute.return_value = mock_result
        
        tenant = await service.get_tenant_by_id(tenant_id=mock_tenant.id, db=mock_db)
        
        assert tenant == mock_tenant
        assert tenant.name == "Found Tenant"
    
    @pytest.mark.asyncio
    async def test_get_tenant_by_id_not_found(self):
        """Test getting non-existent tenant returns None."""
        from app.modules.tenants import service
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        tenant = await service.get_tenant_by_id(tenant_id=uuid4(), db=mock_db)
        
        assert tenant is None
    
    @pytest.mark.asyncio
    async def test_update_tenant_not_found(self):
        """Test updating non-existent tenant fails."""
        from app.modules.tenants import service
        from app.core.exceptions import TenantError
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        
        from app.modules.tenants.schemas import TenantUpdate
        data = TenantUpdate(name="New Name")
        
        with pytest.raises(TenantError) as exc_info:
            await service.update_tenant(tenant_id=uuid4(), data=data, db=mock_db, redis=AsyncMock())
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_deactivate_tenant_already_inactive(self):
        """Test deactivating already inactive tenant fails."""
        from app.modules.tenants import service
        from app.core.exceptions import TenantError
        
        mock_tenant = MagicMock()
        mock_tenant.is_active = False
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant
        mock_db.execute.return_value = mock_result
        
        with pytest.raises(TenantError) as exc_info:
            await service.deactivate_tenant(tenant_id=uuid4(), db=mock_db, redis=AsyncMock())
        
        assert exc_info.value.status_code == 409
    
    @pytest.mark.asyncio
    async def test_update_tenant_plan_updates_max_assets(self):
        """Test updating plan auto-updates max_assets."""
        from app.modules.tenants import service
        
        mock_tenant = MagicMock()
        mock_tenant.id = uuid4()
        mock_tenant.plan = "free"
        mock_tenant.max_assets = 10
        
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant
        mock_db.execute.return_value = mock_result
        
        from app.modules.tenants.schemas import TenantUpdate
        data = TenantUpdate(plan="pro")
        
        updated = await service.update_tenant(
            tenant_id=mock_tenant.id,
            data=data,
            db=mock_db,
            redis=AsyncMock(),
        )
        
        assert updated.plan == "pro"
        assert updated.max_assets == 100  # pro plan limit


class TestTenantResponseSchema:
    """Test TenantResponse schema."""
    
    def test_tenant_response_from_attributes(self):
        """Test TenantResponse can be created from ORM object."""
        from app.modules.tenants.schemas import TenantResponse, TenantSettings
        from datetime import datetime
        from uuid import UUID
        
        # Simulate ORM object
        class MockTenant:
            id = UUID("12345678-1234-1234-1234-123456789abc")
            name = "Test Tenant"
            slug = "test-tenant"
            plan = "pro"
            is_active = True
            max_assets = 100
            settings = None  # Should use default
            created_at = datetime.now()
            updated_at = datetime.now()
        
        response = TenantResponse.model_validate(MockTenant())
        assert response.name == "Test Tenant"
        assert response.slug == "test-tenant"
        assert isinstance(response.settings, TenantSettings)
    
    def test_tenant_response_settings_default_if_none(self):
        """Test settings_default_if_none validator."""
        from app.modules.tenants.schemas import TenantResponse
        
        # Test the validator directly
        result = TenantResponse.settings_default_if_none(None)
        assert result == {}
        
        result = TenantResponse.settings_default_if_none({"key": "value"})
        assert result == {"key": "value"}


class TestUpdateTenantTokenRevocation:
    """Test that update_tenant revokes tokens on deactivation transition."""

    @pytest.mark.asyncio
    async def test_update_tenant_deactivate_revokes_tokens(self):
        """update_tenant con is_active=True→False llama a revocacion de tokens."""
        from app.modules.tenants import service
        from app.modules.tenants.schemas import TenantUpdate
        from uuid import uuid4

        tenant_id = uuid4()
        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id
        mock_tenant.is_active = True

        user1 = uuid4()
        user2 = uuid4()
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.scalars = AsyncMock(return_value=[user1, user2])

        mock_redis = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant
        mock_db.execute.return_value = mock_result

        data = TenantUpdate(is_active=False)

        with patch.object(service, "_revoke_all_user_tokens_for_tenant", new_callable=AsyncMock) as mock_revoke_refresh, \
             patch("app.modules.tenants.service.revoke_all_user_access_tokens", new_callable=AsyncMock) as mock_revoke_access:
            await service.update_tenant(tenant_id=tenant_id, data=data, db=mock_db, redis=mock_redis)

            mock_revoke_refresh.assert_awaited_once_with(tenant_id, mock_db)
            assert mock_revoke_access.await_count == 2

    @pytest.mark.asyncio
    async def test_update_tenant_deactivate_already_inactive_no_revocation(self):
        """update_tenant con is_active=False sobre tenant ya inactivo NO revoca tokens."""
        from app.modules.tenants import service
        from app.modules.tenants.schemas import TenantUpdate
        from uuid import uuid4

        tenant_id = uuid4()
        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id
        mock_tenant.is_active = False  # ya inactivo

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.scalars = AsyncMock(return_value=[])

        mock_redis = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant
        mock_db.execute.return_value = mock_result

        data = TenantUpdate(is_active=False)

        with patch.object(service, "_revoke_all_user_tokens_for_tenant", new_callable=AsyncMock) as mock_revoke_refresh, \
             patch("app.modules.tenants.service.revoke_all_user_access_tokens", new_callable=AsyncMock) as mock_revoke_access:
            await service.update_tenant(tenant_id=tenant_id, data=data, db=mock_db, redis=mock_redis)

            mock_revoke_refresh.assert_not_awaited()
            mock_revoke_access.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tenant_reactivate_no_revocation(self):
        """update_tenant con is_active=False→True NO revoca tokens (reactivacion)."""
        from app.modules.tenants import service
        from app.modules.tenants.schemas import TenantUpdate
        from uuid import uuid4

        tenant_id = uuid4()
        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id
        mock_tenant.is_active = False  # inactivo, se va a reactivar

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.scalars = AsyncMock(return_value=[])

        mock_redis = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant
        mock_db.execute.return_value = mock_result

        data = TenantUpdate(is_active=True)

        with patch.object(service, "_revoke_all_user_tokens_for_tenant", new_callable=AsyncMock) as mock_revoke_refresh, \
             patch("app.modules.tenants.service.revoke_all_user_access_tokens", new_callable=AsyncMock) as mock_revoke_access:
            await service.update_tenant(tenant_id=tenant_id, data=data, db=mock_db, redis=mock_redis)

            mock_revoke_refresh.assert_not_awaited()
            mock_revoke_access.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_tenant_patch_without_is_active_no_revocation(self):
        """update_tenant sin cambio de is_active NO revoca tokens."""
        from app.modules.tenants import service
        from app.modules.tenants.schemas import TenantUpdate
        from uuid import uuid4

        tenant_id = uuid4()
        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id
        mock_tenant.is_active = True
        mock_tenant.plan = "free"
        mock_tenant.max_assets = 10

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.scalars = AsyncMock(return_value=[])

        mock_redis = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant
        mock_db.execute.return_value = mock_result

        data = TenantUpdate(plan="pro")

        with patch.object(service, "_revoke_all_user_tokens_for_tenant", new_callable=AsyncMock) as mock_revoke_refresh, \
             patch("app.modules.tenants.service.revoke_all_user_access_tokens", new_callable=AsyncMock) as mock_revoke_access:
            await service.update_tenant(tenant_id=tenant_id, data=data, db=mock_db, redis=mock_redis)

            mock_revoke_refresh.assert_not_awaited()
            mock_revoke_access.assert_not_awaited()
