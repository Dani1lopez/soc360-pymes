from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


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
        raise JWTError(f"Payload incompleto, faltan campos: {missing}")
    
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
    return await redis.exists(f"{_DENYLIST_PREFIX}{jti}") > 0


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
    """Revoca todos los JTIs activos del usuario y elimina el conjunto.
    
    Usa pipeline atómico para denylist + delete. Si falla, la denylist parcial
    sigue siendo segura (los tokens siguen bloqueados aunque no se borró el set).
    """
    key = f"{_ACTIVE_JTIS_PREFIX}{user_id}"
    jtis = await redis.smembers(key)
    if not jtis:
        logger.debug("No hay JTIs activos para revocar", extra={"user_id": user_id})
        return
    
    jti_strs = [j.decode() if isinstance(j, bytes) else j for j in jtis]
    
    async with redis.pipeline(transaction=True) as pipe:
        for jti in jti_strs:
            pipe.set(f"{_DENYLIST_PREFIX}{jti}", "1", ex=ttl_seconds)
        pipe.delete(key)
        await pipe.execute()
    
    logger.info("Todos los JTIs del usuario revocados", extra={"user_id": user_id, "count": len(jti_strs)})


def secure_compare(val_a: str, val_b: str) -> bool:
    """Compara dos strings en tiempo constante"""
    return hmac.compare_digest(val_a.encode(), val_b.encode())