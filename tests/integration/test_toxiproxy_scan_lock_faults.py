"""Real-Toxiproxy characterization of the four deferred scan lock FlowIds."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core import dist_lock, metrics
from app.core.config import settings
from app.core.dist_lock import acquire_dist_lock, build_lock_key
from app.core.exceptions import RedisOutageError, TemporaryUnavailableError
from app.core.redis import close_pool, get_redis_client
from tests.helpers.toxiproxy import ToxiproxyTransportController

pytestmark = [pytest.mark.integration, pytest.mark.toxiproxy]

SCAN_LOCKS = (
    ("scan_start_lock", "scan_start"),
    ("scan_update_lock", "scan_update"),
    ("scan_complete_lock", "scan_complete"),
    ("scan_cancel_lock", "scan_cancel"),
)
REQUEST_TIMEOUT_SECONDS = 3.0
CLEANUP_TIMEOUT_SECONDS = 5.0
PROXY_PORT = 26379
DIRECT_REDIS_PORT = 6379
REDIS_TEST_DATABASE = 15
LOCK_TENANT_ID = "pr7-tenant"
LOCK_ASSET_ID = "pr7-asset"


def _redis_client(port: int) -> Redis:
    """Build a bounded Redis client for the proxy or direct test route."""
    return Redis(
        host="localhost",
        port=port,
        db=REDIS_TEST_DATABASE,
        password=settings.REDIS_PASSWORD.get_secret_value() or None,
        decode_responses=True,
        socket_connect_timeout=REQUEST_TIMEOUT_SECONDS,
        socket_timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _metric_flows(flow_id: str) -> set[str]:
    """Return flow labels emitted by the distributed-lock metric families."""
    flows: set[str] = set()
    for metric in (
        metrics.METRIC_LOCK_ACQUIRE_TOTAL,
        metrics.METRIC_LOCK_RELEASE_TOTAL,
        metrics.METRIC_LOCK_CONTENTION_TOTAL,
        metrics.METRIC_LOCK_WAIT_SECONDS,
    ):
        for family in metric.collect():
            for sample in family.samples:
                if sample.labels.get("flow") == flow_id:
                    flows.add(flow_id)
    return flows


async def _run_lock_attempt(
    flow_id: str,
    operation: str,
    *,
    waiter: Any = None,
    wait_timeout_seconds: float = 0.5,
) -> str:
    """Run one direct lock operation through the proxy with a hard bound."""
    redis = await get_redis_client()
    try:

        async def _attempt() -> str:
            async with acquire_dist_lock(
                flow_id=flow_id,
                tenant_id=LOCK_TENANT_ID,
                asset_id=LOCK_ASSET_ID,
                ttl_seconds=30,
                operation=operation,
                wait_timeout_seconds=wait_timeout_seconds,
                redis=redis,
                waiter=waiter,
            ) as handle:
                key = handle.key
                assert await redis.get(key) == handle.owner_token
                return key

        return await asyncio.wait_for(_attempt(), timeout=REQUEST_TIMEOUT_SECONDS)
    finally:
        await asyncio.wait_for(redis.aclose(), timeout=CLEANUP_TIMEOUT_SECONDS)


async def _acquire_scan_lock(flow_id: str, operation: str) -> tuple[str, set[str]]:
    """Acquire, release, and inspect one scan lock's safe evidence."""
    key = await _run_lock_attempt(flow_id, operation)
    probe = await get_redis_client()
    try:
        assert await probe.get(key) is None
    finally:
        await asyncio.wait_for(probe.aclose(), timeout=CLEANUP_TIMEOUT_SECONDS)
    return key, _metric_flows(flow_id)


