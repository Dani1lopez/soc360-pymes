from contextlib import asynccontextmanager
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@asynccontextmanager
async def _lock(*, captured=None, error=None, **kwargs):
    if captured is not None:
        captured.update(kwargs)
    if error:
        raise error
    yield None


def _user(tenant_id, active=True):
    return SimpleNamespace(id=uuid4(), tenant_id=tenant_id, is_active=active)


def _db():
    db = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_deactivate_user_runs_inside_scoped_lock() -> None:
    from app.modules.users import service

    tenant_id = uuid4()
    current = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, is_superadmin=True)
    target, redis, captured = _user(tenant_id), AsyncMock(), {}
    with patch.multiple(
        service,
        acquire_dist_lock=MagicMock(side_effect=partial(_lock, captured=captured)),
        _revoke_all_user_tokens=AsyncMock(),
        revoke_all_user_access_tokens=AsyncMock(),
    ):
        await service.deactivate_user(current, target, _db(), redis)

    assert target.is_active is False
    assert captured == {
        "flow_id": "auth_post_credential_user_deactivate_lock",
        "tenant_id": str(tenant_id),
        "asset_id": f"user:{target.id}",
        "operation": "deactivate",
        "ttl_seconds": service.settings.LOCK_DEFAULT_TTL_SECONDS,
        "wait_timeout_seconds": 2.0,
        "redis": redis,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["contention", "outage"])
async def test_deactivate_user_propagates_lock_failures(error: str) -> None:
    from app.core.exceptions import RedisUnreachableError, TemporaryUnavailableError
    from app.modules.users import service

    current = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), is_superadmin=True)
    target = _user(current.tenant_id)
    lock_error = (
        TemporaryUnavailableError("lock_timeout")
        if error == "contention"
        else RedisUnreachableError("redis unavailable")
    )
    db = _db()
    with patch.object(
        service,
        "acquire_dist_lock",
        side_effect=partial(_lock, error=lock_error),
    ):
        with pytest.raises(type(lock_error)) as exc_info:
            await service.deactivate_user(current, target, db, AsyncMock())
    assert exc_info.value is lock_error
    db.flush.assert_not_awaited()
