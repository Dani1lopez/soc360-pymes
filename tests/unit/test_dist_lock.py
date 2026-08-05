"""Unit tests for the Redis distributed-lock primitive."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from pydantic import SecretStr
from redis.exceptions import ResponseError


class RecordingWaiter:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def wait(self, awaitable: Any, *, timeout: float) -> Any:
        self.calls.append(timeout)
        return await awaitable


class AwaitingWaiter(RecordingWaiter):
    """RedisLockWaiter-compatible waiter that records retry deadlines."""


class TimeoutRecordingWaiter:
    """Deterministic waiter that forces production retry cancellation."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, float]] = []

    async def wait(self, awaitable: Any, *, timeout: float) -> Any:
        self.calls.append((awaitable, timeout))
        raise asyncio.TimeoutError()


class ScriptedFakeRedis(FakeRedis):
    """fakeredis fixture with Lua semantics without the optional lupa package."""

    async def eval(self, script: str, numkeys: int, *args: Any) -> int:
        key, token, argument = args
        current = await self.get(key)
        if isinstance(current, bytes):
            current = current.decode()
        if current != token:
            return 0
        if "PEXPIRE" in script:
            return int(await self.pexpire(key, int(argument)))
        return int(await self.delete(key))


@pytest_asyncio.fixture
async def redis() -> ScriptedFakeRedis:
    client = ScriptedFakeRedis()
    yield client
    await client.aclose()


def _set_secret(monkeypatch: pytest.MonkeyPatch, secret: str) -> Any:
    from app.core import dist_lock

    monkeypatch.setattr(
        dist_lock, "settings", SimpleNamespace(LOCK_KEY_SECRET=SecretStr(secret))
    )
    return dist_lock


