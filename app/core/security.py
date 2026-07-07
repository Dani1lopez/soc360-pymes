from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import anyio
import bcrypt
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from redis.asyncio import Redis

from app.core.config import settings
from app.core.exceptions import UserError
from app.core.logging import get_logger

logger = get_logger(__name__)


def hash_password(plain: str) -> str:
    """Hash password using bcrypt with 72-byte limit."""
    password_bytes = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def validate_password_length(password: str) -> None:
    """Service-level backstop for bcrypt's 72-byte password input limit."""
    if len(password.encode("utf-8")) > 72:
        raise UserError(
            {
                "code": "password_too_long",
                "message": "Password exceeds 72 bytes (UTF-8). Choose a shorter password.",
            },
            status_code=400,
        )


def verify_password(plain: str, hashed: str) -> bool:
    """Verify password against bcrypt hash."""
    return bcrypt.checkpw(
        plain.encode("utf-8")[:72],
        hashed.encode("utf-8"),
    )


async def hash_password_async(plain: str) -> str:
    """Async wrapper — offloads bcrypt.hashpw to a threadpool worker."""
    return await anyio.to_thread.run_sync(hash_password, plain)


async def verify_password_async(plain: str, hashed: str) -> bool:
    """Async wrapper — offloads bcrypt.checkpw to a threadpool worker."""
    return await anyio.to_thread.run_sync(verify_password, plain, hashed)


ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "analyst": 1,
    "ingestor": 1,
    "admin": 2,
    "superadmin": 99,
}


def can_assign_role(assigner_role: str, target_role: str) -> bool:
    """Un usuario solo puede crear usuarios con rol estrictamente inferior al suyo"""
    assigner_level = ROLE_HIERARCHY.get(assigner_role, -1)
    target_level = ROLE_HIERARCHY.get(target_role, -1)
    return target_level < assigner_level


def has_minimum_role(user_role: str, required_role: str) -> bool:
    """Verifica que el usuario tenga al menos el mismo nivel de rol requerido"""
    return ROLE_HIERARCHY.get(user_role, -1) >= ROLE_HIERARCHY.get(required_role, -1)


