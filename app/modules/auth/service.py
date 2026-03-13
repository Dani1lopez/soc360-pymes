import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    verify_password,
    hash_password,
    revoke_access_token,
)
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User
from app.modules.tenants.models import Tenant
from app.modules.auth.schemas import TokenResponse


MAX_ACTIVE_SESSIONS = 5
REFRESH_TOKEN_EXPIRE_DAYS = 7
LOGIN_ATTEMPTS_WINDOW_SECONDS = 900
LOGIN_ATTEMPTS_MAX = 10


class AuthError(Exception):
    """
    Error de autenticación lanzado por el service layer.
    El router es responsable de convertirlo a HTTPException.
    Separar la excepción del HTTP permite reutilizar el service
    en tests y workers sin depender de FastAPI.
    """
    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


async def _check_account_lockout(email: str, redis: Redis) -> None:
    """Verifica si la cuenta esta bloqueada por demasiados intentos fallidos"""
    key = f"login_attempts:{hashlib.sha256(email.encode()).hexdigest()}"
    attempts = await redis.get(key)
    if attempts and int(attempts) >= LOGIN_ATTEMPTS_MAX:
        ttl = await redis.ttl(key)
        raise AuthError(
            message=f"Cuenta bloqueada temporalmente. Intenta de nuevo en {ttl} segundos.",
            code="ACCOUNT_TEMPORARILY_LOCKED",
        )


async def _record_failed_attempt(email: str, redis: Redis) -> None:
    """Incrementa el contador de intentos fallidos para el email dado."""
    key = f"login_attempts:{hashlib.sha256(email.encode()).hexdigest()}"
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, LOGIN_ATTEMPTS_WINDOW_SECONDS)


async def _clear_login_attempts(email: str, redis: Redis) -> None:
    """Limpia el contador tras un login exitoso"""
    key = f"login_attempts:{hashlib.sha256(email.encode()).hexdigest()}"
    await redis.delete(key)


async def _get_active_user(email: str, db: AsyncSession) -> User:
    """Carga el usuario pro email y verifica que esta activo"""
    user = await db.scalar(
        select(User).where(User.email == email)
    )
    if not user or not user.is_active:
        raise AuthError(
            message="Credenciales incorrectas",
            code="INVALID_CREDENTIALS",
        )
    return user


async def _check_tenant_active(user: User, db: AsyncSession) -> None:
    """Verifica que el tenant del usuario esta activo"""
    if user.is_superadmin:
        return
    
    tenant = await db.scalar(
        select(Tenant).where(Tenant.id == user.tenant_id)
    )
    
    if not tenant or not tenant.is_active:
        raise AuthError(
            message="Credenciales incorrectas",
            code="INVALID_CREDENTIALS",
        )