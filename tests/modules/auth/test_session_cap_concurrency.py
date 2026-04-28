from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient, ASGITransport
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import Base
from app.core.redis import get_redis
from app.core.security import hash_password
from app.dependencies import get_db, get_db_with_tenant
from app.main import create_app
from app.modules.auth.models import RefreshToken
from app.modules.auth.service import MAX_ACTIVE_SESSIONS
from app.modules.tenants.models import Tenant
from app.modules.users.models import User
from tests.conftest import (
    ADMIN_A_ID,
    TENANT_A_ID,
    TEST_DATABASE_URL,
)

ADMIN_A_EMAIL = "admin@alpha.test"
ADMIN_A_PASSWORD = "AdminAlpha123!"


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _count_active(db: AsyncSession, user_id: UUID) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .where(RefreshToken.revoked_at.is_(None))
        .where(RefreshToken.expires_at > datetime.now(timezone.utc))
    ) or 0


async def _ensure_user_exists(db: AsyncSession) -> None:
    """Seed tenant + user if not present (idempotent for concurrency tests)."""
    exists = await db.scalar(
        select(func.count()).select_from(User).where(User.id == UUID(ADMIN_A_ID))
    )
    if exists:
        return

    tenant = Tenant(
        id=UUID(TENANT_A_ID), name="Empresa Alpha", slug="empresa-alpha",
        plan="starter", is_active=True, max_assets=50,
    )
    user = User(
        id=UUID(ADMIN_A_ID), tenant_id=UUID(TENANT_A_ID),
        email=ADMIN_A_EMAIL, hashed_password=hash_password(ADMIN_A_PASSWORD),
        full_name="Admin Alpha", role="admin", is_active=True, is_superadmin=False,
    )
    await db.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    db.add(tenant)
    await db.flush()
    db.add(user)
    await db.flush()


async def _cleanup_user_tokens(db: AsyncSession, user_id: UUID) -> None:
    """Revoke all refresh tokens for a user to ensure clean test state."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.flush()


async def _seed_active_tokens(
    db: AsyncSession, user_id: UUID, count: int
) -> list[str]:
    """Insert `count` active refresh tokens and return raw token strings."""
    tokens: list[str] = []
    for i in range(count):
        raw = f"seed_{user_id}_{i}_{datetime.now(timezone.utc).isoformat()}"
        db.add(RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ))
        tokens.append(raw)
    await db.flush()
    return tokens


async def _login_via_client(client: AsyncClient) -> str | None:
    """POST /login and return the refresh_token cookie value."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.cookies.get("refresh_token")


def _make_client_with_session(
    session_factory: Callable[[], AsyncSession],
) -> AsyncClient:
    """Create an AsyncClient whose /auth requests use a fresh DB session."""
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


@pytest.mark.asyncio
async def test_session_cap_burst_from_zero_active(isolated_db_session):
    """6 parallel logins from 0 active sessions → exactly 5 active after."""
    user_id = UUID(ADMIN_A_ID)

    # Seed user (committed so login queries can find it)
    seed = isolated_db_session()
    async with seed.begin():
        await _ensure_user_exists(seed)
        await _cleanup_user_tokens(seed, user_id)
        await seed.commit()

    # Verify starting state: 0 active
    verify = isolated_db_session()
    async with verify.begin():
        start_count = await _count_active(verify, user_id)
    assert start_count == 0, f"Expected 0 active, got {start_count}"

    # Fire 6 parallel logins, each with its own DB session
    async def _do_login():
        client = _make_client_with_session(isolated_db_session)
        async with client:
            return await _login_via_client(client)

    results = await asyncio.gather(*[_do_login() for _ in range(6)])
    assert all(r is not None for r in results), "All logins should succeed"

    # Verify final state: exactly MAX_ACTIVE_SESSIONS
    check = isolated_db_session()
    async with check.begin():
        final_count = await _count_active(check, user_id)
    assert final_count == MAX_ACTIVE_SESSIONS, (
        f"Expected {MAX_ACTIVE_SESSIONS} active sessions, got {final_count}"
    )


@pytest.mark.asyncio
async def test_session_cap_burst_from_four_active(isolated_db_session):
    """6 parallel logins from 4 active sessions → exactly 5 active after."""
    user_id = UUID(ADMIN_A_ID)

    # Seed user + 4 active tokens (committed)
    seed = isolated_db_session()
    async with seed.begin():
        await _ensure_user_exists(seed)
        await _cleanup_user_tokens(seed, user_id)
        await _seed_active_tokens(seed, user_id, 4)
        await seed.commit()

    # Fire 6 parallel logins
    async def _do_login():
        client = _make_client_with_session(isolated_db_session)
        async with client:
            return await _login_via_client(client)

    results = await asyncio.gather(*[_do_login() for _ in range(6)])
    assert all(r is not None for r in results)

    # Verify: exactly 5
    check = isolated_db_session()
    async with check.begin():
        final_count = await _count_active(check, user_id)
    assert final_count == MAX_ACTIVE_SESSIONS, (
        f"Expected {MAX_ACTIVE_SESSIONS} active sessions, got {final_count}"
    )


@pytest.mark.asyncio
async def test_session_cap_burst_from_five_active(isolated_db_session):
    """6 parallel logins from 5 active sessions → exactly 5 active after."""
    user_id = UUID(ADMIN_A_ID)

    # Seed user + 5 active tokens (committed)
    seed = isolated_db_session()
    async with seed.begin():
        await _ensure_user_exists(seed)
        await _cleanup_user_tokens(seed, user_id)
        await _seed_active_tokens(seed, user_id, 5)
        await seed.commit()

    # Fire 6 parallel logins
    async def _do_login():
        client = _make_client_with_session(isolated_db_session)
        async with client:
            return await _login_via_client(client)

    results = await asyncio.gather(*[_do_login() for _ in range(6)])
    assert all(r is not None for r in results)

    # Verify: exactly 5
    check = isolated_db_session()
    async with check.begin():
        final_count = await _count_active(check, user_id)
    assert final_count == MAX_ACTIVE_SESSIONS, (
        f"Expected {MAX_ACTIVE_SESSIONS} active sessions, got {final_count}"
    )
