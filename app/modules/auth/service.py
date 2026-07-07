from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import select, update, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    hash_password_async,
    verify_password_async,
    validate_password_length,
    revoke_access_token,
    track_jti,
    untrack_jti,
    revoke_all_user_access_tokens,
)
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User
from app.modules.tenants.models import Tenant
from app.modules.auth.schemas import TokenResponse
from sqlalchemy.exc import DBAPIError

from app.core.database import set_tenant_context
from app.core.exceptions import AuthError, ServiceUnavailableError
from app.core.pii import hash_email, mask_ip
from app.core.redis import check_redis_healthy

MAX_ACTIVE_SESSIONS = 5
REFRESH_TOKEN_EXPIRE_DAYS = 7
LOGIN_ATTEMPTS_WINDOW_SECONDS = 900
LOGIN_ATTEMPTS_MAX = 10

logger = get_logger(__name__)

if TYPE_CHECKING:
    from app.event_bus import EventBus


async def get_event_bus() -> "EventBus":
    """Thin alias so tests can patch app.modules.auth.service.get_event_bus."""
    from app.dependencies import get_event_bus as _get
    return await _get()



def _login_attempts_key(email: str) -> str:
    """Genera la clave Redis para el contador de intentos de login."""
    return f"login_attempts:{hashlib.sha256(email.encode()).hexdigest()}"


async def _check_account_lockout(email: str, redis: Redis) -> None:
    """Verifica si la cuenta esta bloqueada por demasiados intentos fallidos.

    El lockout se rastrea internamente (Redis) pero el response PUBLICO
    devuelve 401 generico para no revelar existencia de la cuenta.
    Si Redis esta caido, se niega el acceso por seguridad (fail-closed).
    """
    key = _login_attempts_key(email)
    try:
        attempts = await redis.get(key)
    except Exception:
        logger.warning("login_lockout_check_failed", reason="redis_error")
        raise AuthError(
            status_code=401,
            detail="Credenciales incorrectas",
        )
    if attempts and int(attempts) >= LOGIN_ATTEMPTS_MAX:
        raise AuthError(
            status_code=401,
            detail="Credenciales incorrectas",
        )


async def _record_failed_attempt(email: str, redis: Redis) -> None:
    """Incrementa el contador de intentos fallidos para el email dado.
    Si Redis falla, se loguea warning y se continua (best-effort).
    """
    key = _login_attempts_key(email)
    try:
        attempts = await redis.incr(key)
        if attempts == 1:
            await redis.expire(key, LOGIN_ATTEMPTS_WINDOW_SECONDS)
    except Exception:
        logger.warning("login_record_failed_attempt_failed", reason="redis_error")


async def _clear_login_attempts(email: str, redis: Redis) -> None:
    """Limpia el contador tras un login exitoso.
    Si Redis falla, se loguea warning y se continua (best-effort).
    """
    key = _login_attempts_key(email)
    try:
        await redis.delete(key)
    except Exception:
        logger.warning("login_clear_attempts_failed", reason="redis_error")


async def _get_active_user(email: str, db: AsyncSession) -> tuple[User, Tenant | None]:
    """Carga el usuario por email (con Tenant en un solo SELECT) y verifica que esta activo.

    Returns (user, tenant). Tenant is None for superadmins.
    """
    stmt = (
        select(User, Tenant)
        .outerjoin(Tenant, User.tenant_id == Tenant.id)
        .where(User.email == email)
    )
    row = await db.execute(stmt)
    result = row.one_or_none()
    if not result:
        raise AuthError(
            status_code=401,
            detail="Credenciales incorrectas",
        )
    user, tenant = result
    if not user.is_active:
        raise AuthError(
            status_code=401,
            detail="Credenciales incorrectas",
        )
    return user, tenant


async def _get_active_user_by_id(user_id: UUID, db: AsyncSession) -> tuple[User, Tenant | None]:
    """Carga usuario por id (con Tenant en un solo SELECT) y verifica que esta activo.

    Returns (user, tenant). Tenant is None for superadmins.
    """
    stmt = (
        select(User, Tenant)
        .outerjoin(Tenant, User.tenant_id == Tenant.id)
        .where(User.id == user_id)
    )
    row = await db.execute(stmt)
    result = row.one_or_none()
    if not result:
        raise AuthError(
            status_code=401,
            detail="Usuario inactivo.",
        )
    user, tenant = result
    if not user.is_active:
        raise AuthError(
            status_code=401,
            detail="Usuario inactivo.",
        )
    return user, tenant


