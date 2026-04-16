from __future__ import annotations

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
    track_jti,
    untrack_jti,
    revoke_all_user_access_tokens,
)
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User
from app.modules.tenants.models import Tenant
from app.modules.auth.schemas import TokenResponse
from app.core.exceptions import AuthError

MAX_ACTIVE_SESSIONS = 5
REFRESH_TOKEN_EXPIRE_DAYS = 7
LOGIN_ATTEMPTS_WINDOW_SECONDS = 900
LOGIN_ATTEMPTS_MAX = 10



def _login_attempts_key(email: str) -> str:
    """Genera la clave Redis para el contador de intentos de login."""
    return f"login_attempts:{hashlib.sha256(email.encode()).hexdigest()}"


async def _check_account_lockout(email: str, redis: Redis) -> None:
    """Verifica si la cuenta esta bloqueada por demasiados intentos fallidos"""
    key = _login_attempts_key(email)
    attempts = await redis.get(key)
    if attempts and int(attempts) >= LOGIN_ATTEMPTS_MAX:
        ttl = await redis.ttl(key)
        raise AuthError(
            status_code=429,
            detail=f"Cuenta bloqueada temporalmente. Intenta de nuevo en {ttl} segundos.",
        )


async def _record_failed_attempt(email: str, redis: Redis) -> None:
    """Incrementa el contador de intentos fallidos para el email dado."""
    key = _login_attempts_key(email)
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, LOGIN_ATTEMPTS_WINDOW_SECONDS)


async def _clear_login_attempts(email: str, redis: Redis) -> None:
    """Limpia el contador tras un login exitoso"""
    key = _login_attempts_key(email)
    await redis.delete(key)


async def _get_active_user(email: str, db: AsyncSession) -> User:
    """Carga el usuario pro email y verifica que esta activo"""
    user = await db.scalar(
        select(User).where(User.email == email)
    )
    if not user or not user.is_active:
        raise AuthError(
            status_code=401,
            detail="Credenciales incorrectas",
        )
    return user


async def _get_active_user_by_id(user_id: UUID, db: AsyncSession) -> User:
    """Carga usuario por id y verifica que esta activo"""
    user = await db.scalar(
        select(User).where(User.id == user_id)
    )
    if not user or not user.is_active:
        raise AuthError(
            status_code=401,
            detail="Usuario inactivo.",
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
            status_code=401,
            detail="Credenciales incorrectas",
        )


async def _create_refresh_token(
    user_id: UUID,
    db: AsyncSession,
    created_from_ip: str | None = None,
) -> str:
    """Genera un refresh token seguro, lo hashea y guarda en BD"""
    active_count = await db.scalar(
        select(func.count()).select_from(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .where(RefreshToken.revoked_at.is_(None))
        .where(RefreshToken.expires_at > datetime.now(timezone.utc))
    ) or 0
    
    if active_count >= MAX_ACTIVE_SESSIONS:
        oldest = await db.scalar(
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .order_by(RefreshToken.created_at.asc())
            .limit(1)
        )
        if oldest:
            oldest.revoked_at = datetime.now(timezone.utc)
    
    raw_token = secrets.token_urlsafe(64)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    
    db.add(RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        created_from_ip=created_from_ip,
    ))
    
    return raw_token


async def _revoke_all_user_tokens(
    user_id: UUID,
    db: AsyncSession,
) -> None:
    """Revoca todos los refresh tokens activos del usuario en una sola query"""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .where(RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def login(
    email: str,
    password: str,
    db: AsyncSession,
    redis: Redis,
    request_ip: str | None = None
) -> tuple[TokenResponse, str]:
    """Autentica al usuario y delvuelve el access token + refresh token"""
    await _check_account_lockout(email, redis)
    
    user = await _get_active_user(email, db)
    
    if not verify_password(password, user.hashed_password):
        await _record_failed_attempt(email, redis)
        raise AuthError(
            status_code=401,
            detail="Credenciales incorrectas.",
        )
    
    await _check_tenant_active(user, db)
    
    await _clear_login_attempts(email, redis)
    
    access_token, jti = create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id) if user.tenant_id else None,
        role=user.role,
        is_superadmin=user.is_superadmin,
    )
    await track_jti(str(user.id), jti, redis)
    refresh_token = await _create_refresh_token(user.id, db, created_from_ip=request_ip)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    ), refresh_token


async def refresh_tokens(
    refresh_token: str,
    db: AsyncSession,
    redis: Redis,
    request_ip: str | None = None,
    old_jti: str | None = None,
) -> tuple[TokenResponse, str]:
    """Invalida el anterior y genera uno nuevo"""
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    record = await db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .where(RefreshToken.revoked_at.is_(None))
        .where(RefreshToken.expires_at > datetime.now(timezone.utc))
    )
    if not record:
        raise AuthError(
            status_code=401,
            detail="Refresh token invalido o expirado",
        )
    
    user = await _get_active_user_by_id(record.user_id, db)
    await _check_tenant_active(user, db)
    
    record.revoked_at = datetime.now(timezone.utc)
    new_refresh_token = await _create_refresh_token(
        user.id, db, created_from_ip=request_ip
    )
    
    access_token, new_jti = create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id) if user.tenant_id else None,
        role=user.role,
        is_superadmin=user.is_superadmin,
    )
    
    # Revocar el access token viejo si se proporcionó
    if old_jti:
        await revoke_access_token(
            jti=old_jti,
            ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            redis=redis,
        )
        await untrack_jti(str(user.id), old_jti, redis)
    
    await track_jti(str(user.id), new_jti, redis)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    ), new_refresh_token


async def logout(
    jti: str,
    refresh_token: str,
    user_id: str,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Revoca el acces token y el refresh token"""
    await revoke_access_token(
        jti=jti,
        ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        redis=redis,
    )
    await untrack_jti(user_id, jti, redis)
    
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    record = await db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .where(RefreshToken.revoked_at.is_(None))
    )
    if record:
        record.revoked_at = datetime.now(timezone.utc)


async def change_password(
    user_id: UUID,
    current_password: str,
    new_password: str,
    current_jti: str,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Cambia la contraseña y revoca todas las sesiones activas"""
    user = await _get_active_user_by_id(user_id, db)
    if not verify_password(current_password, user.hashed_password):
        raise AuthError(
            status_code=400,
            detail="La contraseña actual es incorrecta.",
        )
    
    user.hashed_password = hash_password(new_password)
    
    await _revoke_all_user_tokens(user_id, db)
    
    await revoke_all_user_access_tokens(
        user_id=str(user_id),
        redis=redis,
        ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )