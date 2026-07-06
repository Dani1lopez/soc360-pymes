from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from jwt import InvalidTokenError

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.rate_limit import RateLimiter
from app.core.security import decode_access_token
from app.dependencies import DBDep, RedisDep, CurrentUserDep
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
)
from app.modules.auth import service

logger = get_logger(__name__)

REFRESH_COOKIE_NAME = "refresh_token"

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind trusted proxies."""
    if settings.TRUSTED_PROXIES and request.client:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded and request.client.host in settings.TRUSTED_PROXIES:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _get_rate_limiter(redis: RedisDep) -> RateLimiter:
    """Dependency: return a RateLimiter instance."""
    return RateLimiter(redis)


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.ENVIRONMENT != "development",
        samesite="strict",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DBDep,
    redis: RedisDep,
    rate_limiter: RateLimiter = Depends(_get_rate_limiter),
) -> TokenResponse:
    ip = _get_client_ip(request)

    # Check rate limit before attempting login
    # Returns 401 (not 429) to maintain enumeration resistance —
    # attacker can't distinguish between wrong password, unknown user, and rate limit.
    # Fail-open: if Redis is down, skip rate limiting and let auth proceed.
    if settings.RATE_LIMIT_ENABLED:
        try:
            status = await rate_limiter.check(ip, body.email)
            if status.is_locked:
                logger.warning("login_rate_limited", ip=ip, email=body.email[:3] + "***")
                raise HTTPException(
                    status_code=401,
                    detail="Credenciales incorrectas",
                )
        except HTTPException:
            raise
        except Exception:
            logger.warning("rate_limit_check_failed", reason="redis_error", ip=ip)

    try:
        user_agent = request.headers.get("user-agent")
        token_response, refresh_token = await service.login(
            email=body.email,
            password=body.password,
            request_ip=ip,
            user_agent=user_agent,
            db=db,
            redis=redis,
        )
    except AppError as exc:
        # Record failure on auth error (wrong password, user not found, etc.)
        if settings.RATE_LIMIT_ENABLED:
            try:
                await rate_limiter.record_failure(ip, body.email)
            except Exception:
                logger.warning("rate_limit_record_failed", reason="redis_error", ip=ip)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    # Success — reset failure counters
    if settings.RATE_LIMIT_ENABLED:
        try:
            await rate_limiter.record_success(ip, body.email)
        except Exception:
            logger.warning("rate_limit_reset_failed", reason="redis_error", ip=ip)

    _set_refresh_cookie(response, refresh_token)
    return token_response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: DBDep,
    redis: RedisDep,
    rate_limiter: RateLimiter = Depends(_get_rate_limiter),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")

    ip = _get_client_ip(request)

    # Check rate limit by IP only (no email available in refresh requests)
    # Fail-open: if Redis is down, skip rate limiting.
    if settings.RATE_LIMIT_ENABLED:
        try:
            status = await rate_limiter.check(ip, f"refresh:{ip}")
            if status.is_locked:
                logger.warning("refresh_rate_limited", ip=ip)
                raise HTTPException(
                    status_code=429,
                    detail="Demasiados intentos. Intenta más tarde.",
                )
        except HTTPException:
            raise
        except Exception:
            logger.warning("rate_limit_check_failed", reason="redis_error", ip=ip)

    # Extraer JTI viejo del access token si existe (no es requerido)
    old_jti = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:]
            payload = decode_access_token(token)
            old_jti = payload.get("jti")
        except InvalidTokenError:
            pass  # token inválido o expirado — no importa, no podemos removerlo

    try:
        token_response, new_refresh = await service.refresh_tokens(
            refresh_token=refresh_token,
            old_jti=old_jti,
            db=db,
            redis=redis,
            request_ip=ip,
        )
    except AppError as exc:
        # Record failure on refresh error
        if settings.RATE_LIMIT_ENABLED:
            try:
                await rate_limiter.record_failure(ip, f"refresh:{ip}")
            except Exception:
                logger.warning("rate_limit_record_failed", reason="redis_error", ip=ip)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    # Success — reset failure counters
    if settings.RATE_LIMIT_ENABLED:
        try:
            await rate_limiter.record_success(ip, f"refresh:{ip}")
        except Exception:
            logger.warning("rate_limit_reset_failed", reason="redis_error", ip=ip)

    _set_refresh_cookie(response, new_refresh)
    return token_response


@router.post("/logout", status_code=200)
async def logout(
    request: Request,
    response: Response,
    db: DBDep,
    redis: RedisDep,
    current_user: CurrentUserDep,
    rate_limiter: RateLimiter = Depends(_get_rate_limiter),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> dict:
    ip = _get_client_ip(request)

    # Check rate limit — fail-open if Redis is down
    if settings.RATE_LIMIT_ENABLED:
        try:
            status = await rate_limiter.check(ip, f"logout:{current_user.id}")
            if status.is_locked:
                logger.warning("logout_rate_limited", ip=ip, user_id=str(current_user.id))
                raise HTTPException(
                    status_code=429,
                    detail="Demasiados intentos. Intenta más tarde.",
                )
        except HTTPException:
            raise
        except Exception:
            logger.warning("rate_limit_check_failed", reason="redis_error", ip=ip)

    try:
        await service.logout(
            jti=current_user.current_jti,  # type: ignore[attr-defined]
            # Si no hay cookie, solo revocamos el access token (jti)
            refresh_token=refresh_token or "",
            user_id=str(current_user.id),
            db=db,
            redis=redis,
        )
    except AppError as exc:
        if settings.RATE_LIMIT_ENABLED:
            try:
                await rate_limiter.record_failure(ip, f"logout:{current_user.id}")
            except Exception:
                logger.warning("rate_limit_record_failed", reason="redis_error", ip=ip)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    _clear_refresh_cookie(response)
    return {"detail": "Sesion cerrada correctamente"}


@router.post("/change-password", status_code=200)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: DBDep,
    redis: RedisDep,
    current_user: CurrentUserDep,
    rate_limiter: RateLimiter = Depends(_get_rate_limiter),
) -> dict:
    ip = _get_client_ip(request)

    # Check rate limit — fail-open if Redis is down
    if settings.RATE_LIMIT_ENABLED:
        try:
            status = await rate_limiter.check(ip, f"change-password:{current_user.id}")
            if status.is_locked:
                logger.warning("change_password_rate_limited", ip=ip, user_id=str(current_user.id))
                raise HTTPException(
                    status_code=429,
                    detail="Demasiados intentos. Intenta más tarde.",
                )
        except HTTPException:
            raise
        except Exception:
            logger.warning("rate_limit_check_failed", reason="redis_error", ip=ip)

    try:
        await service.change_password(
            user_id=current_user.id,
            current_password=body.current_password,
            new_password=body.new_password,
            current_jti=current_user.current_jti, # type: ignore[attr-defined]
            db=db,
            redis=redis,
        )
    except AppError as exc:
        if settings.RATE_LIMIT_ENABLED:
            try:
                await rate_limiter.record_failure(ip, f"change-password:{current_user.id}")
            except Exception:
                logger.warning("rate_limit_record_failed", reason="redis_error", ip=ip)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    _clear_refresh_cookie(response)
    return {"detail": "Contraseña actualizada. Inicia sesion de nuevo"}