def _lock_args(redis: ScriptedFakeRedis, **overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = dict(
        flow_id="scan",
        tenant_id="tenant-1",
        asset_id="asset-1",
        ttl_seconds=30,
        operation="scan_start",
        wait_timeout_seconds=1.0,
        redis=redis,
    )
    args.update(overrides)
    return args


def test_build_lock_key_hmac_format_and_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist_lock = _set_secret(monkeypatch, "first lock secret")
    key = dist_lock.build_lock_key("scan", "t1", "a1")
    expected = hmac.new(b"first lock secret", b"t1", hashlib.sha256).digest()[:8].hex()
    assert key == f"lock:scan:{expected}:t1:a1"
    assert re.fullmatch(r"[0-9a-f]{16}", key.split(":")[2])

    _set_secret(monkeypatch, "rotated lock secret")
    rotated = dist_lock.build_lock_key("scan", "t1", "a1")
    assert rotated.split(":")[2] != key.split(":")[2]


@pytest.mark.parametrize(
    "flow_id",
    [
        "scan_start_lock",
        "scan_update_lock",
        "scan_complete_lock",
        "scan_cancel_lock",
    ],
)
def test_build_lock_key_preserves_full_flow_id(
    monkeypatch: pytest.MonkeyPatch,
    flow_id: str,
) -> None:
    dist_lock = _set_secret(monkeypatch, "flow identity secret")

    key = dist_lock.build_lock_key(flow_id, "tenant-1", "asset-1")

    assert key.split(":")[1] == flow_id


def test_build_lock_key_keeps_scan_flows_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist_lock = _set_secret(monkeypatch, "flow isolation secret")
    flow_ids = (
        "scan_start_lock",
        "scan_update_lock",
        "scan_complete_lock",
        "scan_cancel_lock",
    )

    keys = {
        dist_lock.build_lock_key(flow_id, "tenant-1", "asset-1") for flow_id in flow_ids
    }

    assert len(keys) == len(flow_ids)


@pytest.mark.parametrize(
    "resource", ["__SUPERADMIN_SESSION__", "__TENANT_DEACTIVATION__"]
)
def test_build_lock_key_preserves_reserved_sentinels(
    monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    dist_lock = _set_secret(monkeypatch, "sentinel secret")
    key = dist_lock.build_lock_key("auth", "tenant-1", resource)
    assert key.rsplit(":", 1)[-1] == resource
    assert ":" not in resource and not any(c.isspace() for c in resource)


def test_build_lock_key_hashes_unsafe_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist_lock = _set_secret(monkeypatch, "component secret")
    key = dist_lock.build_lock_key("scan", "tenant:42", "asset-1")
    assert key.split(":")[3] == hashlib.sha256(b"tenant:42").hexdigest()


@pytest.mark.asyncio
async def test_acquire_returns_random_handle_and_releases(
    monkeypatch: pytest.MonkeyPatch, redis: ScriptedFakeRedis
) -> None:
    dist_lock = _set_secret(monkeypatch, "acquire secret")
    async with dist_lock.acquire_dist_lock(**_lock_args(redis)) as handle:
        assert handle.key == dist_lock.build_lock_key("scan", "tenant-1", "asset-1")
        assert re.fullmatch(r"[0-9a-f]{32}", handle.owner_token)
        assert await redis.get(handle.key) in {
            handle.owner_token,
            handle.owner_token.encode(),
        }
    assert await redis.get(handle.key) is None


@pytest.mark.asyncio
async def test_acquire_rejects_ttl_before_redis_call() -> None:
    from app.core import dist_lock

    class NoCallRedis:
        async def set(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("Redis must not be called")

    with pytest.raises(ValueError, match="ttl_seconds must be >= LOCK_MIN_TTL_SECONDS"):
        async with dist_lock.acquire_dist_lock(
            **_lock_args(NoCallRedis(), ttl_seconds=0)
        ):
            pass


@pytest.mark.asyncio
async def test_contention_and_reentry_have_distinct_details(
    monkeypatch: pytest.MonkeyPatch, redis: ScriptedFakeRedis
) -> None:
    from app.core.exceptions import TemporaryUnavailableError

    dist_lock = _set_secret(monkeypatch, "contention secret")
    monkeypatch.setattr(dist_lock.random, "uniform", lambda _low, _high: 0.1)
    key = dist_lock.build_lock_key("scan", "tenant-1", "asset-1")
    await redis.set(key, "another-owner", nx=True, px=30_000)
    with pytest.raises(TemporaryUnavailableError, match="lock_timeout"):
        async with dist_lock.acquire_dist_lock(
            **_lock_args(redis, waiter=RecordingWaiter())
        ):
            pass

    await redis.delete(key)
    first = dist_lock.acquire_dist_lock(**_lock_args(redis))
    await first.__aenter__()
    try:
        with pytest.raises(TemporaryUnavailableError, match="lock_reentry"):
            async with dist_lock.acquire_dist_lock(**_lock_args(redis)):
                pass
    finally:
        await first.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flow_id", "operation"),
    [("scan_start_lock", "scan_start"), ("scan_cancel_lock", "scan_cancel")],
)
async def test_contention_timeout_cancels_single_retry(
    monkeypatch: pytest.MonkeyPatch,
    redis: ScriptedFakeRedis,
    flow_id: str,
    operation: str,
) -> None:
    from app.core.exceptions import TemporaryUnavailableError

    dist_lock = _set_secret(monkeypatch, "deterministic timeout secret")
    monkeypatch.setattr(dist_lock.random, "uniform", lambda _low, _high: 0.25)
    key = dist_lock.build_lock_key(flow_id, "tenant-1", "asset-1")
    await redis.set(key, "held-by-owner", nx=True, px=30_000)
    waiter = TimeoutRecordingWaiter()

    with pytest.raises(TemporaryUnavailableError, match="lock_timeout"):
        async with dist_lock.acquire_dist_lock(
            **_lock_args(
                redis,
                flow_id=flow_id,
                operation=operation,
                waiter=waiter,
                wait_timeout_seconds=0.25,
            )
        ):
            pass

    assert len(waiter.calls) == 1
    assert waiter.calls[0][0].done()
    assert waiter.calls[0][0].cancelled()
    assert await redis.get(key) == b"held-by-owner"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_error",
    [
        ConnectionError("retry transport failed"),
        asyncio.TimeoutError("retry timed out"),
    ],
    ids=["connection", "timeout"],
)
async def test_retry_outage_precedence(
    monkeypatch: pytest.MonkeyPatch,
    redis: ScriptedFakeRedis,
    transport_error: BaseException,
) -> None:
    from app.core.exceptions import RedisOutageError, TemporaryUnavailableError

    dist_lock = _set_secret(monkeypatch, "retry outage secret")
    monkeypatch.setattr(dist_lock.random, "uniform", lambda _low, _high: 0.0)
    key = dist_lock.build_lock_key("scan_update_lock", "tenant-1", "asset-1")
    await redis.set(key, "held-by-owner", nx=True, px=30_000)
    original_set = redis.set
    set_calls = 0

    async def scripted_set(*args: Any, **kwargs: Any) -> Any:
        nonlocal set_calls
        set_calls += 1
        if set_calls == 2:
            raise transport_error
        return await original_set(*args, **kwargs)

    monkeypatch.setattr(redis, "set", scripted_set)

    with pytest.raises(RedisOutageError) as exc_info:
        async with dist_lock.acquire_dist_lock(
            **_lock_args(
                redis,
                flow_id="scan_update_lock",
                operation="scan_update",
                waiter=AwaitingWaiter(),
                wait_timeout_seconds=0.25,
            )
        ):
            pass

    assert isinstance(exc_info.value, RedisOutageError)
    assert not isinstance(exc_info.value, TemporaryUnavailableError)
    assert set_calls == 2


@pytest.mark.asyncio
async def test_acquire_propagates_redis_outage(
    monkeypatch: pytest.MonkeyPatch, redis: ScriptedFakeRedis
) -> None:
    from app.core.exceptions import RedisOutageError, TemporaryUnavailableError

    dist_lock = _set_secret(monkeypatch, "outage secret")

    async def fail_set(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(redis, "set", fail_set)
    with pytest.raises(RedisOutageError) as exc_info:
        async with dist_lock.acquire_dist_lock(**_lock_args(redis)):
            pass
    assert not isinstance(exc_info.value, TemporaryUnavailableError)


@pytest.mark.asyncio
async def test_injected_waiter_controls_exactly_one_retry(
    monkeypatch: pytest.MonkeyPatch, redis: ScriptedFakeRedis
) -> None:
    dist_lock = _set_secret(monkeypatch, "waiter secret")
    monkeypatch.setattr(dist_lock.random, "uniform", lambda _low, _high: 0.25)
    await redis.set(
        dist_lock.build_lock_key("scan", "tenant-1", "asset-1"), "owner", px=30_000
    )
    waiter = RecordingWaiter()
    with pytest.raises(Exception, match="lock_timeout"):
        async with dist_lock.acquire_dist_lock(
            **_lock_args(redis, waiter=waiter, wait_timeout_seconds=2.5)
        ):
            pass
    assert waiter.calls == [2.5]


@pytest.mark.asyncio
async def test_renew_and_release_are_owner_verified(
    monkeypatch: pytest.MonkeyPatch, redis: ScriptedFakeRedis
) -> None:
    dist_lock = _set_secret(monkeypatch, "owner secret")
    async with dist_lock.acquire_dist_lock(**_lock_args(redis)) as handle:
        assert await handle.renew(ttl_seconds=60) is True
        assert handle.ttl_seconds == 60
        await redis.set(handle.key, "different-owner", px=30_000)
        assert await handle.renew() is False
        assert handle.is_lost is True
        assert await redis.get(handle.key) in {b"different-owner", "different-owner"}
        await redis.delete(handle.key)

    # A separately acquired handle proves the release branch.
    async with dist_lock.acquire_dist_lock(**_lock_args(redis)) as handle:
        assert await handle.release() is True
        assert await redis.get(handle.key) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_twice", [False, True])
async def test_release_noscript_reloads_once(
    monkeypatch: pytest.MonkeyPatch,
    redis: ScriptedFakeRedis,
    fail_twice: bool,
) -> None:
    from app.core.exceptions import RedisResponseError

    dist_lock = _set_secret(monkeypatch, "noscript secret")
    original_eval = redis.eval
    eval_calls = 0
    loads = 0

    async def eval_with_noscript(script: str, numkeys: int, *args: Any) -> int:
        nonlocal eval_calls
        eval_calls += 1
        if eval_calls == 1 or fail_twice:
            raise ResponseError("NOSCRIPT missing")
        return await original_eval(script, numkeys, *args)

    async def load(_script: str) -> bytes:
        nonlocal loads
        loads += 1
        return b"sha"

    monkeypatch.setattr(redis, "eval", eval_with_noscript)
    monkeypatch.setattr(redis, "script_load", load)
    context = dist_lock.acquire_dist_lock(**_lock_args(redis))
    handle = await context.__aenter__()
    if fail_twice:
        with pytest.raises(RedisResponseError):
            await handle.release()
        handle._released = True
    else:
        assert await handle.release() is True
    assert eval_calls == 2 and loads == 1
    await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_context_exit_releases_on_cancel_and_exception(
    monkeypatch: pytest.MonkeyPatch, redis: ScriptedFakeRedis
) -> None:
    dist_lock = _set_secret(monkeypatch, "exit secret")
    context = dist_lock.acquire_dist_lock(**_lock_args(redis))
    handle = await context.__aenter__()
    with pytest.raises(asyncio.CancelledError):
        await handle.__aexit__(asyncio.CancelledError, asyncio.CancelledError(), None)
    assert await redis.get(handle.key) is None

    with pytest.raises(RuntimeError, match="work failed"):
        async with dist_lock.acquire_dist_lock(**_lock_args(redis)) as handle:
            raise RuntimeError("work failed")
    assert await redis.get(handle.key) is None
