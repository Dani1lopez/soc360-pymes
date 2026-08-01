from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _db(tenant):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = tenant
    db.execute = AsyncMock(return_value=result)
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [uuid4(), uuid4()]))
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_deactivate_tenant_mutates_without_service_owned_lock() -> None:
    from app.modules.tenants import service

    tenant_id = uuid4()
    tenant = SimpleNamespace(id=tenant_id, is_active=True)
    db, redis = _db(tenant), object()
    revoke_tokens = AsyncMock()
    revoke_access_tokens = AsyncMock()

    with patch.multiple(
        service,
        _revoke_all_user_tokens_for_tenant=revoke_tokens,
        revoke_all_user_access_tokens=revoke_access_tokens,
    ):
        result = await service.deactivate_tenant(tenant_id, db, redis)

    assert result is tenant and tenant.is_active is False
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(tenant)
    revoke_tokens.assert_awaited_once_with(tenant_id, db)
    assert revoke_access_tokens.await_count == 2


@pytest.mark.asyncio
async def test_deactivate_tenant_preserves_injected_mutation_error() -> None:
    from app.core.exceptions import TemporaryUnavailableError
    from app.modules.tenants import service

    tenant_id = uuid4()
    tenant = SimpleNamespace(id=tenant_id, is_active=True)
    mutation_error = TemporaryUnavailableError("lock_timeout")

    with patch.object(
        service,
        "_revoke_all_user_tokens_for_tenant",
        AsyncMock(side_effect=mutation_error),
    ):
        with pytest.raises(TemporaryUnavailableError) as exc_info:
            await service.deactivate_tenant(tenant_id, _db(tenant), object())

    assert exc_info.value is mutation_error
