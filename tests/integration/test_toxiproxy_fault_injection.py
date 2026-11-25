"""Focused Redis/Toxiproxy fault-injection matrix.

All toxics are applied after the proxy-backed application lifespan is healthy.
The matrix deliberately excludes startup failure, ``/metrics``, the catalog-only
ghost FlowId, scan locks, one-test-per-FlowId expansion, raw Redis translation,
``ServiceUnavailableError`` normalization, revocation/event behavior, and
Redis/Postgres atomicity.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config import settings
from app.core.redis import close_pool
from tests.conftest import (
    ANALYST_A_ID,
    TENANT_B_ID,
)
from tests.helpers.toxiproxy import ToxiproxyTransportController

pytestmark = [pytest.mark.integration, pytest.mark.toxiproxy]

REQUEST_TIMEOUT_SECONDS = 3.0
CLEANUP_TIMEOUT_SECONDS = 5.0
PROXY_PORT = 26379
DIRECT_REDIS_PORT = 6379
REDIS_TEST_DATABASE = 15


def _redis_client(port: int) -> Redis:
    """Build a Redis client for either the proxy or direct test route."""
    return Redis(
        host="localhost",
        port=port,
        db=REDIS_TEST_DATABASE,
        password=settings.REDIS_PASSWORD.get_secret_value() or None,
        decode_responses=True,
        socket_connect_timeout=REQUEST_TIMEOUT_SECONDS,
    )


async def _flush_direct_database() -> None:
    """Flush only the disposable Redis database used by this matrix."""
    client = _redis_client(DIRECT_REDIS_PORT)
    try:
        await asyncio.wait_for(client.flushdb(), timeout=CLEANUP_TIMEOUT_SECONDS)
    finally:
        await asyncio.wait_for(client.aclose(), timeout=CLEANUP_TIMEOUT_SECONDS)


async def _reset_proxy_state(
    toxiproxy_client: ToxiproxyTransportController,
) -> None:
    """Reset every mutable Redis test boundary and surface cleanup failures."""
    failures: list[tuple[str, BaseException]] = []

    cleanup_steps: tuple[tuple[str, Callable[[], Awaitable[object]]], ...] = (
        ("toxics", toxiproxy_client.reset_toxics),
        ("pool", close_pool),
        ("database", _flush_direct_database),
    )
    for name, cleanup in cleanup_steps:
        try:
            await asyncio.wait_for(cleanup(), timeout=CLEANUP_TIMEOUT_SECONDS)
        except BaseException as exc:
            failures.append((name, exc))

    if failures:
        name, error = failures[0]
        raise RuntimeError(f"Toxiproxy cleanup failed at {name}") from error


@asynccontextmanager
async def _connection_drop(
    toxiproxy_client: ToxiproxyTransportController,
) -> AsyncIterator[None]:
    """Apply a bounded post-startup connection drop and always reset it."""
    try:
        await asyncio.wait_for(
            toxiproxy_client.add_connection_drop(1.0),
            timeout=CLEANUP_TIMEOUT_SECONDS,
        )
        yield
    finally:
        await _reset_proxy_state(toxiproxy_client)


async def _login(client: AsyncClient) -> tuple[str, str]:
    """Perform a healthy login and return its access token and refresh cookie."""
    response = await asyncio.wait_for(
        client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@alpha.test",
                "password": "AdminAlpha123!",
            },
        ),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    refresh_token = client.cookies.get("refresh_token")
    assert isinstance(payload.get("access_token"), str)
    assert isinstance(refresh_token, str)
    return payload["access_token"], refresh_token


def _assert_lock_outage(response: Response) -> None:
    """Assert the existing sanitized RedisOutageError HTTP boundary."""
    assert response.status_code == 503
    assert response.json() == {"detail": "service temporarily unavailable"}
    assert response.headers["retry-after"] == str(
        settings.REDIS_OUTAGE_RETRY_AFTER_SECONDS
    )


@pytest.mark.asyncio
async def test_login_rate_outage_is_masked(
    seed_data,
    app_via_proxy: AsyncClient,
    toxiproxy_client: ToxiproxyTransportController,
):
    """A Redis outage during login-rate evaluation remains generic 401."""
    async with _connection_drop(toxiproxy_client):
        response = await asyncio.wait_for(
            app_via_proxy.post(
                "/api/v1/auth/login",
                json={
                    "email": "admin@alpha.test",
                    "password": "AdminAlpha123!",
                },
            ),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Credenciales incorrectas"}

    access_token, refresh_token = await _login(app_via_proxy)
    assert access_token
    assert refresh_token


@pytest.mark.asyncio
async def test_refresh_outage_fails_closed(
    seed_data,
    app_via_proxy: AsyncClient,
    toxiproxy_client: ToxiproxyTransportController,
):
    """Refresh fails closed through the sanitized global outage boundary."""
    await _login(app_via_proxy)

    async with _connection_drop(toxiproxy_client):
        response = await asyncio.wait_for(
            app_via_proxy.post("/api/v1/auth/refresh"),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    _assert_lock_outage(response)
    assert "access_token" not in response.json()
    assert "set-cookie" not in response.headers

    recovered = await asyncio.wait_for(
        app_via_proxy.post("/api/v1/auth/refresh"),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    assert recovered.status_code == 200, recovered.text
    assert isinstance(recovered.json().get("access_token"), str)


@pytest.mark.asyncio
async def test_current_user_token_outage_sanitized_503(
    seed_data,
    app_via_proxy: AsyncClient,
    toxiproxy_client: ToxiproxyTransportController,
):
    """Current-user token lookup outage surfaces the sanitized global 503 boundary."""
    access_token, _ = await _login(app_via_proxy)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with _connection_drop(toxiproxy_client):
        response = await asyncio.wait_for(
            app_via_proxy.get("/api/v1/users/me", headers=headers),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    _assert_lock_outage(response)

    recovered = await asyncio.wait_for(
        app_via_proxy.get("/api/v1/users/me", headers=headers),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["email"] == "admin@alpha.test"


@pytest.mark.parametrize(
    ("target_id", "current_user_key"),
    [(ANALYST_A_ID, "admin_a")],
    ids=["user-deactivation"],
)
@pytest.mark.asyncio
async def test_user_deactivation_lock_transport_503(
    target_id: str,
    current_user_key: str,
    seed_data,
    app_via_proxy: AsyncClient,
    toxiproxy_client: ToxiproxyTransportController,
    lock_test_overrides,
):
    """User deactivation lock transport failure stays a sanitized 503."""
    lock_test_overrides(app_via_proxy, seed_data[current_user_key])
    path = f"/api/v1/users/{target_id}"

    async with _connection_drop(toxiproxy_client):
        response = await asyncio.wait_for(
            app_via_proxy.delete(path),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    _assert_lock_outage(response)

    recovered = await asyncio.wait_for(
        app_via_proxy.delete(path),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    assert recovered.status_code == 204, recovered.text


@pytest.mark.parametrize(
    ("target_id", "current_user_key"),
    [(TENANT_B_ID, "superadmin")],
    ids=["tenant-deactivation"],
)
@pytest.mark.asyncio
async def test_tenant_deactivation_lock_transport_503(
    target_id: str,
    current_user_key: str,
    seed_data,
    app_via_proxy: AsyncClient,
    toxiproxy_client: ToxiproxyTransportController,
    lock_test_overrides,
):
    """Tenant deactivation lock transport failure stays a sanitized 503."""
    lock_test_overrides(app_via_proxy, seed_data[current_user_key])
    path = f"/api/v1/tenants/{target_id}"

    async with _connection_drop(toxiproxy_client):
        response = await asyncio.wait_for(
            app_via_proxy.delete(path),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    _assert_lock_outage(response)

    recovered = await asyncio.wait_for(
        app_via_proxy.delete(path),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    assert recovered.status_code == 204, recovered.text


@pytest.mark.asyncio
async def test_toxic_reset_recovers_pool_and_proxy_state(
    seed_data,
    app_via_proxy: AsyncClient,
    toxiproxy_client: ToxiproxyTransportController,
):
    """A failed faulted operation leaves clean proxy, pool, and DB-15 state."""
    direct_client = _redis_client(DIRECT_REDIS_PORT)
    try:
        assert await asyncio.wait_for(
            direct_client.set("toxiproxy:isolation-sentinel", "contaminated"),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    finally:
        await asyncio.wait_for(direct_client.aclose(), timeout=CLEANUP_TIMEOUT_SECONDS)

    async with _connection_drop(toxiproxy_client):
        proxy_client = _redis_client(PROXY_PORT)
        try:
            with pytest.raises((RedisConnectionError, RedisTimeoutError)):
                await asyncio.wait_for(
                    proxy_client.ping(), timeout=REQUEST_TIMEOUT_SECONDS
                )
        finally:
            await asyncio.wait_for(
                proxy_client.aclose(), timeout=CLEANUP_TIMEOUT_SECONDS
            )

    clean_client = _redis_client(DIRECT_REDIS_PORT)
    try:
        assert (
            await asyncio.wait_for(
                clean_client.get("toxiproxy:isolation-sentinel"),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            is None
        )
        assert (
            await asyncio.wait_for(clean_client.ping(), timeout=REQUEST_TIMEOUT_SECONDS)
            is True
        )
    finally:
        await asyncio.wait_for(clean_client.aclose(), timeout=CLEANUP_TIMEOUT_SECONDS)

    access_token, _ = await _login(app_via_proxy)
    assert access_token
