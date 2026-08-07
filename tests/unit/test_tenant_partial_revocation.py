from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import PartialFailureError, RedisOutageError
from app.core.redis import get_redis
from app.dependencies import get_tenant_deactivation_db, require_superadmin


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_index", [0, 1, 2])
async def test_tenant_revocations_aggregate_failures_in_user_order(
    failure_index: int,
) -> None:
    from app.modules.tenants import service

    user_ids = ["user-a", "user-b", "user-c"]
    failures = [
        None,
        RedisOutageError("redis failure"),
        None,
    ]
    failures[failure_index] = RedisOutageError(f"failure-{failure_index}")
    revoke = AsyncMock(side_effect=failures)

    with patch.object(service, "revoke_all_user_access_tokens", revoke):
        with pytest.raises(PartialFailureError) as exc_info:
            await service._revoke_user_tokens_deterministically(
                user_ids=user_ids,
                redis=MagicMock(),
                ttl_seconds=60,
            )

    assert str(exc_info.value).index("user-a") < str(exc_info.value).index("user-b")
    assert str(exc_info.value).index("user-b") < str(exc_info.value).index("user-c")
    assert f"failure-{failure_index}" in str(exc_info.value)
    assert revoke.await_count == len(user_ids)


@pytest.mark.asyncio
async def test_tenant_revocations_complete_all_users_when_no_failure() -> None:
    from app.modules.tenants import service

    revoke = AsyncMock()
    with patch.object(service, "revoke_all_user_access_tokens", revoke):
        result = await service._revoke_user_tokens_deterministically(
            user_ids=["user-a", "user-b"],
            redis=MagicMock(),
            ttl_seconds=60,
        )

    assert result is None
    assert [call.kwargs["user_id"] for call in revoke.await_args_list] == [
        "user-a",
        "user-b",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update_tenant", "deactivate_tenant"])
async def test_tenant_mutations_raise_partial_failure_after_all_revocations(
    operation: str,
) -> None:
    from app.modules.tenants import service
    from app.modules.tenants.schemas import TenantUpdate

    tenant_id = uuid4()
    tenant = SimpleNamespace(id=tenant_id, is_active=True)
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [uuid4(), uuid4()]
    db.scalars = AsyncMock(return_value=scalar_result)
    lookup_result = MagicMock()
    lookup_result.scalar_one_or_none.return_value = tenant
    db.execute.return_value = lookup_result
    revoke = AsyncMock(
        side_effect=[RedisOutageError("first user failed"), None]
    )

    with (
        patch.object(service, "_revoke_all_user_tokens_for_tenant", AsyncMock()),
        patch.object(service, "revoke_all_user_access_tokens", revoke),
    ):
        with pytest.raises(PartialFailureError):
            if operation == "update_tenant":
                await service.update_tenant(
                    tenant_id, TenantUpdate(is_active=False), db, MagicMock()
                )
            else:
                await service.deactivate_tenant(tenant_id, db, MagicMock())

    assert tenant.is_active is False
    assert revoke.await_count == 2
    db.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_tenant_deactivation_partial_failure_uses_global_sanitized_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.tenants import service
    from app.main import create_app

    monkeypatch.setattr(settings, "REDIS_OUTAGE_RETRY_AFTER_SECONDS", 37)
    app = create_app()

    async def override_db():
        return MagicMock()

    async def override_redis():
        return MagicMock()

    async def override_tenant_db():
        yield MagicMock()

    async def override_superadmin():
        return SimpleNamespace(is_superadmin=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = override_redis
    app.dependency_overrides[get_tenant_deactivation_db] = override_tenant_db
    app.dependency_overrides[require_superadmin] = override_superadmin

    with patch.object(
        service,
        "deactivate_tenant",
        AsyncMock(side_effect=PartialFailureError("user-b: RedisOutageError")),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.delete(f"/api/v1/tenants/{uuid4()}")

    assert response.status_code == 503
    assert response.json() == {"detail": "service temporarily unavailable"}
    assert response.headers["Retry-After"] == "37"
    assert "user-b" not in response.text
