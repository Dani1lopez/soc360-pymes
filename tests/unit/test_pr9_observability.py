from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
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


@pytest.mark.parametrize(
    ("relative_path", "flow_constant"),
    [
        ("app/modules/auth/service.py", "_FLOW_ID_AUTH_CHANGE_PASSWORD_REVOKE"),
        ("app/modules/users/service.py", "_FLOW_ID_USERS_UPDATE_USER_REVOKE"),
        ("app/modules/users/service.py", "_FLOW_ID_USERS_DEACTIVATE_USER_REVOKE"),
        ("app/modules/tenants/service.py", "_FLOW_ID_TENANTS_UPDATE_TENANT_REVOKE"),
        ("app/modules/tenants/service.py", "_FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE"),
    ],
)
def test_revocation_call_sites_pass_catalog_flow_ids(
    relative_path: str,
    flow_constant: str,
) -> None:
    source = (Path(__file__).parents[2] / relative_path).read_text(encoding="utf-8")
    assert f"flow_id={flow_constant}" in source


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


@pytest.mark.asyncio
async def test_login_retry_records_retry_metric_with_publish_flow() -> None:
    from app.core.exceptions import RedisOutageError
    from app.core.metrics import METRIC_RETRY
    from app.core.outage import _FLOW_ID_AUTH_LOGIN_EVENT_PUBLISH
    from tests.unit.test_auth_service_event_publish import _login_with_publish_side_effect

    before = METRIC_RETRY.labels(flow=_FLOW_ID_AUTH_LOGIN_EVENT_PUBLISH)._value.get()
    result, event_bus = await _login_with_publish_side_effect(
        [RedisOutageError("first outage"), RedisOutageError("second outage")]
    )

    assert result[0].access_token == "access_token"
    assert event_bus.publish.await_count == 2
    assert (
        METRIC_RETRY.labels(flow=_FLOW_ID_AUTH_LOGIN_EVENT_PUBLISH)._value.get()
        == before + 1
    )


@pytest.mark.asyncio
async def test_tenant_partial_revocation_records_metric_with_flow() -> None:
    from app.core.exceptions import PartialFailureError, RedisOutageError
    from app.core.metrics import METRIC_PARTIAL_REVOCATION
    from app.core.outage import _FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE
    from app.modules.tenants import service

    flow = _FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE
    before = METRIC_PARTIAL_REVOCATION.labels(flow=flow)._value.get()
    revoke = AsyncMock(side_effect=[RedisOutageError("first"), None])

    with patch.object(service, "revoke_all_user_access_tokens", revoke):
        with pytest.raises(PartialFailureError):
            await service._revoke_user_tokens_deterministically(
                user_ids=["user-a", "user-b"],
                redis=MagicMock(),
                ttl_seconds=60,
                flow_id=flow,
            )

    assert METRIC_PARTIAL_REVOCATION.labels(flow=flow)._value.get() == before + 1


@pytest.mark.asyncio
async def test_security_partial_revocation_records_metric_with_flow() -> None:
    from app.core.exceptions import RedisOutageError
    from app.core.metrics import METRIC_PARTIAL_REVOCATION
    from app.core.security import revoke_all_user_access_tokens

    flow = "users_update_user_revoke"

    class FailingRedis(FakeRedis):
        async def smembers(self, key: str):  # type: ignore[override]
            return [b"jti-a", b"jti-b"]

        async def set(self, key: str, *args, **kwargs):  # type: ignore[override]
            if key == "revoked:jti-b":
                raise RedisConnectionError("partial outage")
            return await super().set(key, *args, **kwargs)

    redis = FailingRedis()
    before = METRIC_PARTIAL_REVOCATION.labels(flow=flow)._value.get()
    try:
        with pytest.raises(RedisOutageError):
            await revoke_all_user_access_tokens(
                user_id="partial-metric-user",
                redis=redis,
                ttl_seconds=60,
                flow_id=flow,
            )
    finally:
        await redis.aclose()

    assert METRIC_PARTIAL_REVOCATION.labels(flow=flow)._value.get() == before + 1


