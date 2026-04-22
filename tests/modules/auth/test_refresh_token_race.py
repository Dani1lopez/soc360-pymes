from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient, ASGITransport, Response
from sqlalchemy import func, select, text, insert, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.core.security import hash_password
from app.dependencies import get_db, get_db_with_tenant
from app.main import create_app
from app.modules.auth.models import RefreshToken
from app.modules.tenants.models import Tenant
from app.modules.users.models import User
from tests.conftest import ADMIN_A_ID, TENANT_A_ID


def _hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def _login_and_get_refresh_token(client: AsyncClient) -> str:
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert login_response.status_code == 200
    refresh_token = login_response.cookies.get("refresh_token")
    assert refresh_token is not None
    return refresh_token


async def _refresh_with_cookie(client: AsyncClient, refresh_token: str) -> Response:
    return await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={refresh_token}"},
    )


async def _count_refresh_tokens(db_session: AsyncSession, user_id: UUID) -> int:
    return await db_session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user_id)
    ) or 0


async def _count_active_refresh_tokens(db_session: AsyncSession, user_id: UUID) -> int:
    return await db_session.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .where(RefreshToken.revoked_at.is_(None))
        .where(RefreshToken.expires_at > datetime.now(timezone.utc))
    ) or 0


async def _get_refresh_record(db_session: AsyncSession, raw_token: str) -> RefreshToken | None:
    return await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh_token(raw_token))
    )


ADMIN_A_EMAIL = "admin@alpha.test"
ADMIN_A_PASSWORD = "AdminAlpha123!"


async def _ensure_user_exists(db: AsyncSession) -> None:
    """Seed tenant + user if not present (idempotent, conflict-safe)."""
    tenant_exists = await db.scalar(
        select(func.count()).select_from(Tenant).where(Tenant.id == UUID(TENANT_A_ID))
    )
    if not tenant_exists:
        await db.execute(
            pg_insert(Tenant).values(
                id=UUID(TENANT_A_ID), name="Empresa Alpha", slug="empresa-alpha",
                plan="starter", is_active=True, max_assets=50,
            ).on_conflict_do_nothing(index_elements=["id"])
        )
        await db.flush()

    user_exists = await db.scalar(
        select(func.count()).select_from(User).where(User.id == UUID(ADMIN_A_ID))
    )
    if not user_exists:
        await db.execute(text("SET LOCAL app.is_superadmin = 'true'"))
        await db.execute(
            pg_insert(User).values(
                id=UUID(ADMIN_A_ID), tenant_id=UUID(TENANT_A_ID),
                email=ADMIN_A_EMAIL, hashed_password=hash_password(ADMIN_A_PASSWORD),
                full_name="Admin Alpha", role="admin", is_active=True, is_superadmin=False,
            ).on_conflict_do_nothing(index_elements=["id"])
        )
        await db.flush()


def _make_client_with_session(
    session_factory: Callable[[], AsyncSession],
) -> AsyncClient:
    """Create an AsyncClient whose requests use a fresh DB session.

    Each call produces a client backed by its own AsyncSession, which gets
    a separate DB connection from the pooled engine. This is required to
    prove real concurrency rather than shared-session fake concurrency.
    """
    app = create_app()
    fake_redis = FakeRedis()
    _session = session_factory()

    async def _override_get_db():
        async with _session.begin():
            yield _session

    async def _override_get_db_with_tenant():
        async with _session.begin():
            yield _session

    async def _override_get_redis():
        yield fake_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_db_with_tenant] = _override_get_db_with_tenant
    app.dependency_overrides[get_redis] = _override_get_redis

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


async def test_refresh_token_concurrent_race(isolated_db_session):
    """Two concurrent refresh requests with same token → exactly 1 succeeds.

    Uses isolated DB sessions per request (via pooled engine) to prove real
    concurrency. The shared client/db_session fixture fakes concurrency by
    routing all requests through a single NullPool connection.
    """
    user_id = UUID(ADMIN_A_ID)

    # Seed user (committed so login queries can find it)
    seed = isolated_db_session()
    async with seed.begin():
        await _ensure_user_exists(seed)
        await seed.commit()

    # Login to obtain a refresh token
    login_client = _make_client_with_session(isolated_db_session)
    async with login_client:
        refresh_token = await _login_and_get_refresh_token(login_client)

    # Two concurrent refresh requests, each with its own DB session/connection
    async def _do_refresh() -> Response:
        client = _make_client_with_session(isolated_db_session)
        async with client:
            return await _refresh_with_cookie(client, refresh_token)

    responses = await asyncio.gather(_do_refresh(), _do_refresh())

    successful = [r for r in responses if r.status_code == 200]
    unauthorized = [r for r in responses if r.status_code == 401]

    assert len(successful) == 1, f"Expected 1 success, got {len(successful)}: {[r.status_code for r in responses]}"
    assert len(unauthorized) == 1, f"Expected 1 unauthorized, got {len(unauthorized)}"

    # Verify final state: login token + rotated token = 2 total, 1 active
    verify = isolated_db_session()
    async with verify.begin():
        after_total = await _count_refresh_tokens(verify, user_id)
        after_active = await _count_active_refresh_tokens(verify, user_id)

    assert after_total == 2, f"Expected 2 total tokens (login + rotated), got {after_total}"
    assert after_active == 1, f"Expected 1 active token, got {after_active}"


async def test_refresh_token_revoked_after_lock(client: AsyncClient, seed_data, db_session: AsyncSession):
    refresh_token = await _login_and_get_refresh_token(client)
    user_id = UUID(ADMIN_A_ID)
    before_total = await _count_refresh_tokens(db_session, user_id)

    record = await _get_refresh_record(db_session, refresh_token)
    assert record is not None
    record.revoked_at = datetime.now(timezone.utc)
    await db_session.flush()

    response = await _refresh_with_cookie(client, refresh_token)

    assert response.status_code == 401
    assert await _count_refresh_tokens(db_session, user_id) == before_total


async def test_refresh_token_expired(client: AsyncClient, seed_data, db_session: AsyncSession):
    refresh_token = await _login_and_get_refresh_token(client)
    user_id = UUID(ADMIN_A_ID)
    before_total = await _count_refresh_tokens(db_session, user_id)

    record = await _get_refresh_record(db_session, refresh_token)
    assert record is not None
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    response = await _refresh_with_cookie(client, refresh_token)

    assert response.status_code == 401
    assert await _count_refresh_tokens(db_session, user_id) == before_total


async def test_refresh_token_happy_path_preserved(client: AsyncClient, seed_data, db_session: AsyncSession):
    user_id = UUID(ADMIN_A_ID)

    # Clean up any leftover tokens from concurrency tests that committed data
    await db_session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db_session.flush()

    old_refresh_token = await _login_and_get_refresh_token(client)
    before_total = await _count_refresh_tokens(db_session, user_id)

    response = await _refresh_with_cookie(client, old_refresh_token)

    assert response.status_code == 200
    assert "access_token" in response.json()
    new_refresh_token = response.cookies.get("refresh_token")
    assert new_refresh_token is not None
    assert new_refresh_token != old_refresh_token

    old_record = await _get_refresh_record(db_session, old_refresh_token)
    assert old_record is not None
    assert old_record.revoked_at is not None

    assert await _count_refresh_tokens(db_session, user_id) == before_total + 1
    assert await _count_active_refresh_tokens(db_session, user_id) == 1
