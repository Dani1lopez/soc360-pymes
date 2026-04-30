from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Request, Response

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import decode_access_token
from app.dependencies import DBDep, RedisDep, CurrentUserDep
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
)
from app.modules.auth import service


REFRESH_COOKIE_NAME = "refresh_token"

router = APIRouter(prefix="/auth", tags=["auth"])


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
) -> TokenResponse:
    try:
        user_agent = request.headers.get("user-agent")
        token_response, refresh_token = await service.login(
            email=body.email,
            password=body.password,
            request_ip=request.client.host if request.client else None,
            user_agent=user_agent,
            db=db,
            redis=redis,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    _set_refresh_cookie(response, refresh_token)
    return token_response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: DBDep,
    redis: RedisDep,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")

    # Extraer JTI viejo del access token si existe (no es requerido)
    old_jti = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:]
            payload = decode_access_token(token)
            old_jti = payload.get("jti")
        except Exception:
            pass  # token inválido o expirado — no importa, no podemos removerlo

    try:
        token_response, new_refresh = await service.refresh_tokens(
            refresh_token=refresh_token,
            old_jti=old_jti,
            db=db,
            redis=redis,
            request_ip=request.client.host if request.client else None,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    _set_refresh_cookie(response, new_refresh)
    return token_response


@router.post("/logout", status_code=200)
async def logout(
    response: Response,
    db: DBDep,
    redis: RedisDep,
    current_user: CurrentUserDep,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> dict:
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
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    _clear_refresh_cookie(response)
    return {"detail": "Sesion cerrada correctamente"}


@router.post("/change-password", status_code=200)
async def change_password(
    body: ChangePasswordRequest,
    response: Response,
    db: DBDep,
    redis: RedisDep,
    current_user: CurrentUserDep,
) -> dict:
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
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    _clear_refresh_cookie(response)
    return {"detail": "Contraseña actualizada. Inicia sesion de nuevo"}
