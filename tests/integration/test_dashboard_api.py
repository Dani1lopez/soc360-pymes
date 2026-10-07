"""Public dashboard contract: authorization, tenant isolation and best-effort cache."""

import json
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from app.core.redis import get_redis
from app.modules.assets.models import Asset
from app.modules.dashboard.schemas import DashboardSummary
from tests.conftest import TENANT_A_ID, TENANT_B_ID

URL = "/api/v1/dashboard/summary"
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def dashboard_redis(client: AsyncClient):
    """Resolve the exact FakeRedis already used by the client's dependency override."""
    app = client._transport.app  # ASGITransport; client does not expose app directly.
    dependency = app.dependency_overrides[get_redis]()
    try:
        yield await dependency.__anext__()
    finally:
        await dependency.aclose()


async def _add_asset(db: AsyncSession, tenant_id: str) -> None:
    # client overrides both DB dependencies with this savepoint-backed session.
    # Commit follows the API seeding convention without escaping outer rollback.
    await set_tenant_context(db, None, is_superadmin=True)
    db.add(
        Asset(
            tenant_id=UUID(tenant_id),
            asset_type="hostname",
            value=f"{uuid4()}.test",
            status="active",
        )
    )
    await db.flush()
    await db.commit()


def _summary(response, tenant_id: str) -> dict:
    assert response.status_code == 200, response.text
    body = response.json()
    DashboardSummary.model_validate(body)
    assert body["tenant_id"] == tenant_id
    return body


@pytest.mark.parametrize("role", ["admin", "analyst", "viewer"])
@pytest.mark.parametrize("tenant_id", [None, TENANT_A_ID, TENANT_B_ID])
async def test_tenant_roles(
    client,
    role,
    tenant_id,
    seed_data,
    admin_a_headers,
    analyst_a_headers,
    viewer_a_headers,
):
    headers = {
        "admin": admin_a_headers,
        "analyst": analyst_a_headers,
        "viewer": viewer_a_headers,
    }[role]
    response = await client.get(
        URL,
        headers=headers,
        params={} if tenant_id is None else {"tenant_id": tenant_id},
    )
    if tenant_id == TENANT_B_ID:
        assert response.status_code == 403
    else:
        _summary(response, TENANT_A_ID)


@pytest.mark.parametrize("authenticated", [False, True])
async def test_denied_roles(client, ingestor_a_headers, authenticated):
    response = await client.get(
        URL, headers=ingestor_a_headers if authenticated else {}
    )
    assert response.status_code == (403 if authenticated else 401)


@pytest.mark.parametrize(
    "tenant_id, status",
    [
        (None, 422),
        (
            "99999999-9999-4999-8999-999999999999",
            404,
        ),  # stable id: xdist needs identical collection
        ("not-a-uuid", 422),
        (TENANT_A_ID, 200),
        (TENANT_B_ID, 200),
    ],
)
async def test_superadmin_tenant_selection(
    client, superadmin_headers, tenant_id, status
):
    response = await client.get(
        URL,
        headers=superadmin_headers,
        params={} if tenant_id is None else {"tenant_id": tenant_id},
    )
    assert response.status_code == status, response.text
    if status == 200:
        _summary(response, tenant_id)


async def test_cache_value_ttl_and_hit(
    client, admin_a_headers, db_session, dashboard_redis
):
    first = _summary(await client.get(URL, headers=admin_a_headers), TENANT_A_ID)
    key = f"dashboard:summary:{TENANT_A_ID}"
    cached = await dashboard_redis.get(key)
    assert cached is not None
    assert json.loads(cached) == first
    assert 0 < await dashboard_redis.ttl(key) <= 60
    await _add_asset(db_session, TENANT_A_ID)
    second = _summary(await client.get(URL, headers=admin_a_headers), TENANT_A_ID)
    assert second == first  # DB now has one more active asset; cache must win.
    # Expire only this entry and prove the insertion really changed the DB result.
    await dashboard_redis.delete(key)
    fresh = _summary(await client.get(URL, headers=admin_a_headers), TENANT_A_ID)
    assert fresh["assets_monitored"] == first["assets_monitored"] + 1


async def test_cache_is_tenant_scoped(
    client, superadmin_headers, admin_b_headers, db_session, dashboard_redis
):
    await _add_asset(db_session, TENANT_A_ID)
    await _add_asset(db_session, TENANT_A_ID)
    await _add_asset(db_session, TENANT_B_ID)
    a = _summary(
        await client.get(
            URL, headers=superadmin_headers, params={"tenant_id": TENANT_A_ID}
        ),
        TENANT_A_ID,
    )
    b = _summary(
        await client.get(
            URL, headers=superadmin_headers, params={"tenant_id": TENANT_B_ID}
        ),
        TENANT_B_ID,
    )
    assert a["assets_monitored"] == 2
    assert b["assets_monitored"] == 1
    for tenant_id, body in [(TENANT_A_ID, a), (TENANT_B_ID, b)]:
        assert (
            json.loads(await dashboard_redis.get(f"dashboard:summary:{tenant_id}"))
            == body
        )
    assert _summary(await client.get(URL, headers=admin_b_headers), TENANT_B_ID) == b


@pytest.mark.parametrize("operation", ["get", "set"])
async def test_redis_failure_is_best_effort(
    client, admin_a_headers, db_session, dashboard_redis, monkeypatch, operation
):
    await _add_asset(db_session, TENANT_A_ID)
    failing = AsyncMock(side_effect=RedisError("cache unavailable"))
    # Login/header fixture has completed before patching: auth Redis is unaffected.
    monkeypatch.setattr(dashboard_redis, operation, failing)
    body = _summary(await client.get(URL, headers=admin_a_headers), TENANT_A_ID)
    assert body["assets_monitored"] == 1
    failing.assert_awaited()


async def test_unreadable_cache_entry_is_a_miss(
    client, admin_a_headers, db_session, dashboard_redis
):
    # A payload cached before a schema change must not turn into a 500.
    await _add_asset(db_session, TENANT_A_ID)
    await dashboard_redis.set(
        f"dashboard:summary:{TENANT_A_ID}", '{"stale": true}', ex=60
    )
    body = _summary(await client.get(URL, headers=admin_a_headers), TENANT_A_ID)
    assert body["assets_monitored"] == 1
