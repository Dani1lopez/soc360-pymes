from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient, ASGITransport, Response
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.core.security import decode_access_token, hash_password
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
    await db_session.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    return await db_session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user_id)
    ) or 0


async def _count_active_refresh_tokens(db_session: AsyncSession, user_id: UUID) -> int:
    await db_session.execute(text("SET LOCAL app.is_superadmin = 'true'"))
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
    """Seed tenant + user if not present (idempotent, conflict-safe).

    Runs under superadmin context so the RLS WITH CHECK on `tenants` (and the
    refresh_tokens/users policies) do not reject test bookkeeping writes.
    """
    await db.execute(text("SET LOCAL app.is_superadmin = 'true'"))
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
    *,
    redis: FakeRedis | None = None,
) -> AsyncClient:
    """Create an AsyncClient whose requests use a fresh DB session.

    Each call produces a client backed by its own AsyncSession, which gets
    a separate DB connection from the pooled engine. This is required to
    prove real concurrency rather than shared-session fake concurrency.

    Pass ``redis=`` to share one FakeRedis between several clients so a
    request on one client can observe Redis side effects made by another.
    """
    app = create_app()
    fake_redis = redis if redis is not None else FakeRedis()
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

    # Seed user (committed so login queries can find it) and hard-DELETE any
    # pre-existing refresh tokens for this user. The hard DELETE (not revoke)
    # is required because `after_total` counts ALL rows including revoked
    # ones; without this, prior tests (e.g. session_cap) that committed
    # tokens for the same user would pollute the absolute-count assertion.
    seed = isolated_db_session()
    async with seed.begin():
        await _ensure_user_exists(seed)
        await seed.execute(text("SET LOCAL app.is_superadmin = 'true'"))
        await seed.execute(
            text("DELETE FROM refresh_tokens WHERE user_id = :uid"),
            {"uid": user_id},
        )
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

    # Verify final state: login token + rotated token = 2 total. Under the
    # approved L5 contract (no grace period) the losing concurrent R1 is a
    # replay: it revokes the whole family, so 0 tokens remain active.
    verify = isolated_db_session()
    async with verify.begin():
        after_total = await _count_refresh_tokens(verify, user_id)
        after_active = await _count_active_refresh_tokens(verify, user_id)

    assert after_total == 2, f"Expected 2 total tokens (login + rotated), got {after_total}"
    assert after_active == 0, f"Expected 0 active tokens after replay revocation, got {after_active}"

    # The winner's fresh credentials are dead too: the replay revoked the
    # family, so its refresh cookie and its access JWT are both rejected.
    winner = successful[0]
    winner_access = winner.json()["access_token"]
    winner_refresh = winner.cookies.get("refresh_token")
    assert winner_refresh is not None, "winner must have received a rotated cookie"

    winner_client = _make_client_with_session(isolated_db_session)
    async with winner_client:
        me = await winner_client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {winner_access}"},
        )
        assert me.status_code == 401, (
            "winner's access JWT must be rejected after the replay revocation"
        )
        winner_refresh_response = await _refresh_with_cookie(winner_client, winner_refresh)
    assert winner_refresh_response.status_code == 401, (
        "winner's rotated refresh cookie must be rejected after the replay revocation"
    )


async def test_replay_cleanup_preserves_jwt_tracked_after_replay_commit(isolated_db_session):
    """The post-commit Redis cleanup of a replay must not touch newer JWTs.

    The replay's revocation commit releases the per-user advisory lock, so a
    concurrent login can track a NEW current-version JWT between the commit
    and the Redis cleanup. That cleanup captured the prior JTIs while the
    lock was held and must denylist/SREM ONLY those members: the newer JWT
    must keep working on /api/v1/users/me and stay in ``active_jtis``.
    """
    user_id = UUID(ADMIN_A_ID)
    shared_redis = FakeRedis()

    # Seed user (committed) and hard-DELETE any pre-existing refresh tokens.
    seed = isolated_db_session()
    async with seed.begin():
        await _ensure_user_exists(seed)
        await seed.execute(text("SET LOCAL app.is_superadmin = 'true'"))
        await seed.execute(
            text("DELETE FROM refresh_tokens WHERE user_id = :uid"),
            {"uid": user_id},
        )
        await seed.commit()

    login_client = _make_client_with_session(isolated_db_session, redis=shared_redis)
    async with login_client:
        login_response = await login_client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
        )
        assert login_response.status_code == 200, login_response.text
        old_access = login_response.json()["access_token"]
        replay_token = login_response.cookies.get("refresh_token")
        assert replay_token is not None

    # Rotate R1 -> R2 with a normal client so re-presenting R1 is a replay.
    rotation_client = _make_client_with_session(isolated_db_session, redis=shared_redis)
    async with rotation_client:
        rotated = await _refresh_with_cookie(rotation_client, replay_token)
        assert rotated.status_code == 200, rotated.text

    # The replay session's commit pauses right after confirming: the advisory
    # lock is released but the Redis cleanup has not run yet.
    replay_session = isolated_db_session()
    committed = asyncio.Event()
    release = asyncio.Event()
    original_commit = replay_session.commit

    async def _pausing_commit():
        await original_commit()
        committed.set()
        await release.wait()

    replay_session.commit = _pausing_commit  # type: ignore[method-assign]

    async def _do_replay() -> Response:
        replay_client = _make_client_with_session(
            lambda: replay_session, redis=shared_redis
        )
        async with replay_client:
            return await _refresh_with_cookie(replay_client, replay_token)

    replay_task = asyncio.create_task(_do_replay())
    await asyncio.wait_for(committed.wait(), timeout=10)

    # A fresh login DURING the pause: it acquires the just-released lock,
    # mints a current-version JWT and tracks its JTI after the snapshot.
    concurrent_client = _make_client_with_session(isolated_db_session, redis=shared_redis)
    async with concurrent_client:
        concurrent_login = await concurrent_client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
        )
        assert concurrent_login.status_code == 200, concurrent_login.text
        new_access = concurrent_login.json()["access_token"]

        release.set()
        replay_response = await asyncio.wait_for(replay_task, timeout=10)
        assert replay_response.status_code == 401

        new_jti = decode_access_token(new_access)["jti"]
        old_jti = decode_access_token(old_access)["jti"]

        # The new JWT still authenticates and stays tracked; the prior one is
        # denylisted and untracked.
        me_new = await concurrent_client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {new_access}"},
        )
        assert me_new.status_code == 200, (
            "JWT tracked after the replay commit must survive the cleanup: "
            f"got {me_new.status_code} {me_new.text}"
        )
        me_old = await concurrent_client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {old_access}"},
        )
        assert me_old.status_code == 401

        tracked = {
            m.decode() if isinstance(m, bytes) else m
            for m in await shared_redis.smembers(f"active_jtis:{user_id}")
        }
        assert new_jti in tracked, "newer login's JTI must remain in active_jtis"
        assert old_jti not in tracked, "prior JTI must be untracked"
        assert await shared_redis.exists(f"revoked:{old_jti}") == 1
        assert await shared_redis.exists(f"revoked:{new_jti}") == 0


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