async def _check_tenant_active(user: User, tenant: Tenant | None) -> None:
    """Verifica que el tenant del usuario esta activo.

    Uses the pre-loaded tenant from the JOIN in _get_active_user /
    _get_active_user_by_id — no extra SELECT needed.
    """
    if user.is_superadmin:
        return

    if not tenant or not tenant.is_active:
        raise AuthError(
            status_code=401,
            detail="Credenciales incorrectas",
        )


# PostgreSQL advisory lock SQL — serializes session-cap checks per user.
# Uses pg_advisory_xact_lock so the lock is held for the transaction duration
# and released automatically on commit or rollback.
_ADVISORY_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:user_id AS text), 0))"
)

# Set a transaction-local lock_timeout so pg_advisory_xact_lock cannot block
# indefinitely. set_config(..., true) makes it LOCAL (transaction-scoped),
# mirroring the pattern used by set_tenant_context.
_LOCK_TIMEOUT_SQL = text(
    "SELECT set_config('lock_timeout', :timeout_ms, true)"
)

# 2-second timeout for advisory lock acquisition.
_ADVISORY_LOCK_TIMEOUT_MS = "2000"

# SQLSTATE code for lock_not_available (raised when lock_timeout expires).
_LOCK_TIMEOUT_SQLSTATE = "55P03"


def _is_lock_timeout_error(exc: DBAPIError) -> bool:
    """Detect whether *exc* is a lock-timeout error (SQLSTATE 55P03).

    SQLAlchemy wraps the underlying DBAPI exception.  For most dialects
    a lock timeout surfaces as ``OperationalError`` (a ``DBAPIError``
    subclass), but with asyncpg the driver maps
    ``asyncpg.LockNotAvailableError`` through the generic DBAPI ``Error``
    which SQLAlchemy wraps as a plain ``DBAPIError`` — **not**
    ``OperationalError``.  We therefore accept the full ``DBAPIError``
    hierarchy and inspect ``orig`` / ``sql_error()`` for the SQLSTATE.

    Detection layers (dialect-agnostic):

    * **asyncpg** — ``orig`` is an ``asyncpg.LockNotAvailableError`` with
      ``.sqlstate == '55P03'``.
    * **psycopg (3) / psycopg2** — ``orig`` carries ``.pgcode == '55P03'``.
    * Other dialects may expose ``.code`` or only the SQLSTATE in the
      string representation or ``sql_error()`` output.
    """
    orig = exc.orig
    if orig is not None:
        # 1. Direct isinstance against asyncpg (most precise when available).
        try:
            import asyncpg

            if isinstance(orig, asyncpg.LockNotAvailableError):
                return True
        except ImportError:
            pass

        # 2. SQLSTATE / pgcode attributes on the DBAPI exception.
        for attr in ("sqlstate", "pgcode", "code"):
            if getattr(orig, attr, None) == _LOCK_TIMEOUT_SQLSTATE:
                return True

        # 3. String fallback on orig — some drivers embed the SQLSTATE.
        if _LOCK_TIMEOUT_SQLSTATE in str(orig):
            return True

    # 4. sql_error() — DBAPIError may expose the SQLSTATE in its structured
    #    error dict even when orig is heavily wrapped.
    try:
        sql_err = exc.sql_error()
        if sql_err and _LOCK_TIMEOUT_SQLSTATE in str(sql_err):
            return True
    except Exception:  # pragma: no cover - defensive
        pass

    return False


async def _acquire_session_cap_lock(user_id: UUID, db: AsyncSession) -> None:
    """Acquire a transaction-scoped advisory lock for session-cap serialization.

    Must be called inside an active transaction (db.in_transaction() == True).
    Sets a 2-second lock_timeout before acquiring the lock so that contention
    raises a controlled error instead of blocking indefinitely.

    Raises ServiceUnavailableError if the lock cannot be acquired within the
    timeout (PostgreSQL raises lock_not_available / SQLSTATE 55P03).
    """
    if not db.in_transaction():
        raise RuntimeError(
            "_acquire_session_cap_lock requires an active transaction"
        )
    # Set transaction-local lock_timeout so the advisory lock cannot hang.
    await db.execute(_LOCK_TIMEOUT_SQL, {"timeout_ms": _ADVISORY_LOCK_TIMEOUT_MS})
    try:
        await db.execute(_ADVISORY_LOCK_SQL, {"user_id": str(user_id)})
    except DBAPIError as exc:
        if _is_lock_timeout_error(exc):
            logger.warning(
                "session_cap_lock_timeout",
                user_id=str(user_id),
                timeout_ms=_ADVISORY_LOCK_TIMEOUT_MS,
            )
            raise ServiceUnavailableError(
                detail="Servicio temporalmente ocupado, intenta de nuevo."
            ) from exc
        # Not a lock timeout — re-raise the original DBAPIError unchanged.
        raise


