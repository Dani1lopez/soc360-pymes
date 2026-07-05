from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from redis.asyncio import Redis, ConnectionPool
from app.core.config import settings
from app.core.logging import get_logger


#Se crea una vez cuando arranca la app
_pool: ConnectionPool | None = None
logger = get_logger(__name__)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            str(settings.REDIS_URL),
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
        )
    return _pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    redis = Redis(connection_pool=get_pool())
    try:
        yield redis
    finally:
        await redis.aclose()


async def get_redis_client() -> Redis:
    """Direct async factory. Caller owns the connection lifecycle."""
    return Redis(connection_pool=get_pool())


async def ping_redis() -> bool:
    redis = Redis(connection_pool=get_pool())
    try:
        return await redis.ping()
    finally:
        await redis.aclose()


async def check_redis_healthy(redis: Redis) -> bool:
    """Returns True if Redis is reachable, False otherwise."""
    try:
        return await redis.ping()
    except Exception:
        return False


async def ping_redis_with_retry(
    *,
    max_attempts: int = 3,
    backoff_base_seconds: float = 1.0,
) -> bool:
    """Ping Redis with exponential backoff for the FastAPI lifespan (issue #128).

    Returns True on the first successful ping. Returns False if every attempt
    fails. Each failed attempt is logged with the underlying error so operators
    can diagnose transient outages — we never swallow the cause.

    Backoff schedule: attempt N waits ``backoff_base_seconds * 2**(N-1)``
    seconds before the next try (1s, 2s, 4s by default).
    """
    for attempt in range(1, max_attempts + 1):
        error: Exception | None = None
        try:
            if await ping_redis():
                if attempt > 1:
                    logger.info("redis_ping_recovered", attempt=attempt)
                return True
        except Exception as exc:
            error = exc

        is_last = attempt >= max_attempts
        wait = backoff_base_seconds * (2 ** (attempt - 1))
        log_payload = {
            "attempt": attempt,
            "max_attempts": max_attempts,
            "error": str(error) if error else "ping returned falsy",
            "error_type": type(error).__name__ if error else None,
        }
        if is_last:
            logger.error("redis_ping_attempts_exhausted", **log_payload)
            return False
        logger.warning(
            "redis_ping_attempt_failed",
            **log_payload,
            backoff_seconds=wait,
        )
        await asyncio.sleep(wait)

    return False  # unreachable; keeps type-checkers happy


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None