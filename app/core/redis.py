from __future__ import annotations

from collections.abc import AsyncGenerator
from redis.asyncio import Redis, ConnectionPool
from app.core.config import settings


#Se crea una vez cuando arranca la app
_pool: ConnectionPool | None = None


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


async def ping_redis() -> bool:
    redis = Redis(connection_pool=get_pool())
    try:
        return await redis.ping()
    finally:
        await redis.aclose()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None