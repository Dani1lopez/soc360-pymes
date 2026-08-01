import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import SecretStr
from redis.exceptions import ResponseError

from app.core import metrics

COUNTERS = ((metrics.METRIC_LOCK_ACQUIRE_TOTAL, "soc360_redis_lock_acquire", ("flow", "outcome")), (metrics.METRIC_LOCK_RENEW_TOTAL, "soc360_redis_lock_renew", ("flow", "outcome")), (metrics.METRIC_LOCK_RELEASE_TOTAL, "soc360_redis_lock_release", ("flow", "outcome")), (metrics.METRIC_LOCK_CONTENTION_TOTAL, "soc360_redis_lock_contention", ("flow", "operation", "outcome")))  # fmt: skip
RATIFIED_OUTCOMES = {
    "acquired",
    "contended",
    "reentry",
    "lost",
    "cancelled",
    "noscript_recovered",
    "not_owner",
}


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


@pytest.mark.parametrize(("metric", "name", "labels"), COUNTERS)
def test_lock_counters_have_canonical_contract(metric, name, labels) -> None:
    assert metric._name == name
    assert metric._labelnames == labels


def test_lock_wait_histogram_has_canonical_contract() -> None:
    metric = metrics.METRIC_LOCK_WAIT_SECONDS
    assert metric._name == "soc360_redis_lock_wait_seconds"
    assert metric._labelnames == ("flow", "operation")
    assert tuple(metric._upper_bounds) == (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"))  # fmt: skip


@pytest.mark.asyncio
async def test_lock_lifecycle_emits_only_ratified_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import dist_lock

    monkeypatch.setattr(
        dist_lock,
        "settings",
        SimpleNamespace(LOCK_KEY_SECRET=SecretStr("metrics secret")),
    )
    observed: list[str] = []

    def record(_kind: str, _flow_id: str, outcome: str, _operation: str = "") -> None:
        observed.append(outcome)

    monkeypatch.setattr(dist_lock, "_record", record)
    redis = ScriptedFakeRedis()
    lock_args = dict(
        flow_id="scan_start_lock",
        tenant_id="tenant-1",
        asset_id="asset-1",
        ttl_seconds=30,
        operation="scan_start",
        wait_timeout_seconds=1.0,
        redis=redis,
    )

    try:
        async with dist_lock.acquire_dist_lock(**lock_args) as handle:
            assert await handle.renew() is True

        original_eval = redis.eval
        eval_calls = 0

        async def eval_with_noscript(script: str, numkeys: int, *args: Any) -> int:
            nonlocal eval_calls
            eval_calls += 1
            if eval_calls == 1:
                raise ResponseError("NOSCRIPT missing")
            return await original_eval(script, numkeys, *args)

        monkeypatch.setattr(redis, "eval", eval_with_noscript)
        monkeypatch.setattr(redis, "script_load", lambda _script: _loaded_script())
        context = dist_lock.acquire_dist_lock(**lock_args)
        handle = await context.__aenter__()
        assert await handle.release() is True
        await context.__aexit__(None, None, None)

        context = dist_lock.acquire_dist_lock(**lock_args)
        handle = await context.__aenter__()
        with pytest.raises(asyncio.CancelledError):
            await handle.__aexit__(
                asyncio.CancelledError,
                asyncio.CancelledError(),
                None,
            )
        await context.__aexit__(None, None, None)

        assert set(observed) <= RATIFIED_OUTCOMES
        assert {"acquired", "cancelled", "noscript_recovered"} <= set(observed)
    finally:
        await redis.aclose()


async def _loaded_script() -> bytes:
    return b"sha"
