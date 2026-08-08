from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.outage import (
    _FLOW_ID_AUTH_CHANGE_PASSWORD_REVOKE,
    _FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE,
    _FLOW_ID_USERS_DEACTIVATE_USER_REVOKE,
    _FLOW_ID_USERS_UPDATE_USER_REVOKE,
)


@pytest.mark.asyncio
async def test_change_password_passes_revocation_flow_id() -> None:
    from app.modules.auth import service

    user_id = uuid4()
    user = SimpleNamespace(id=user_id, hashed_password="old-hash")
    db = MagicMock()
    db.flush = AsyncMock()
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
            user_id=user_id,
            current_password="old-password",
            new_password="New-password-1!",
            current_jti="current-jti",
            db=db,
            redis=MagicMock(),
        )

    assert revoke.await_args.kwargs["flow_id"] == _FLOW_ID_AUTH_CHANGE_PASSWORD_REVOKE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "flow_id"),
    [
        ("update", _FLOW_ID_USERS_UPDATE_USER_REVOKE),
        ("deactivate", _FLOW_ID_USERS_DEACTIVATE_USER_REVOKE),
    ],
)
async def test_user_revocation_call_sites_pass_flow_id(operation: str, flow_id: str) -> None:
    from app.modules.users import service
    from app.modules.users.schemas import UserUpdate

    target = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), is_active=True)
    current = SimpleNamespace(is_superadmin=True, tenant_id=None)
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    revoke = AsyncMock()

    with (
        patch.object(service, "_revoke_all_user_tokens", AsyncMock()),
        patch.object(service, "revoke_all_user_access_tokens", revoke),
    ):
        if operation == "update":
            await service.update_user(current, target, UserUpdate(is_active=False), db, MagicMock())
        else:
            await service.deactivate_user(current, target, db, MagicMock())

    assert revoke.await_args.kwargs["flow_id"] == flow_id


@pytest.mark.asyncio
async def test_tenant_revocation_call_site_passes_flow_id() -> None:
    from app.modules.tenants import service

    revoke = AsyncMock()
    with patch.object(service, "revoke_all_user_access_tokens", revoke):
        await service._revoke_user_tokens_deterministically(
            user_ids=["user-a"],
            redis=MagicMock(),
            ttl_seconds=60,
            flow_id=_FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE,
        )

    assert revoke.await_args.kwargs["flow_id"] == _FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE
