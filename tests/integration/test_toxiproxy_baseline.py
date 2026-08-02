"""PR1 Toxiproxy baseline — proxy-disabled connection refusal smoke test.

This is the mandatory CI gate that every PR (PR1–PR9) must run.
Named transport scenario: proxy-disabled connection refusal.
"""

from __future__ import annotations

import os

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from tests.helpers.toxiproxy import ToxiproxyTransportController

pytestmark = [pytest.mark.integration, pytest.mark.toxiproxy]

PROXY_NAME = "redis"


@pytest.mark.asyncio
async def test_pr1_redis_connection_refused_smoke(
    toxiproxy_session: ToxiproxyTransportController,
):
    """When the Toxiproxy proxy is disabled, Redis connections must be refused.

    This proves the baseline fault-injection harness works: disabling the
    proxy causes a connection error, re-enabling it restores connectivity.
    """
    # 1. Verify Redis is reachable through the proxy
    client = Redis(
        host="localhost",
        port=26379,
        db=int(os.environ.get("REDIS_DB", "0")),
        password=os.environ.get("REDIS_PASSWORD") or None,
        decode_responses=True,
    )
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()

    # 2. Disable the proxy — simulates Redis being unreachable
    try:
        await toxiproxy_session.disable_proxy(PROXY_NAME)

        # 3. Connection must be refused
        client2 = Redis(
            host="localhost",
            port=26379,
            db=int(os.environ.get("REDIS_DB", "0")),
            password=os.environ.get("REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        try:
            with pytest.raises((RedisConnectionError, RedisTimeoutError)):
                await client2.ping()
        finally:
            await client2.aclose()
    finally:
        # 4. Re-enable the proxy — connectivity must be restored
        await toxiproxy_session.enable_proxy(PROXY_NAME)

    client3 = Redis(
        host="localhost",
        port=26379,
        db=int(os.environ.get("REDIS_DB", "0")),
        password=os.environ.get("REDIS_PASSWORD") or None,
        decode_responses=True,
    )
    try:
        assert await client3.ping() is True
    finally:
        await client3.aclose()


@pytest.mark.asyncio
async def test_toxiproxy_setup_errors_fail_closed(monkeypatch):
    """Unexpected mandatory baseline setup errors must fail the session."""
    import tests.conftest as project_conftest

    async def fail_setup(*args, **kwargs):
        raise RuntimeError("admin unavailable")

    monkeypatch.setattr(ToxiproxyTransportController, "ensure_proxy", fail_setup)

    with pytest.raises(RuntimeError, match="admin unavailable"):
        await project_conftest.toxiproxy_session.__wrapped__().__anext__()


@pytest.mark.asyncio
async def test_toxiproxy_teardown_errors_fail_closed(monkeypatch):
    """Unexpected mandatory baseline teardown errors must fail the session."""
    import tests.conftest as project_conftest

    async def ensure_setup(*args, **kwargs):
        return None

    async def fail_teardown(*args, **kwargs):
        raise RuntimeError("proxy cleanup unavailable")

    monkeypatch.setattr(ToxiproxyTransportController, "ensure_proxy", ensure_setup)
    monkeypatch.setattr(ToxiproxyTransportController, "enable_proxy", fail_teardown)

    session = project_conftest.toxiproxy_session.__wrapped__()
    await session.__anext__()
    with pytest.raises(RuntimeError, match="proxy cleanup unavailable"):
        await session.__anext__()