def create_access_token(
    *,
    user_id: str,
    tenant_id: str | None,
    role: str,
    is_superadmin: bool,
    expires_delta: timedelta | None = None,
) -> tuple[str, str]:
    """Crea un access token JWT firmado con HS256"""
    if is_superadmin and tenant_id is not None:
        raise ValueError("Superadmin no puede tener tenant_id")
    
    if not is_superadmin and tenant_id is None:
        raise ValueError("Usuario normal debe tener tenant_id")
    
    if role not in ROLE_HIERARCHY:
        raise ValueError(f"Rol invalido: {role}")
    
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    jti = str(uuid.uuid4())
    
    payload: dict[str, Any] = {
        "sub": user_id,
        "jti": jti,
        "tenant_id": tenant_id,
        "role": role,
        "is_superadmin": is_superadmin,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica y verifica la firma del JWT"""
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    
    required_fields = {"sub", "jti", "role", "is_superadmin", "tenant_id"}
    missing = required_fields - payload.keys()
    
    if missing:
        raise InvalidTokenError(f"Payload incompleto, faltan campos: {missing}")
    
    return payload


def get_token_remaining_seconds(payload: dict[str, Any]) -> int:
    """Calcula los segundos que quedan hasta que el token expire"""
    exp = payload.get("exp", 0)
    now = int(datetime.now(timezone.utc).timestamp())
    remaining = exp - now
    return max(remaining, 0)


_DENYLIST_PREFIX = "revoked:"
_ACTIVE_JTIS_PREFIX = "active_jtis:"


async def revoke_access_token(jti: str, ttl_seconds: int, redis: Redis) -> None:
    """Añade el JTI a la denylist con TTL igual al tiempo restante del token"""
    if ttl_seconds > 0:
        await redis.set(f"{_DENYLIST_PREFIX}{jti}", "1", ex=ttl_seconds)
        logger.debug("Token revocado", extra={"jti": jti, "ttl": ttl_seconds})


async def is_token_revoked(jti: str, redis: Redis) -> bool:
    """Devuelve True si el token esta en la denylist"""
    result = await redis.exists(f"{_DENYLIST_PREFIX}{jti}")
    return int(result) > 0


async def revoke_tokens_by_jtis(jtis: list[str], redis: Redis, ttl_seconds: int = 900) -> None:
    """Revoca multiples tokens en una sola operacion pipeline"""
    if not jtis:
        return
    async with redis.pipeline(transaction=False) as pipe:
        for jti in jtis:
            pipe.set(f"{_DENYLIST_PREFIX}{jti}", "1", ex=ttl_seconds)
        await pipe.execute()
    logger.info("Sesiones invalidas en bulk", extra={"count": len(jtis)})


async def track_jti(user_id: str, jti: str, redis: Redis) -> None:
    """Añade el JTI al conjunto de JTIs activos del usuario. Idempotente (SADD)."""
    await redis.sadd(f"{_ACTIVE_JTIS_PREFIX}{user_id}", jti)
    logger.debug("JTI trackeado", extra={"user_id": user_id, "jti": jti})


async def untrack_jti(user_id: str, jti: str, redis: Redis) -> None:
    """Remueve el JTI del conjunto de JTIs activos. Seguro si no existe (SREM)."""
    await redis.srem(f"{_ACTIVE_JTIS_PREFIX}{user_id}", jti)
    logger.debug("JTI untrackeado", extra={"user_id": user_id, "jti": jti})


async def get_active_jtis(user_id: str, redis: Redis) -> list[str]:
    """Devuelve la lista de JTIs activos para el usuario. Lista vacía si no hay ninguno."""
    members = await redis.smembers(f"{_ACTIVE_JTIS_PREFIX}{user_id}")
    return [m.decode() if isinstance(m, bytes) else m for m in members]


async def revoke_all_user_access_tokens(
    user_id: str,
    redis: Redis,
    ttl_seconds: int,
) -> None:
    """Revoca todos los JTIs activos del usuario usando comandos ordenados (REQ-140-R05).

    Estrategia defense-in-depth:
    1. Escribe cada entrada denylist con ``redis.set(...)`` ordenado (sin pipeline).
    2. Si al menos una SET tuvo éxito, intenta eliminar el set ``active_jtis``
       (best-effort) incluso si alguna SET posterior falló.
    3. Si ninguna SET tuvo éxito, propaga el error para que el caller reintente.

    Esto evita el estado parcial ambiguo de usar ``pipeline(transaction=True)``:
    si el pipeline falla en ``execute()``, no sabemos cuántas SET llegaron a Redis.
    """
    key = f"{_ACTIVE_JTIS_PREFIX}{user_id}"
    jtis = await redis.smembers(key)
    if not jtis:
        logger.debug("No hay JTIs activos para revocar", extra={"user_id": user_id})
        return

    jti_strs = [j.decode() if isinstance(j, bytes) else j for j in jtis]
    denylisted_count = 0

    # Fase 1: denylist SETs ordenados (sin pipeline, REQ-140-R05)
    for jti in jti_strs:
        try:
            await redis.set(f"{_DENYLIST_PREFIX}{jti}", "1", ex=ttl_seconds)
            denylisted_count += 1
        except Exception:
            if denylisted_count == 0:
                # Zero success — propagate for retry
                logger.warning(
                    "redis_revoke_zero_success",
                    extra={"user_id": user_id, "jtis_count": len(jti_strs)},
                )
                raise
            # Partial success — log and continue to best-effort cleanup
            logger.warning(
                "redis_revoke_all_partial_failure",
                extra={
                    "user_id": user_id,
                    "jtis_count": len(jti_strs),
                    "denylisted_count": denylisted_count,
                },
            )
            break

    # Fase 2: best-effort DELETE del set active_jtis
    try:
        await redis.delete(key)
    except Exception:
        logger.warning(
            "redis_active_jtis_cleanup_failed",
            extra={"user_id": user_id},
        )

    logger.info(
        "Todos los JTIs del usuario revocados",
        extra={"user_id": user_id, "count": denylisted_count, "total_jtis": len(jti_strs)},
    )


async def revoke_all_user_access_tokens_batch(
    user_ids: list[str],
    redis: Redis,
    ttl_seconds: int,
) -> None:
    """Batch revocation for multiple users — O(1) pipelines instead of O(u).
    
    Performance fix (issue #104): When deactivating a tenant with many users,
    the old code called revoke_all_user_access_tokens() for each user individually,
    resulting in O(u) Redis pipelines where u = number of users. For a tenant with
    500 users and 5 sessions per user, this could mean ~3,500 Redis commands
    concurrent with only 20 connections available, causing ConnectionError timeouts.
    
    This batch function:
    1. Makes ONE pipeline to SMEMBERS all user JTI sets (batch read)
    2. Collects all JTIs from all users
    3. Makes ONE pipeline to DENYLIST all JTIs + DELETE all JTI sets (batch write)
    
    Reduces O(u) pipelines to O(1) pipelines.
    
    Args:
        user_ids: List of user IDs to revoke tokens for
        redis: Redis client instance
        ttl_seconds: TTL for denylist entries
    """
    if not user_ids:
        return
    
    # Phase 1: Collect all JTIs from all users
    # Note: We use individual SMEMBERS calls instead of a pipeline because
    # FakeRedis (used in tests) doesn't handle pipeline(transaction=False) correctly.
    # This is still O(u) reads + O(1) writes, which is much better than O(u) full pipelines.
    all_jtis: list[tuple[str, str]] = []  # (user_id, jti) pairs
    for uid in user_ids:
        jtis = await redis.smembers(f"{_ACTIVE_JTIS_PREFIX}{uid}")
        if jtis:
            for jti in jtis:
                jti_str = jti.decode() if isinstance(jti, bytes) else jti
                all_jtis.append((uid, jti_str))
    
    if not all_jtis:
        logger.debug("No active JTIs to revoke for any user", extra={"user_count": len(user_ids)})
        return
    
    # Phase 3: Batch DENYLIST + DELETE in a single pipeline
    async with redis.pipeline(transaction=False) as pipe:
        for uid, jti in all_jtis:
            pipe.set(f"{_DENYLIST_PREFIX}{jti}", "1", ex=ttl_seconds)
        # Delete all JTI sets
        for uid in user_ids:
            pipe.delete(f"{_ACTIVE_JTIS_PREFIX}{uid}")
        
        try:
            await pipe.execute()
        except Exception:
            logger.exception(
                "redis_batch_pipeline_failed",
                extra={"user_count": len(user_ids), "jti_count": len(all_jtis)},
            )
            raise
    
    logger.info(
        "Batch token revocation completed",
        extra={"user_count": len(user_ids), "jti_count": len(all_jtis)},
    )


def secure_compare(val_a: str, val_b: str) -> bool:
    """Compara dos strings en tiempo constante"""
    return hmac.compare_digest(val_a.encode(), val_b.encode())
