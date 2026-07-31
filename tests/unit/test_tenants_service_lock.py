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
async def test_deactivate_tenant_runs_inside_scoped_lock() -> None:
    from app.modules.tenants import service

    tenant_id = uuid4()
    tenant = SimpleNamespace(id=tenant_id, is_active=True)
    db, redis, captured = _db(tenant), AsyncMock(), {}
    with patch.multiple(
        service,
        acquire_dist_lock=MagicMock(side_effect=partial(_lock, captured=captured)),
        _revoke_all_user_tokens_for_tenant=AsyncMock(),
        revoke_all_user_access_tokens=AsyncMock(),
    ):
        result = await service.deactivate_tenant(tenant_id, db, redis)

    assert result is tenant and tenant.is_active is False
    assert captured == {
        "flow_id": "auth_tenant_deactivate_lock",
        "tenant_id": str(tenant_id),
        "asset_id": f"tenant:{tenant_id}",
        "operation": "deactivate",
        "ttl_seconds": service.settings.LOCK_DEFAULT_TTL_SECONDS,
        "wait_timeout_seconds": 2.0,
        "redis": redis,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["contention", "outage"])
async def test_deactivate_tenant_propagates_lock_failures(error: str) -> None:
    from app.core.exceptions import RedisUnreachableError, TemporaryUnavailableError
    from app.modules.tenants import service

    tenant_id = uuid4()
    tenant = SimpleNamespace(id=tenant_id, is_active=True)
    lock_error = (
        TemporaryUnavailableError("lock_timeout")
        if error == "contention"
        else RedisUnreachableError("redis unavailable")
    )
    with patch.object(
        service,
        "acquire_dist_lock",
        side_effect=partial(_lock, error=lock_error),
    ):
        with pytest.raises(type(lock_error)) as exc_info:
            await service.deactivate_tenant(tenant_id, _db(tenant), AsyncMock())
    assert exc_info.value is lock_error