@pytest.mark.asyncio
async def test_security_zero_success_is_not_counted_as_partial_revocation() -> None:
    from app.core.exceptions import RedisOutageError
    from app.core.metrics import METRIC_PARTIAL_REVOCATION
    from app.core.security import revoke_all_user_access_tokens

    flow = "users_update_user_revoke"
    before = METRIC_PARTIAL_REVOCATION.labels(flow=flow)._value.get()
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value=[b"jti-only"])
    redis.set = AsyncMock(side_effect=RedisConnectionError("outage-before-write"))

    with pytest.raises(RedisOutageError):
        await revoke_all_user_access_tokens(
            user_id="zero-success-user",
            redis=redis,
            ttl_seconds=60,
            flow_id=flow,
        )

    assert METRIC_PARTIAL_REVOCATION.labels(flow=flow)._value.get() == before


def test_partial_rate_limit_recorder_uses_canonical_flow_label() -> None:
    from app.core.metrics import METRIC_PARTIAL_RATE_LIMIT
    from app.core.outage import _FLOW_ID_AUTH_LOGIN_RATE_RECORD
    from app.modules.auth.router import _record_partial_rate_limit

    before = METRIC_PARTIAL_RATE_LIMIT.labels(flow=_FLOW_ID_AUTH_LOGIN_RATE_RECORD)._value.get()
    _record_partial_rate_limit(_FLOW_ID_AUTH_LOGIN_RATE_RECORD)

    assert (
        METRIC_PARTIAL_RATE_LIMIT.labels(flow=_FLOW_ID_AUTH_LOGIN_RATE_RECORD)._value.get()
        == before + 1
    )


@pytest.mark.asyncio
async def test_login_rate_precheck_redis_error_records_outage_not_partial_rate_limit() -> None:
    from fastapi import HTTPException

    from app.core.metrics import METRIC_OUTAGES, METRIC_PARTIAL_RATE_LIMIT
    from app.core.outage import _FLOW_ID_AUTH_LOGIN_RATE_PRECHECK
    from app.modules.auth import router as auth_router
    from app.modules.auth.schemas import LoginRequest

    flow = _FLOW_ID_AUTH_LOGIN_RATE_PRECHECK
    outages_before = METRIC_OUTAGES.labels(flow=flow)._value.get()
    partial_before = METRIC_PARTIAL_RATE_LIMIT.labels(flow=flow)._value.get()
    rate_limiter = MagicMock()
    rate_limiter.check = AsyncMock(side_effect=RedisError("redis-down"))

    with patch.object(auth_router.settings, "RATE_LIMIT_ENABLED", True):
        with pytest.raises(HTTPException) as exc_info:
            await auth_router.login(
                body=LoginRequest(email="precheck@test.com", password="Password123!"),
                request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={}),
                response=MagicMock(),
                db=MagicMock(),
                redis=MagicMock(),
                rate_limiter=rate_limiter,
            )

    assert exc_info.value.status_code == 401
    assert METRIC_OUTAGES.labels(flow=flow)._value.get() == outages_before + 1
    assert METRIC_PARTIAL_RATE_LIMIT.labels(flow=flow)._value.get() == partial_before


