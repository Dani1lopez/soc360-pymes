from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RedisOutageError


_CONTRACT = "DB rolls back; Redis partial denylist retained; active_jtis kept; retry is idempotent and safe"


@pytest.mark.asyncio
async def test_change_password_contract_propagates_outage_and_allows_safe_retry() -> None:
    from app.modules.auth import service

    user = SimpleNamespace(hashed_password="old-hash")
    db = MagicMock(spec=AsyncSession)
    redis = MagicMock()
    revoke_access = AsyncMock(
        side_effect=[RedisOutageError("partial denylist"), None]
    )

    with (
        patch.object(service, "check_redis_healthy", AsyncMock(return_value=True)),
        patch.object(service, "_get_active_user_by_id", AsyncMock(return_value=(user, None))),
        patch.object(service, "verify_password_async", AsyncMock(return_value=True)),
        patch.object(service, "hash_password_async", AsyncMock(return_value="new-hash")),
        patch.object(service, "_revoke_all_user_tokens", AsyncMock()) as revoke_db,
        patch.object(service, "revoke_all_user_access_tokens", revoke_access),
    ):
        with pytest.raises(RedisOutageError):
            await service.change_password(
                user_id=uuid4(),
                current_password="OldPassword123!",
                new_password="NewPassword123!",
                current_jti="jti-1",
                db=db,
                redis=redis,
            )

        user.hashed_password = "old-hash"  # simulate the surrounding DB rollback
        await service.change_password(
            user_id=uuid4(),
            current_password="OldPassword123!",
            new_password="NewPassword123!",
            current_jti="jti-1",
            db=db,
            redis=redis,
        )

    revoke_db.assert_awaited()
    assert revoke_access.await_count == 2


def test_change_password_documents_partial_state_contract() -> None:
    from app.modules.auth import service

    assert _CONTRACT in " ".join(service.change_password.__doc__.split())


@pytest.mark.asyncio
async def test_partial_denylist_is_retained_and_retry_is_idempotent() -> None:
    from app.core.security import is_token_revoked, revoke_all_user_access_tokens

    class FailOnceRedis(FakeRedis):
        failed = False

        async def set(self, key: str, *args, **kwargs):  # type: ignore[override]
            if key == "revoked:jti-b" and not self.failed:
                self.failed = True
                raise RedisConnectionError("transient Redis failure")
            return await super().set(key, *args, **kwargs)

    redis = FailOnceRedis()
    try:
        await redis.sadd("active_jtis:contract-user", "jti-a", "jti-b")

        with pytest.raises(RedisOutageError):
            await revoke_all_user_access_tokens(
                "contract-user", redis, ttl_seconds=60
            )

        assert await redis.smembers("active_jtis:contract-user") == {
            b"jti-a",
            b"jti-b",
        }
        assert await is_token_revoked("jti-a", redis) is True

        await revoke_all_user_access_tokens("contract-user", redis, ttl_seconds=60)

        assert await redis.exists("active_jtis:contract-user") == 0
        assert await is_token_revoked("jti-a", redis) is True
        assert await is_token_revoked("jti-b", redis) is True
    finally:
        await redis.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update_user", "deactivate_user"])
async def test_user_revocation_contract_propagates_outage_and_allows_safe_retry(
    operation: str,
) -> None:
    from app.modules.users import service
    from app.modules.users.schemas import UserUpdate

    tenant_id = uuid4()
    current = SimpleNamespace(tenant_id=tenant_id, is_superadmin=True)
    target = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, is_active=True)
    db = MagicMock(spec=AsyncSession)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    revoke_access = AsyncMock(
        side_effect=[RedisOutageError("partial denylist"), None]
    )

    with (
        patch.object(service, "_revoke_all_user_tokens", AsyncMock()),
        patch.object(service, "revoke_all_user_access_tokens", revoke_access),
    ):
        if operation == "update_user":

            async def call():
                return await service.update_user(
                    current_user=current,
                    target=target,
                    data=UserUpdate(is_active=False),
                    db=db,
                    redis=object(),
                )
        else:

            async def call():
                return await service.deactivate_user(
                    current_user=current,
                    target=target,
                    db=db,
                    redis=object(),
                )
        with pytest.raises(RedisOutageError):
            await call()

        target.is_active = True  # simulate the surrounding DB rollback
        await call()

    assert revoke_access.await_count == 2


@pytest.mark.parametrize("operation", ["update_user", "deactivate_user"])
def test_user_services_document_partial_state_contract(operation: str) -> None:
    from app.modules.users import service

    assert _CONTRACT in " ".join(getattr(service, operation).__doc__.split())