async def _seed_held_key(flow_id: str) -> tuple[Redis, str]:
    """Create a real proxy-backed owner key for contention scenarios."""
    owner = await get_redis_client()
    key = build_lock_key(flow_id, LOCK_TENANT_ID, LOCK_ASSET_ID)
    await asyncio.wait_for(
        owner.set(key, "held-by-owner", nx=True, px=30_000),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return owner, key


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
    """Reset toxics, the application pool, and disposable Redis state."""
    failures: list[tuple[str, BaseException]] = []
    cleanup_steps = (
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
    """Apply a post-startup connection drop and always perform bounded cleanup."""
    try:
        await asyncio.wait_for(
            toxiproxy_client.add_connection_drop(1.0),
            timeout=CLEANUP_TIMEOUT_SECONDS,
        )
        yield
    finally:
        await _reset_proxy_state(toxiproxy_client)


@asynccontextmanager
async def _cleanup_after_failure(
    toxiproxy_client: ToxiproxyTransportController,
) -> AsyncIterator[None]:
    """Provide the same fail-closed cleanup without pre-injecting a toxic."""
    try:
        yield
    finally:
        await _reset_proxy_state(toxiproxy_client)


class TimeoutRecordingWaiter:
    """Deterministic waiter that makes production cancel the retry task."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, float]] = []

    async def wait(self, awaitable: Any, *, timeout: float) -> Any:
        self.calls.append((awaitable, timeout))
        raise asyncio.TimeoutError()


class RetryDropWaiter:
    """Inject a toxic after contention starts and before retry Redis I/O."""

    def __init__(self, toxiproxy_client: ToxiproxyTransportController) -> None:
        self._toxiproxy_client = toxiproxy_client
        self.calls: list[tuple[Any, float]] = []

    async def wait(self, awaitable: Any, *, timeout: float) -> Any:
        self.calls.append((awaitable, timeout))
        await asyncio.wait_for(
            self._toxiproxy_client.add_connection_drop(1.0),
            timeout=CLEANUP_TIMEOUT_SECONDS,
        )
        return await asyncio.wait_for(awaitable, timeout=timeout)


@pytest.mark.parametrize(("flow_id", "operation"), SCAN_LOCKS)
@pytest.mark.asyncio
async def test_scan_lock_healthy_acquires_and_releases(
    flow_id: str,
    operation: str,
    app_via_proxy,
    toxiproxy_client,
) -> None:
    """Each scan FlowId MUST acquire and release through the healthy proxy."""
    key, metric_flows = await _acquire_scan_lock(flow_id, operation)

    assert key.split(":", 2)[1] == flow_id
    assert flow_id in metric_flows


@pytest.mark.parametrize(("flow_id", "operation"), SCAN_LOCKS)
@pytest.mark.asyncio
async def test_scan_lock_initial_drop_is_typed_outage(
    flow_id: str,
    operation: str,
    app_via_proxy,
    toxiproxy_client: ToxiproxyTransportController,
) -> None:
    """A post-startup initial drop MUST remain a typed Redis outage."""
    async with _connection_drop(toxiproxy_client):
        with pytest.raises(RedisOutageError) as exc_info:
            await _run_lock_attempt(flow_id, operation)

    assert not isinstance(exc_info.value, TemporaryUnavailableError)
    await _acquire_scan_lock(flow_id, operation)


@pytest.mark.parametrize(("flow_id", "operation"), SCAN_LOCKS)
@pytest.mark.asyncio
async def test_scan_lock_contention_cancels_one_retry(
    flow_id: str,
    operation: str,
    app_via_proxy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Held-key contention MUST cancel one retry and leave no waiter lease."""
    monkeypatch.setattr(dist_lock.random, "uniform", lambda _low, _high: 0.25)
    owner, key = await _seed_held_key(flow_id)
    waiter = TimeoutRecordingWaiter()
    try:
        with pytest.raises(TemporaryUnavailableError, match="lock_timeout"):
            await _run_lock_attempt(
                flow_id,
                operation,
                waiter=waiter,
                wait_timeout_seconds=0.25,
            )

        assert len(waiter.calls) == 1
        assert waiter.calls[0][0].done()
        assert waiter.calls[0][0].cancelled()
        assert await owner.get(key) == "held-by-owner"
    finally:
        await asyncio.wait_for(owner.delete(key), timeout=CLEANUP_TIMEOUT_SECONDS)
        await asyncio.wait_for(owner.aclose(), timeout=CLEANUP_TIMEOUT_SECONDS)

    await _acquire_scan_lock(flow_id, operation)


@pytest.mark.parametrize(("flow_id", "operation"), SCAN_LOCKS)
@pytest.mark.asyncio
async def test_scan_lock_retry_drop_preserves_outage_precedence(
    flow_id: str,
    operation: str,
    app_via_proxy,
    toxiproxy_client: ToxiproxyTransportController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry-phase drop MUST beat the lock timeout outcome."""
    monkeypatch.setattr(dist_lock.random, "uniform", lambda _low, _high: 0.25)
    owner, key = await _seed_held_key(flow_id)
    waiter = RetryDropWaiter(toxiproxy_client)
    try:
        async with _cleanup_after_failure(toxiproxy_client):
            with pytest.raises(RedisOutageError) as exc_info:
                await _run_lock_attempt(
                    flow_id,
                    operation,
                    waiter=waiter,
                    wait_timeout_seconds=0.5,
                )

        assert not isinstance(exc_info.value, TemporaryUnavailableError)
        assert len(waiter.calls) == 1
    finally:
        await asyncio.wait_for(owner.aclose(), timeout=CLEANUP_TIMEOUT_SECONDS)

    await _acquire_scan_lock(flow_id, operation)


@pytest.mark.asyncio
async def test_failed_scan_lock_scenario_resets_proxy_pool_and_database(
    app_via_proxy,
    toxiproxy_client: ToxiproxyTransportController,
) -> None:
    """Failed toxic scenarios MUST leave every shared boundary recoverable."""
    direct_client = _redis_client(DIRECT_REDIS_PORT)
    try:
        await asyncio.wait_for(
            direct_client.set("pr7:isolation-sentinel", "contaminated"),
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

    assert await toxiproxy_client.list_toxics() == []
    from app.core import redis as redis_module

    assert redis_module._pool is None
    clean_client = _redis_client(DIRECT_REDIS_PORT)
    try:
        assert (
            await asyncio.wait_for(
                clean_client.get("pr7:isolation-sentinel"),
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

    await _acquire_scan_lock("scan_cancel_lock", "scan_cancel")