@pytest.mark.asyncio
async def test_login_rate_precheck_generic_error_records_no_metric() -> None:
    from app.core.metrics import METRIC_OUTAGES, METRIC_PARTIAL_RATE_LIMIT
    from app.core.outage import _FLOW_ID_AUTH_LOGIN_RATE_PRECHECK
    from app.modules.auth import router as auth_router
    from app.modules.auth.schemas import LoginRequest, TokenResponse

    flow = _FLOW_ID_AUTH_LOGIN_RATE_PRECHECK
    outages_before = METRIC_OUTAGES.labels(flow=flow)._value.get()
    partial_before = METRIC_PARTIAL_RATE_LIMIT.labels(flow=flow)._value.get()
    rate_limiter = MagicMock()
    rate_limiter.check = AsyncMock(side_effect=RuntimeError("unexpected"))
    rate_limiter.record_success = AsyncMock()

    with (
        patch.object(auth_router.settings, "RATE_LIMIT_ENABLED", True),
        patch.object(
            auth_router.service,
            "login",
            AsyncMock(return_value=(TokenResponse(access_token="access", expires_in=60), "refresh")),
        ),
    ):
        result = await auth_router.login(
            body=LoginRequest(email="generic@test.com", password="Password123!"),
            request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={}),
            response=MagicMock(),
            db=MagicMock(),
            redis=MagicMock(),
            rate_limiter=rate_limiter,
        )

    assert result.access_token == "access"
    assert METRIC_OUTAGES.labels(flow=flow)._value.get() == outages_before
    assert METRIC_PARTIAL_RATE_LIMIT.labels(flow=flow)._value.get() == partial_before


@pytest.mark.asyncio
async def test_login_rate_record_failure_redis_error_records_partial_rate_limit() -> None:
    from fastapi import HTTPException

    from app.core.exceptions import AuthError
    from app.core.metrics import METRIC_PARTIAL_RATE_LIMIT
    from app.core.outage import _FLOW_ID_AUTH_LOGIN_RATE_RECORD
    from app.modules.auth import router as auth_router
    from app.modules.auth.schemas import LoginRequest

    flow = _FLOW_ID_AUTH_LOGIN_RATE_RECORD
    before = METRIC_PARTIAL_RATE_LIMIT.labels(flow=flow)._value.get()
    rate_limiter = MagicMock()
    rate_limiter.record_failure = AsyncMock(side_effect=RedisError("redis-down"))

    with (
        patch.object(auth_router.settings, "RATE_LIMIT_ENABLED", True),
        patch.object(
            auth_router.service,
            "login",
            AsyncMock(side_effect=AuthError(status_code=401, detail="invalid credentials")),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await auth_router.login(
                body=LoginRequest(email="mutation@test.com", password="Password123!"),
                request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={}),
                response=MagicMock(),
                db=MagicMock(),
                redis=MagicMock(),
                rate_limiter=rate_limiter,
            )

    assert exc_info.value.status_code == 401
    assert METRIC_PARTIAL_RATE_LIMIT.labels(flow=flow)._value.get() == before + 1


@pytest.mark.asyncio
async def test_lock_lease_loss_records_coordination_failure() -> None:
    from app.core.dist_lock import LockHandle
    from app.core.metrics import METRIC_COORDINATION_FAILURE
    from app.core.outage import _FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK

    flow = _FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK
    before = METRIC_COORDINATION_FAILURE.labels(flow=flow)._value.get()
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=0)
    handle = LockHandle(
        key="lock-key",
        owner_token="owner",
        acquired_at=0.0,
        ttl_seconds=30,
        flow_id=flow,
        _redis=redis,
    )

    assert await handle.renew() is False
    assert METRIC_COORDINATION_FAILURE.labels(flow=flow)._value.get() == before + 1


@pytest.mark.asyncio
async def test_revocation_cancellation_records_metric_and_reraises() -> None:
    from app.core.metrics import METRIC_CANCELLATION
    from app.core.security import revoke_access_token

    flow = "users_update_user_revoke"
    before = METRIC_CANCELLATION.labels(flow=flow)._value.get()
    redis = MagicMock()
    redis.set = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await revoke_access_token("cancelled-jti", 60, redis, flow_id=flow)

    assert METRIC_CANCELLATION.labels(flow=flow)._value.get() == before + 1


def test_outage_catalog_docstring_matches_29_flow_catalog() -> None:
    from app.core import outage

    assert outage.__doc__ is not None
    assert "29-FlowId" in outage.__doc__
    assert "25-FlowId" not in outage.__doc__
