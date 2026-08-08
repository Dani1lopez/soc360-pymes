from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession


def _histogram_count(histogram: object, flow: str) -> float:
    collector = next(iter(histogram.collect()))
    sample = next(
        (
            sample
            for sample in collector.samples
            if sample.name.endswith("_count") and sample.labels["flow"] == flow
        ),
        None,
    )
    return sample.value if sample is not None else 0.0


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


@pytest.mark.asyncio
async def test_login_passes_canonical_flow_label_to_event_bus() -> None:
    from app.core.outage import _FLOW_ID_AUTH_LOGIN_EVENT_PUBLISH
    from app.event_bus import EventBus
    from app.modules.auth import service

    user = SimpleNamespace(
        id=uuid4(),
        email="flow@test.com",
        hashed_password="hash",
        tenant_id=uuid4(),
        role="admin",
        is_superadmin=False,
        is_active=True,
    )
    tenant = SimpleNamespace(is_active=True)
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    redis = AsyncMock()
    event_bus = AsyncMock(spec=EventBus)

    with patch.multiple(
        service,
        check_redis_healthy=AsyncMock(return_value=True),
        _check_account_lockout=AsyncMock(),
        _get_active_user=AsyncMock(return_value=(user, tenant)),
        verify_password_async=AsyncMock(return_value=True),
        _check_tenant_active=AsyncMock(),
        _clear_login_attempts=AsyncMock(),
        create_access_token=MagicMock(return_value=("access", "jti")),
        _create_refresh_token=AsyncMock(return_value="refresh"),
        get_event_bus=AsyncMock(return_value=event_bus),
    ):
        await service.login(
            email="flow@test.com",
            password="password",
            db=db,
            redis=redis,
        )

    assert event_bus.publish.await_args.kwargs["flow"] == _FLOW_ID_AUTH_LOGIN_EVENT_PUBLISH


@pytest.mark.asyncio
async def test_event_bus_publish_records_supplied_flow_label() -> None:
    from app.event_bus import EventBus
    from app.event_schemas import AuthLoginEvent

    event = AuthLoginEvent(
        event_id=uuid4(),
        tenant_id=uuid4(),
        user_id="event-flow-user",
        email_hash="a" * 32,
    )
    redis = FakeRedis()
    try:
        with patch("app.event_bus.bus.logger.debug") as debug:
            await EventBus(redis).publish(event, flow="auth_login_event_publish")

        assert debug.call_args.kwargs["extra"]["flow"] == "auth_login_event_publish"
        assert await redis.xlen("events:auth.login") == 1
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_revocation_outage_and_latency_metrics_use_flow_label() -> None:
    from app.core.metrics import METRIC_OPERATION_LATENCY, METRIC_OUTAGES
    from app.core.security import revoke_access_token, track_jti
    from app.core.exceptions import RedisOutageError

    flow = "auth_change_password_revoke"
    outage_before = METRIC_OUTAGES.labels(flow=flow)._value.get()
    latency_before = _histogram_count(METRIC_OPERATION_LATENCY, flow)
    redis = MagicMock()
    redis.set = AsyncMock(side_effect=RedisConnectionError("redis-down"))
    redis.sadd = AsyncMock(return_value=1)

    with pytest.raises(RedisOutageError):
        await revoke_access_token("jti-metrics", 60, redis, flow_id=flow)
    await track_jti("user-metrics", "jti-metrics", redis, flow_id=flow)

    assert METRIC_OUTAGES.labels(flow=flow)._value.get() == outage_before + 1
    assert _histogram_count(METRIC_OPERATION_LATENCY, flow) == latency_before + 2


@pytest.mark.asyncio
async def test_event_bus_outage_metric_uses_supplied_flow_label() -> None:
    from app.core.exceptions import RedisOutageError
    from app.core.metrics import METRIC_OUTAGES
    from app.event_bus import EventBus
    from app.event_schemas import AuthLoginEvent

    flow = "auth_login_event_publish"
    before = METRIC_OUTAGES.labels(flow=flow)._value.get()
    redis = MagicMock()
    redis.xadd = AsyncMock(side_effect=RedisConnectionError("redis-down"))
    event = AuthLoginEvent(
        event_id=uuid4(),
        tenant_id=uuid4(),
        user_id="event-outage-user",
        email_hash="b" * 32,
    )

    with pytest.raises(RedisOutageError):
        await EventBus(redis).publish(event, flow=flow)

    assert METRIC_OUTAGES.labels(flow=flow)._value.get() == before + 1


@pytest.mark.asyncio
async def test_current_user_health_outage_metric_uses_dependency_flow_label() -> None:
    from app.core.metrics import METRIC_OUTAGES
    from app.dependencies import auth
    from app.core.exceptions import ServiceUnavailableError

    flow = "auth_current_user_dep"
    before = METRIC_OUTAGES.labels(flow=flow)._value.get()
    with (
        patch.object(auth, "decode_access_token", return_value={"sub": str(uuid4()), "jti": "jti"}),
        patch.object(auth, "check_redis_healthy", AsyncMock(return_value=False)),
    ):
        with pytest.raises(ServiceUnavailableError):
            await auth.get_current_user(token="token", db=MagicMock(), redis=MagicMock())

    assert METRIC_OUTAGES.labels(flow=flow)._value.get() == before + 1
