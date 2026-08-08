from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_revocation_primitive_carries_flow_id_to_structured_log() -> None:
    from app.core.security import revoke_access_token

    redis = FakeRedis()
    try:
        with patch("app.core.security.logger.debug") as debug:
            await revoke_access_token(
                jti="jti-flow",
                ttl_seconds=60,
                redis=redis,
                flow_id="auth_change_password_revoke",
            )

        assert debug.call_args.kwargs["extra"]["flow"] == "auth_change_password_revoke"
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_tracking_primitive_carries_flow_id_to_structured_log() -> None:
    from app.core.security import track_jti

    redis = FakeRedis()
    try:
        with patch("app.core.security.logger.debug") as debug:
            await track_jti(
                user_id="user-flow",
                jti="jti-flow",
                redis=redis,
                flow_id="auth_login_event_publish",
            )

        assert debug.call_args.kwargs["extra"]["flow"] == "auth_login_event_publish"
        assert await redis.smembers("active_jtis:user-flow") == {b"jti-flow"}
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_change_password_passes_canonical_revoke_flow_id() -> None:
    from app.core.outage import _FLOW_ID_AUTH_CHANGE_PASSWORD_REVOKE
    from app.modules.auth import service

    user = SimpleNamespace(hashed_password="old-hash")
    db = MagicMock(spec=AsyncSession)
    revoke = AsyncMock()

    with (
        patch.object(service, "check_redis_healthy", AsyncMock(return_value=True)),
        patch.object(service, "_get_active_user_by_id", AsyncMock(return_value=(user, None))),
        patch.object(service, "verify_password_async", AsyncMock(return_value=True)),
        patch.object(service, "hash_password_async", AsyncMock(return_value="new-hash")),
        patch.object(service, "_revoke_all_user_tokens", AsyncMock()),
        patch.object(service, "revoke_all_user_access_tokens", revoke),
    ):
        await service.change_password(
            user_id=uuid4(),
            current_password="OldPassword123!",
            new_password="NewPassword123!",
            current_jti="jti-1",
            db=db,
            redis=MagicMock(),
        )

    assert revoke.await_args.kwargs["flow_id"] == _FLOW_ID_AUTH_CHANGE_PASSWORD_REVOKE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "expected_flow"),
    [
        ("update_user", "users_update_user_revoke"),
        ("deactivate_user", "users_deactivate_user_revoke"),
    ],
)
async def test_user_revocation_passes_canonical_flow_id(
    operation: str,
    expected_flow: str,
) -> None:
    from app.modules.users import service
    from app.modules.users.schemas import UserUpdate

    tenant_id = uuid4()
    current = SimpleNamespace(tenant_id=tenant_id, is_superadmin=True)
    target = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, is_active=True)
    db = MagicMock(spec=AsyncSession)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    revoke = AsyncMock()

    with (
        patch.object(service, "_revoke_all_user_tokens", AsyncMock()),
        patch.object(service, "revoke_all_user_access_tokens", revoke),
    ):
        if operation == "update_user":
            await service.update_user(
                current_user=current,
                target=target,
                data=UserUpdate(is_active=False),
                db=db,
                redis=MagicMock(),
            )
        else:
            await service.deactivate_user(
                current_user=current,
                target=target,
                db=db,
                redis=MagicMock(),
            )

    assert revoke.await_args.kwargs["flow_id"] == expected_flow


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flow_id", "user_ids"),
    [
        ("tenants_update_tenant_revoke", ["user-a"]),
        ("tenants_deactivate_tenant_revoke", ["user-b"]),
    ],
)
async def test_tenant_revocation_passes_canonical_flow_id(
    flow_id: str,
    user_ids: list[str],
) -> None:
    from app.modules.tenants import service

    revoke = AsyncMock()
    with patch.object(service, "revoke_all_user_access_tokens", revoke):
        await service._revoke_user_tokens_deterministically(
            user_ids=user_ids,
            redis=MagicMock(),
            ttl_seconds=60,
            flow_id=flow_id,
        )

    assert revoke.await_args.kwargs["flow_id"] == flow_id