async def _create_refresh_token(
    user_id: UUID,
    db: AsyncSession,
    created_from_ip: str | None = None,
) -> str:
    """Genera un refresh token seguro, lo hashea y guarda en BD"""
    await _acquire_session_cap_lock(user_id, db)
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


async def _revoke_all_user_tokens_for_tenant(
    tenant_id: UUID,
    db: AsyncSession,
) -> None:
    """Revoca todos los refresh tokens activos de un tenant en una sola query"""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id.in_(
            select(User.id).where(User.tenant_id == tenant_id)
        ))
        .where(RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def login(
    email: str,
    password: str,
    db: AsyncSession,
    redis: Redis,
    request_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[TokenResponse, str]:
    """Autentica al usuario y delvuelve el access token + refresh token"""
    if not await check_redis_healthy(redis):
        raise ServiceUnavailableError()
    # Bootstrap RLS context: at login time we don't know the tenant yet, so we
    # temporarily elevate to superadmin to allow the email-based user lookup.
    # Mirrors the same pattern in app.dependencies.get_current_user.
    # The SET LOCAL is transaction-scoped and is reset on commit/rollback,
    # so it cannot leak across requests.
    await set_tenant_context(db, tenant_id=None, is_superadmin=True)
    await _check_account_lockout(email, redis)

    user, tenant = await _get_active_user(email, db)
    
    if not await verify_password_async(password, user.hashed_password):
        await _record_failed_attempt(email, redis)
        raise AuthError(
            status_code=401,
            detail="Credenciales incorrectas",
        )
    
    await _check_tenant_active(user, tenant)
    
    await _clear_login_attempts(email, redis)

    user.last_login_at = datetime.now(timezone.utc)

    access_token, jti = create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id) if user.tenant_id else None,
        role=user.role,
        is_superadmin=user.is_superadmin,
    )
    await track_jti(str(user.id), jti, redis)
    refresh_token = await _create_refresh_token(user.id, db, created_from_ip=request_ip)

    # Publish auth.login event (non-blocking on failure)
    try:
        event_bus = await get_event_bus()
        from app.event_schemas import AuthLoginEvent
        await event_bus.publish(AuthLoginEvent(
            event_id=uuid4(),
            tenant_id=user.tenant_id,
            user_id=str(user.id),
            email_hash=hash_email(user.email),
            ip_prefix=mask_ip(request_ip),
            user_agent=user_agent,
        ))
    except Exception:
        logger.warning("event_publish_failed", event_type="auth.login")

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
    if not await check_redis_healthy(redis):
        raise ServiceUnavailableError()
    # Bootstrap RLS context: refresh tokens are looked up by token_hash, not by
    # tenant, so we temporarily elevate to superadmin to allow the lookup.
    # Mirrors the login() pattern in this module and get_current_user in
    # app.dependencies. The SET LOCAL is transaction-scoped.
    await set_tenant_context(db, tenant_id=None, is_superadmin=True)
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    async def _rotate_refresh_token() -> tuple[User, str]:
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .where(RefreshToken.revoked_at.is_(None))
            .where(RefreshToken.expires_at > datetime.now(timezone.utc))
            .with_for_update(skip_locked=True)
        )
        record = await db.scalar(stmt)
        if not record:
            raise AuthError(
                status_code=401,
                detail="Refresh token invalido o expirado",
            )
        if record.revoked_at is not None:
            raise AuthError(
                status_code=401,
                detail="Refresh token invalido o expirado",
            )

        user, tenant = await _get_active_user_by_id(record.user_id, db)
        await _check_tenant_active(user, tenant)

        record.revoked_at = datetime.now(timezone.utc)
        new_refresh_token = await _create_refresh_token(
            user.id, db, created_from_ip=request_ip
        )
        return user, new_refresh_token

    if db.in_transaction():
        user, new_refresh_token = await _rotate_refresh_token()
    else:
        async with db.begin():
            user, new_refresh_token = await _rotate_refresh_token()
    
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
    if not await check_redis_healthy(redis):
        raise ServiceUnavailableError()
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
    if not await check_redis_healthy(redis):
        raise ServiceUnavailableError()
    user, _tenant = await _get_active_user_by_id(user_id, db)
    if not await verify_password_async(current_password, user.hashed_password):
        raise AuthError(
            status_code=400,
            detail="La contraseña actual es incorrecta.",
        )
    
    validate_password_length(new_password)
    user.hashed_password = await hash_password_async(new_password)
    
    await _revoke_all_user_tokens(user_id, db)
    
    await revoke_all_user_access_tokens(
        user_id=str(user_id),
        redis=redis,
        ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
