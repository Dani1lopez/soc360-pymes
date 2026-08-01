"""HTTP-level regression coverage for an existing auth lock flow."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core import metrics
from app.core.config import settings
from app.core.dist_lock import build_lock_key
from app.core.exceptions import TemporaryUnavailableError
from app.core.outage import _FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK
from app.core.redis import get_redis
from app.dependencies import (
    get_current_user,
    get_db_with_tenant,
    get_user_for_admin_delete,
)
from app.main import create_app


def _histogram_sample(
    metric, sample_suffix: str, *, flow: str, operation: str
) -> float:
    sample_name = f"{metric._name}_{sample_suffix}"
    for family in metric.collect():
        for sample in family.samples:
            if sample.name == sample_name and sample.labels == {
                "flow": flow,
                "operation": operation,
            }:
                return sample.value
    return 0.0


@pytest.mark.asyncio
async def test_auth_lock_contention_returns_503_and_emits_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guarded auth route must expose contention and wait telemetry over HTTP."""
    app = create_app()
    redis = FakeRedis()
    tenant_id = uuid4()
    target_id = uuid4()
    current_user = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        is_superadmin=True,
        role="superadmin",
    )
    target = SimpleNamespace(
        id=target_id,
        tenant_id=tenant_id,
        is_superadmin=False,
        role="viewer",
        is_active=True,
    )
    flow = _FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK
    operation = "deactivate"

    async def override_current_user() -> SimpleNamespace:
        return current_user

    async def override_target() -> SimpleNamespace:
        return target

    async def override_db():
        yield object()

    async def override_redis():
        yield redis

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_user_for_admin_delete] = override_target
    app.dependency_overrides[get_db_with_tenant] = override_db
    app.dependency_overrides[get_redis] = override_redis

    async def temporary_unavailable_handler(request, exc):
        return JSONResponse(
            status_code=503,
            content={"detail": "service temporarily unavailable"},
        )

    # PR5b owns the lock flow; keep the coordination response local until the
    # dedicated HTTP handler change lands.
    app.add_exception_handler(TemporaryUnavailableError, temporary_unavailable_handler)

    monkeypatch.setattr(settings, "LOCK_KEY_SECRET", SecretStr("http test secret"))
    monkeypatch.setattr("app.core.dist_lock.random.uniform", lambda _low, _high: 0.01)

    lock_key = build_lock_key(
        flow,
        str(tenant_id),
        f"user:{target_id}",
    )
    await redis.set(lock_key, "another-owner", nx=True, px=30_000)

    contention = metrics.METRIC_LOCK_CONTENTION_TOTAL.labels(
        flow=flow,
        operation=operation,
        outcome="contended",
    )
    contention_before = contention._value.get()
    wait_count_before = _histogram_sample(
        metrics.METRIC_LOCK_WAIT_SECONDS,
        "count",
        flow=flow,
        operation=operation,
    )
    wait_sum_before = _histogram_sample(
        metrics.METRIC_LOCK_WAIT_SECONDS,
        "sum",
        flow=flow,
        operation=operation,
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.delete(f"/api/v1/users/{target_id}")
    finally:
        await redis.delete(lock_key)
        await redis.aclose()

    assert response.status_code == 503
    assert contention._value.get() > contention_before
    assert (
        _histogram_sample(
            metrics.METRIC_LOCK_WAIT_SECONDS,
            "count",
            flow=flow,
            operation=operation,
        )
        > wait_count_before
    )
    assert (
        _histogram_sample(
            metrics.METRIC_LOCK_WAIT_SECONDS,
            "sum",
            flow=flow,
            operation=operation,
        )
        > wait_sum_before
    )
