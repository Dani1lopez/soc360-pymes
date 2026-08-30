"""Real Redis pressure regression; run only with the disposable pressure service."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import cast

import httpx
import pytest
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core.exceptions import RedisResponseError
from app.core.metrics import METRIC_OUTAGES
from app.core.security import is_token_revoked, revoke_access_token
from app.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.redis_pressure]


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.fail(f"redis pressure prerequisite missing: {name}")
    return cast(str, value)


def _counter(info: dict, key: str) -> int:
    value = info.get(key, 0)
    if isinstance(value, dict):
        value = value.get("count", 0)
    return int(value or 0)


@pytest.mark.asyncio
async def test_real_redis_noeviction_preserves_security_state_and_dlq() -> None:
    host = os.getenv("REDIS_PRESSURE_HOST", "127.0.0.1")
    port = int(_required("REDIS_PRESSURE_PORT"))
    password = _required("REDIS_PRESSURE_PASSWORD")
    run = uuid.uuid4().hex
    prefix = f"sdd291:{run}:"
    filler_prefix = f"{prefix}filler:"
    redis = Redis(host=host, port=port, password=password, decode_responses=True)
    filler_keys: list[str] = []

    try:
        try:
            await redis.ping()
        except Exception as exc:  # pragma: no cover - environment prerequisite
            pytest.fail(f"dedicated real Redis is unavailable: {exc}")

        config = await redis.config_get("maxmemory", "maxmemory-policy")
        assert config.get("maxmemory-policy") == "noeviction"
        maxmemory = int(config["maxmemory"])
        assert maxmemory > 0
        memory = await redis.info("memory")
        stats = await redis.info("stats")
        before = {
            "used_memory": int(memory["used_memory"]),
            "used_memory_peak": int(memory["used_memory_peak"]),
            "evicted_keys": _counter(stats, "evicted_keys"),
            "oom_errors": _counter(await redis.info("errorstats"), "errorstat_OOM"),
            "total_error_replies": _counter(stats, "total_error_replies"),
        }

        revoked_jti = f"{run}-existing"
        revoked_key = f"revoked:{revoked_jti}"
        active_key = f"active_jtis:{run}-user"
        rate_key = f"ratelimit:ip:{run}-masked"
        lock_key = f"lock:scan:{run}:resource"
        dlq_key = f"events:dlq:{run}-auth"
        await redis.set(revoked_key, "1", ex=3600)
        await redis.sadd(active_key, "jti-existing")
        await redis.hset(rate_key, mapping={"failures": "3", "locked_until": "2099999999"})
        await redis.expire(rate_key, 3600)
        await redis.set(lock_key, "owner-token", px=3600000)
        dlq_id = await redis.xadd(dlq_key, {"event_type": "auth", "attempt": "1"})
        dlq_before = await redis.xrange(dlq_key, dlq_id, dlq_id)

        oom: ResponseError | None = None
        deadline = time.monotonic() + 45
        for index in range(96):
            if time.monotonic() >= deadline:
                break
            key = f"{filler_prefix}{index}"
            try:
                await redis.set(key, os.urandom(1024 * 1024), ex=3600)
                filler_keys.append(key)
            except ResponseError as exc:
                oom = exc
                break
        assert oom is not None, "real Redis did not reject a bounded filler write"
        assert any(token in str(oom).upper() for token in ("OOM", "MAXMEMORY"))

        flow = "auth_change_password_revoke"
        outage_before = METRIC_OUTAGES.labels(flow=flow)._value.get()
        # Use a large, run-owned marker so the already-full allocator rejects this
        # security write rather than accepting a tiny allocation at the boundary.
        new_jti = f"new-{run}-" + ("x" * (1024 * 1024))
        with pytest.raises(RedisResponseError):
            await revoke_access_token(new_jti, 3600, redis, flow_id=flow)
        assert METRIC_OUTAGES.labels(flow=flow)._value.get() > outage_before
        assert not await redis.exists(f"revoked:{new_jti}")

        app = create_app()

        @app.get(f"/__sdd291_pressure_{run}")
        async def pressure_failure() -> None:
            raise RedisResponseError("OOM command not allowed")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/__sdd291_pressure_{run}")
        assert response.status_code == 503
        assert response.headers["Retry-After"]
        assert "OOM" not in response.text
        assert "RedisResponseError" not in response.text

        assert await redis.get(revoked_key) == "1"
        assert await redis.sismember(active_key, "jti-existing")
        assert await redis.hgetall(rate_key) == {"failures": "3", "locked_until": "2099999999"}
        assert await redis.get(lock_key) == "owner-token"
        assert await is_token_revoked(revoked_jti, redis) is True
        assert await redis.xrange(dlq_key, dlq_id, dlq_id) == dlq_before

        after_pressure = await redis.info("stats")
        assert _counter(after_pressure, "evicted_keys") == before["evicted_keys"]
        errorstats = await redis.info("errorstats")
        oom_after = _counter(errorstats, "errorstat_OOM")
        assert oom_after >= before["oom_errors"]

        # Recovery removes only this run's filler keys, never seeded state or DLQ history.
        deleted = 0
        async for key in redis.scan_iter(match=f"{filler_prefix}*"):
            deleted += await redis.delete(key)
        assert deleted == len(filler_keys)
        recovery_key = f"{prefix}recovery"
        assert await redis.set(recovery_key, "ok", ex=60)
        assert await redis.get(revoked_key) == "1"
        assert await redis.xrange(dlq_key, dlq_id, dlq_id) == dlq_before
        final_memory = await redis.info("memory")
        final_stats = await redis.info("stats")
        evidence = {
            "redis_version": (await redis.info("server"))["redis_version"],
            "environment": "disposable-real-redis",
            "limits": {"maxmemory": maxmemory, "container_bound_env": "REDIS_PRESSURE_MEM_LIMIT"},
            "policy": config["maxmemory-policy"],
            "workload": {"filler": "unique 1 MiB incompressible values", "seeded_state": 5},
            "memory": {"used_before": before["used_memory"], "peak_before": before["used_memory_peak"], "used_after": int(final_memory["used_memory"])},
            "headroom_after": max(0, maxmemory - int(final_memory["used_memory"])),
            "oom_errors": oom_after,
            "total_error_replies": _counter(final_stats, "total_error_replies"),
            "evicted_keys_before": before["evicted_keys"],
            "evicted_keys_after": _counter(final_stats, "evicted_keys"),
            "typed_exception": RedisResponseError.__name__,
            "http_status": response.status_code,
            "preserved": {"security_state": True, "dlq": True},
        }
        print(f"REDIS_PRESSURE_EVIDENCE {json.dumps(evidence, sort_keys=True)}")
    finally:
        for key in filler_keys:
            await redis.delete(key)
        await redis.aclose()
