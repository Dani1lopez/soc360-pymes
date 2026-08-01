from __future__ import annotations

import asyncio
import hashlib
import hmac
import random
import re
import secrets
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core.config import settings
from app.core.exceptions import RedisOutageError, TemporaryUnavailableError
from app.core.logging import get_logger
from app.core.outage import AsyncWaiter, RedisLockWaiter, classify_redis_error
from app.core.redis import get_redis_client

_LOCK_RESOURCE_SUPERADMIN_SESSION = "__SUPERADMIN_SESSION__"
_LOCK_RESOURCE_TENANT_DEACTIVATION = "__TENANT_DEACTIVATION__"
LOCK_MIN_TTL_SECONDS: int = 1
RENEW_LUA = (
    'if redis.call("GET", KEYS[1]) == ARGV[1] then '
    'return redis.call("PEXPIRE", KEYS[1], ARGV[2]) else return 0 end'
)
RELEASE_LUA = (
    'if redis.call("GET", KEYS[1]) == ARGV[1] then '
    'return redis.call("DEL", KEYS[1]) else return 0 end'
)
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9_-]+")
_ACTIVE_TOKENS: dict[str, str] = {}
logger = get_logger(__name__)


def _safe_component(value: str) -> str:
    return (
        value
        if value and _SAFE_COMPONENT.fullmatch(value)
        else hashlib.sha256(value.encode()).hexdigest()
    )


def _lock_key_secret() -> bytes:
    configured = getattr(settings, "LOCK_KEY_SECRET", None)
    if configured is None:
        raise ValueError("LOCK_KEY_SECRET is required for distributed locks")
    secret = (
        configured.get_secret_value()
        if hasattr(configured, "get_secret_value")
        else str(configured)
    )
    if not secret:
        raise ValueError("LOCK_KEY_SECRET is required for distributed locks")
    return secret.encode()


def build_lock_key(flow_id: str, tenant_id: str, asset_id: str) -> str:
    """Build ``lock:{flow}:{hmac}:{tenant}:{resource}`` without unsafe segments."""
    tenant, asset = str(tenant_id), str(asset_id)
    namespace = (
        hmac.new(_lock_key_secret(), tenant.encode(), hashlib.sha256).digest()[:8].hex()
    )
    return ":".join(
        (
            "lock",
            _safe_component(str(flow_id)),
            namespace,
            _safe_component(tenant),
            _safe_component(asset),
        )
    )


def _validate_ttl(ttl_seconds: int) -> None:
    if ttl_seconds < LOCK_MIN_TTL_SECONDS:
        raise ValueError("ttl_seconds must be >= LOCK_MIN_TTL_SECONDS")


def _log_not_owner(event: str, handle: "LockHandle") -> None:
    logger.warning(
        event,
        key_hash=hashlib.sha256(handle.key.encode()).hexdigest()[:8],
        tenant_id=handle._tenant_id,
    )


def _record(kind: str, flow_id: str, outcome: str, operation: str = "") -> None:
    """Emit optional PR5b metrics without making PR5a depend on their symbols."""
    try:
        if kind == "acquire":
            from app.core.metrics import METRIC_LOCK_ACQUIRE_TOTAL  # type: ignore[attr-defined]

            METRIC_LOCK_ACQUIRE_TOTAL.labels(flow=flow_id, outcome=outcome).inc()
        elif kind == "renew":
            from app.core.metrics import METRIC_LOCK_RENEW_TOTAL  # type: ignore[attr-defined]

            METRIC_LOCK_RENEW_TOTAL.labels(flow=flow_id, outcome=outcome).inc()
        elif kind == "release":
            from app.core.metrics import METRIC_LOCK_RELEASE_TOTAL  # type: ignore[attr-defined]

            METRIC_LOCK_RELEASE_TOTAL.labels(flow=flow_id, outcome=outcome).inc()
        else:
            from app.core.metrics import METRIC_LOCK_CONTENTION_TOTAL  # type: ignore[attr-defined]

            METRIC_LOCK_CONTENTION_TOTAL.labels(
                flow=flow_id, operation=operation, outcome=outcome
            ).inc()
    except (ImportError, AttributeError):
        pass


def _record_wait(flow_id: str, operation: str, wait_seconds: float) -> None:
    """Emit optional lock-wait telemetry without changing lock semantics."""
    try:
        from app.core.metrics import METRIC_LOCK_WAIT_SECONDS  # type: ignore[attr-defined]

        METRIC_LOCK_WAIT_SECONDS.labels(flow=flow_id, operation=operation).observe(
            wait_seconds
        )
    except (ImportError, AttributeError):
        pass


async def _set_lock(redis: Any, key: str, token: str, ttl_seconds: int) -> bool:
    try:
        return bool(await redis.set(key, token, nx=True, px=ttl_seconds * 1000))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise classify_redis_error(exc) from exc


async def _eval_script(
    redis: Any,
    script: str,
    key: str,
    token: str,
    argument: int,
    *,
    flow_id: str | None = None,
    metric_kind: str | None = None,
) -> Any:
    try:
        return await redis.eval(script, 1, key, token, argument)
    except ResponseError as exc:
        if "NOSCRIPT" not in str(exc).upper():
            raise
        await redis.script_load(script)
        if flow_id is not None and metric_kind is not None:
            _record(metric_kind, flow_id, "noscript_recovered")
        return await redis.eval(script, 1, key, token, argument)


