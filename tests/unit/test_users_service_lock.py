from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _user(tenant_id, active=True):
    return SimpleNamespace(id=uuid4(), tenant_id=tenant_id, is_active=active)


def _db():
    db = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_deactivate_user_mutates_without_service_owned_lock() -> None:
    from app.modules.users import service

    tenant_id = uuid4()
    current = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, is_superadmin=True)
    target, redis, db = _user(tenant_id), object(), _db()
    revoke_tokens = AsyncMock()
    revoke_access_tokens = AsyncMock()

    with patch.multiple(
        service,
        _revoke_all_user_tokens=revoke_tokens,
        revoke_all_user_access_tokens=revoke_access_tokens,
    ):
        await service.deactivate_user(current, target, db, redis)

    assert target.is_active is False
    db.flush.assert_awaited_once()
    revoke_tokens.assert_awaited_once_with(target.id, db)
    revoke_access_tokens.assert_awaited_once_with(
        user_id=str(target.id),
        redis=redis,
        ttl_seconds=service.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@pytest.mark.asyncio
async def test_deactivate_user_preserves_injected_mutation_error() -> None:
    from app.core.exceptions import TemporaryUnavailableError
    from app.modules.users import service

    tenant_id = uuid4()
    current = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, is_superadmin=True)
    target, db = _user(tenant_id), _db()
    mutation_error = TemporaryUnavailableError("lock_timeout")

    with patch.object(
        service,
        "_revoke_all_user_tokens",
        AsyncMock(side_effect=mutation_error),
    ):
        with pytest.raises(TemporaryUnavailableError) as exc_info:
            await service.deactivate_user(current, target, db, object())

    assert exc_info.value is mutation_error