async def _eval_owner_script(
    redis: Any,
    script: str,
    key: str,
    token: str,
    argument: int,
    *,
    flow_id: str | None = None,
    metric_kind: str | None = None,
) -> Any:
    try:
        return await _eval_script(
            redis,
            script,
            key,
            token,
            argument,
            flow_id=flow_id,
            metric_kind=metric_kind,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise classify_redis_error(exc) from exc


async def _cancel_retry(task: asyncio.Task[Any]) -> None:
    if not task.done():
        task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@dataclass
class LockHandle:
    key: str
    owner_token: str
    acquired_at: float
    ttl_seconds: int
    flow_id: str
    _redis: Any = field(default=None, repr=False, compare=False)
    _tenant_id: str = field(default="", repr=False, compare=False)
    _lost: bool = field(default=False, init=False, repr=False)
    _released: bool = field(default=False, init=False, repr=False)

    @property
    def is_lost(self) -> bool:
        return self._lost

    def _mark_lost(self) -> None:
        self._lost = True
        if _ACTIVE_TOKENS.get(self.key) == self.owner_token:
            _ACTIVE_TOKENS.pop(self.key, None)

    async def renew(self, *, ttl_seconds: int | None = None) -> bool:
        if self._lost or self._released:
            return False
        new_ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        _validate_ttl(new_ttl)
        try:
            result = await _eval_owner_script(
                self._redis,
                RENEW_LUA,
                self.key,
                self.owner_token,
                new_ttl * 1000,
                flow_id=self.flow_id,
                metric_kind="renew",
            )
        except RedisOutageError:
            raise
        if result:
            self.ttl_seconds = new_ttl
            _record("renew", self.flow_id, "acquired")
            return True
        self._mark_lost()
        _log_not_owner("distributed_lock_renew_not_owner", self)
        _record("renew", self.flow_id, "lost")
        return False

    async def release(self) -> bool:
        if self._released:
            return False
        if self._lost:
            self._released = True
            _record("release", self.flow_id, "lost")
            return False
        try:
            result = await _eval_owner_script(
                self._redis,
                RELEASE_LUA,
                self.key,
                self.owner_token,
                0,
                flow_id=self.flow_id,
                metric_kind="release",
            )
        except RedisOutageError:
            raise
        self._released = True
        if result:
            _ACTIVE_TOKENS.pop(self.key, None)
            _record("release", self.flow_id, "acquired")
            return True
        self._mark_lost()
        _log_not_owner("distributed_lock_release_not_owner", self)
        _record("release", self.flow_id, "not_owner")
        return False

    async def __aenter__(self) -> "LockHandle":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc_type is asyncio.CancelledError:
            try:
                await self.release()
            except BaseException:
                _log_not_owner("distributed_lock_release_failed_on_cancel", self)
            finally:
                _record("release", self.flow_id, "cancelled")
                raise asyncio.CancelledError
        await self.release()
        return False


@asynccontextmanager
async def acquire_dist_lock(
    *,
    flow_id: str,
    tenant_id: str,
    asset_id: str,
    ttl_seconds: int,
    operation: str,
    wait_timeout_seconds: float,
    redis: Redis | None = None,
    waiter: AsyncWaiter | None = None,
) -> AsyncIterator[LockHandle]:
    """Acquire one namespaced Redis lease and release it on every exit path."""
    _validate_ttl(ttl_seconds)
    key = build_lock_key(flow_id, tenant_id, asset_id)
    redis_client = redis if redis is not None else await get_redis_client()
    token = secrets.token_hex(16)
    wait_started_at = time.monotonic()
    if not await _set_lock(redis_client, key, token, ttl_seconds):
        if key in _ACTIVE_TOKENS:
            _record_wait(flow_id, operation, time.monotonic() - wait_started_at)
            _record("acquire", flow_id, "reentry")
            _record("contention", flow_id, "reentry", operation)
            raise TemporaryUnavailableError("lock_reentry")
        jitter = random.uniform(0.1, 0.5)

        async def retry() -> bool:
            await asyncio.sleep(jitter)
            return await _set_lock(redis_client, key, token, ttl_seconds)

        task = asyncio.create_task(retry())
        try:
            acquired = await (waiter or RedisLockWaiter()).wait(
                task, timeout=wait_timeout_seconds
            )
        except asyncio.TimeoutError:
            await _cancel_retry(task)
            acquired = False
        except BaseException:
            await _cancel_retry(task)
            raise
        if not acquired:
            _record_wait(flow_id, operation, time.monotonic() - wait_started_at)
            _record("acquire", flow_id, "contended")
            _record("contention", flow_id, "contended", operation)
            raise TemporaryUnavailableError("lock_timeout")

    handle = LockHandle(
        key,
        token,
        time.monotonic(),
        ttl_seconds,
        flow_id,
        _redis=redis_client,
        _tenant_id=str(tenant_id),
    )
    _ACTIVE_TOKENS[key] = token
    _record("acquire", flow_id, "acquired")
    try:
        yield handle
    except BaseException as exc:
        await handle.__aexit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        await handle.__aexit__(None, None, None)
