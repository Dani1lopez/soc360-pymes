"""Defensive contract for replayed rotated refresh tokens (S1-S4).

The suite is deliberately non-adversarial: it drives the same public HTTP path
a browser would (login -> refresh -> re-present the previous cookie) and only
asserts the defensive side effects on storage and on the Redis denylist.

Transaction fidelity matters here. The ``client`` fixture yields the test
session without a transaction boundary, so a write made before a 401 would look
persisted even when production rolls it back. ``production_tx_client`` wraps the
same session in ``async with session.begin()`` — the shape of ``get_db`` in
``app/core/database.py`` — so a missing commit is visible as missing state.
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.dependencies import get_db, get_db_with_tenant
from app.main import create_app
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User
from tests.conftest import ADMIN_A_ID

ADMIN_A_EMAIL = "admin@alpha.test"
ADMIN_A_PASSWORD = "AdminAlpha123!"
REFRESH_INVALID_DETAIL = "Refresh token invalido o expirado"


def _hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


REFRESH_COOKIE_NAME = "refresh_token"


def _refresh_cookie_header(raw_token: str) -> dict[str, str]:
    return {"Cookie": REFRESH_COOKIE_NAME + "=" + raw_token}


@pytest_asyncio.fixture
async def production_tx_client(db_session: AsyncSession):
    """Client whose DB dependency mirrors production ``get_db``.

    Requests reuse the fixture session, but scoped in a session transaction:
    an application commit releases the scope (state survives for the
    assertions) while an exception without a commit rolls it back (state
    disappears). That is exactly what production does.

    The scope is a plain ``session.begin()`` when the session is idle and a
    savepoint when the test's own probe queries already autobegun one —
    ``session.begin()`` is illegal in that case and a request must not depend
    on the test having probed the DB yet.
    """
    app = create_app()
    fake_redis = FakeRedis(decode_responses=True)

    @asynccontextmanager
    async def _request_transaction():
        if db_session.in_transaction():
            async with db_session.begin_nested():
                yield db_session
        else:
            async with db_session.begin():
                yield db_session

    async def _override_get_db():
        async with _request_transaction():
            yield db_session

    async def _override_get_db_with_tenant():
        async with _request_transaction():
            yield db_session

    async def _override_get_redis():
        yield fake_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_db_with_tenant] = _override_get_db_with_tenant
    app.dependency_overrides[get_redis] = _override_get_redis

    # Keep the login event publish off the real Redis pool (same reason as the
    # shared ``client`` fixture) and restore the module wrapper afterwards.
    import app.modules.auth.service as _auth_service
    from app.event_bus import EventBus as _EventBus

    _original_get_event_bus = _auth_service.get_event_bus
    _bus = _EventBus(fake_redis)

    async def _fake_get_event_bus() -> _EventBus:
        return _bus

    _auth_service.get_event_bus = _fake_get_event_bus
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client, fake_redis
    finally:
        _auth_service.get_event_bus = _original_get_event_bus


async def _release_fixture_savepoint(db: AsyncSession) -> None:
    """End the seed transaction so requests can open their own savepoint."""
    if db.in_transaction():
        await db.commit()


async def _login(client: AsyncClient, *, email: str = ADMIN_A_EMAIL) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": ADMIN_A_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = response.cookies.get("refresh_token")
    assert token is not None, "login must issue a refresh token"
    return token


async def _refresh(client: AsyncClient, raw_token: str):
    client.cookies.clear()
    return await client.post(
        "/api/v1/auth/refresh",
        headers=_refresh_cookie_header(raw_token),
    )


async def _record(db: AsyncSession, raw_token: str) -> RefreshToken | None:
    await db.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    return await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == _hash_refresh_token(raw_token)
        )
    )


async def _family_rows(db: AsyncSession, family_id: UUID) -> list[RefreshToken]:
    await db.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    rows = await db.scalars(
        select(RefreshToken)
        .where(RefreshToken.family_id == family_id)
        .order_by(RefreshToken.created_at.asc())
    )
    return list(rows)


async def _active_count(db: AsyncSession, user_id: UUID) -> int:
    await db.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    return (
        await db.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .where(RefreshToken.expires_at > datetime.now(timezone.utc))
        )
        or 0
    )


async def _active_jtis(redis: FakeRedis, user_id: str) -> set[str]:
    members = await redis.smembers(f"active_jtis:{user_id}")
    return {m.decode() if isinstance(m, bytes) else m for m in members}


async def _credential_version(db: AsyncSession) -> int:
    await db.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    return (
        await db.scalar(
            select(User.credential_version).where(User.id == UUID(ADMIN_A_ID))
        )
        or 0
    )


async def _reset_credential_version(db: AsyncSession) -> None:
    """Pin ADMIN_A's committed credential_version to 0.

    Other tests in the suite (e.g. the concurrent race) commit a version
    bump; these tests must not depend on execution order.
    """
    await db.execute(
        update(User).where(User.id == UUID(ADMIN_A_ID)).values(credential_version=0)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# S4 — the two persisted data points exist and are wired
# ---------------------------------------------------------------------------


async def test_migration_persists_family_and_rotation_state(db_session: AsyncSession):
    """S4: one migration adds the family and the explicit rotation marker."""
    await db_session.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    columns = dict(
        (
            await db_session.execute(
                text(
                    "SELECT column_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'refresh_tokens' "
                    "AND column_name IN ('family_id', 'rotated_to_id')"
                )
            )
        ).all()
    )
    assert columns == {"family_id": "NO", "rotated_to_id": "YES"}

    family_default = (
        await db_session.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'refresh_tokens' "
                "AND column_name = 'family_id'"
            )
        )
    ).scalar_one()
    assert (
        "gen_random_uuid()" in family_default
    ), "legacy inserts that omit family_id must still get a family"

    index_names = set(
        (
            await db_session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'refresh_tokens'"
                )
            )
        ).scalars()
    )
    assert "ix_refresh_tokens_family_id" in index_names

    fk = (
        await db_session.execute(
            text(
                "SELECT confdeltype::text FROM pg_constraint "
                "WHERE conname = 'fk_refresh_tokens_rotated_to_id'"
            )
        )
    ).scalar_one()
    assert fk == "n", (
        "rotated_to_id is ON DELETE SET NULL: deleting the successor row "
        "erases the rotation marker (the family link stays usable for S2)"
    )


async def test_legacy_insert_without_rotation_context_still_works(
    db_session: AsyncSession, seed_data
):
    """S4/legacy: rows inserted without a rotation context get their own family.

    Scripts, fixtures and any pre-migration writer insert refresh tokens
    without knowing about reuse detection. The columns stay usable for them:
    ``family_id`` is generated per row and ``rotated_to_id`` stays NULL, so a
    historical row is never mistaken for a replayed token.
    """
    await db_session.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    for token_hash in ("legacy-token-a", "legacy-token-b"):
        await db_session.execute(
            insert(RefreshToken).values(
                user_id=UUID(ADMIN_A_ID),
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )

    rows = list(
        await db_session.scalars(
            select(RefreshToken)
            .where(RefreshToken.token_hash.in_(("legacy-token-a", "legacy-token-b")))
            .order_by(RefreshToken.token_hash.asc())
        )
    )
    assert len(rows) == 2
    assert all(row.family_id is not None for row in rows)
    assert rows[0].family_id != rows[1].family_id, "each legacy row is its own family"
    assert all(row.rotated_to_id is None for row in rows)


# ---------------------------------------------------------------------------
# S1 + S2 — normal rotation, then a replayed rotated token
# ---------------------------------------------------------------------------


async def test_rotation_links_family_and_rotation_state(
    production_tx_client, db_session: AsyncSession, seed_data
):
    """S1/S4: a valid rotation keeps the family and records the successor."""
    client, _redis = production_tx_client
    await _release_fixture_savepoint(db_session)

    first = await _login(client)
    rotated = await _refresh(client, first)
    assert rotated.status_code == 200, rotated.text
    second = rotated.cookies.get("refresh_token")
    assert second is not None and second != first

    first_record = await _record(db_session, first)
    second_record = await _record(db_session, second)
    assert first_record is not None and second_record is not None
    assert first_record.revoked_at is not None
    assert first_record.rotated_to_id == second_record.id
    assert second_record.rotated_to_id is None
    assert second_record.family_id == first_record.family_id
    assert second_record.revoked_at is None


async def test_replayed_rotated_token_revokes_family_and_access_tokens(
    production_tx_client, db_session: AsyncSession, seed_data
):
    """S2: replaying R1 answers 401, issues no token, and revokes the session."""
    client, fake_redis = production_tx_client
    await _release_fixture_savepoint(db_session)

    first = await _login(client)
    rotated = await _refresh(client, first)
    assert rotated.status_code == 200, rotated.text
    second = rotated.cookies.get("refresh_token")
    assert second is not None

    first_record = await _record(db_session, first)
    assert first_record is not None
    family_id = first_record.family_id
    assert await _record(db_session, second) is not None
    jtis_before = await _active_jtis(fake_redis, ADMIN_A_ID)
    assert jtis_before, "the session must have a tracked access-token jti"

    replay = await _refresh(client, first)

    assert replay.status_code == 401
    assert replay.json()["detail"] == REFRESH_INVALID_DETAIL
    assert "access_token" not in replay.json()
    assert replay.cookies.get("refresh_token") is None

    # Persisted even though the request ended in a 401 (commit before raise).
    family = await _family_rows(db_session, family_id)
    assert len(family) == 2, [row.token_hash for row in family]
    assert all(
        row.revoked_at is not None for row in family
    ), "every refresh token of the replayed family must be revoked"

    # Access tokens of that user are denylisted through the Redis helper.
    assert await _active_jtis(fake_redis, ADMIN_A_ID) == set()
    for jti in jtis_before:
        assert await fake_redis.exists(f"revoked:{jti}") == 1

    # The rotated successor can no longer renew: the family is dead.
    successor = await _refresh(client, second)
    assert successor.status_code == 401


# ---------------------------------------------------------------------------
# S3 — unknown and non-rotated rejections revoke nothing
# ---------------------------------------------------------------------------


async def test_unknown_refresh_token_rejects_without_revoking_sessions(
    production_tx_client, db_session: AsyncSession, seed_data
):
    """S3: an unknown token is 401 and does not touch other sessions."""
    client, fake_redis = production_tx_client
    await _release_fixture_savepoint(db_session)

    user_id = UUID(ADMIN_A_ID)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
    )
    assert login_response.status_code == 200
    access = login_response.json()["access_token"]
    first = login_response.cookies.get("refresh_token")
    assert first is not None
    rotated = await _refresh(client, first)
    assert rotated.status_code == 200
    second = rotated.cookies.get("refresh_token")
    assert second is not None
    jtis_before = await _active_jtis(fake_redis, ADMIN_A_ID)
    active_before = await _active_count(db_session, user_id)
    # Non-trivial baseline: the committed version must match the live JWT.
    version_before = await _credential_version(db_session)
    assert version_before == decode_access_token(access)["credential_version"]

    unknown = await _refresh(client, "totally-unknown-refresh-token")

    assert unknown.status_code == 401
    assert unknown.json()["detail"] == REFRESH_INVALID_DETAIL
    assert "access_token" not in unknown.json()
    assert await _active_count(db_session, user_id) == active_before
    assert await _active_jtis(fake_redis, ADMIN_A_ID) == jtis_before
    # S3: no revocation side effects — the credential version in the DB is
    # untouched and the existing access JWT still authenticates.
    assert await _credential_version(db_session) == version_before
    still_works = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert still_works.status_code == 200

    # The legitimate session still rotates.
    still_valid = await _refresh(client, second)
    assert still_valid.status_code == 200


async def test_expired_refresh_token_rejects_without_revoking_sessions(
    production_tx_client, db_session: AsyncSession, seed_data
):
    """S3: an expired token is 401 and does not revoke the family."""
    client, fake_redis = production_tx_client
    await _release_fixture_savepoint(db_session)

    user_id = UUID(ADMIN_A_ID)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
    )
    assert login_response.status_code == 200
    access = login_response.json()["access_token"]
    first = login_response.cookies.get("refresh_token")
    assert first is not None
    rotated = await _refresh(client, first)
    assert rotated.status_code == 200
    second = rotated.cookies.get("refresh_token")
    assert second is not None

    # Expire the *current* token without revoking it.
    await db_session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == _hash_refresh_token(second))
        .values(expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    )
    await db_session.commit()
    jtis_before = await _active_jtis(fake_redis, ADMIN_A_ID)
    active_before = await _active_count(db_session, user_id)
    # Non-trivial baseline: the committed version must match the live JWT.
    version_before = await _credential_version(db_session)
    assert version_before == decode_access_token(access)["credential_version"]

    expired = await _refresh(client, second)

    assert expired.status_code == 401
    assert expired.json()["detail"] == REFRESH_INVALID_DETAIL
    assert await _active_count(db_session, user_id) == active_before
    assert await _active_jtis(fake_redis, ADMIN_A_ID) == jtis_before
    # S3: no revocation side effects — the credential version in the DB is
    # untouched and the existing access JWT still authenticates.
    assert await _credential_version(db_session) == version_before
    still_works = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert still_works.status_code == 200


async def test_expired_rotated_token_is_not_treated_as_reuse(
    production_tx_client, db_session: AsyncSession, seed_data
):
    """S3: replaying an *expired* predecessor revokes nothing.

    R1 keeps its rotation marker after rotating, so it still matches the reuse
    lookup. Its expiry must be honoured first: an expired cookie is a plain
    rejection, not evidence that the live successor was replayed.
    """
    client, fake_redis = production_tx_client
    await _release_fixture_savepoint(db_session)

    user_id = UUID(ADMIN_A_ID)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
    )
    assert login_response.status_code == 200
    access = login_response.json()["access_token"]
    first = login_response.cookies.get("refresh_token")
    assert first is not None
    rotated = await _refresh(client, first)
    assert rotated.status_code == 200
    second = rotated.cookies.get("refresh_token")
    assert second is not None

    # Expire the rotated predecessor without touching its rotation marker.
    await db_session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == _hash_refresh_token(first))
        .values(expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    )
    await db_session.commit()
    jtis_before = await _active_jtis(fake_redis, ADMIN_A_ID)
    active_before = await _active_count(db_session, user_id)
    # Non-trivial baseline: the committed version must match the live JWT.
    version_before = await _credential_version(db_session)
    assert version_before == decode_access_token(access)["credential_version"]

    expired = await _refresh(client, first)

    assert expired.status_code == 401
    assert expired.json()["detail"] == REFRESH_INVALID_DETAIL
    assert "set-cookie" not in {k.lower() for k in expired.headers}
    assert await _active_count(db_session, user_id) == active_before
    assert await _active_jtis(fake_redis, ADMIN_A_ID) == jtis_before
    # S3: no revocation side effects — the credential version in the DB is
    # untouched and the existing access JWT still authenticates.
    assert await _credential_version(db_session) == version_before
    still_works = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert still_works.status_code == 200

    # The live successor still renews: its family was never revoked.
    successor = await _refresh(client, second)
    assert successor.status_code == 200


async def test_revoked_without_rotation_is_not_treated_as_reuse(
    production_tx_client, db_session: AsyncSession, seed_data
):
    """Revocation alone (logout/cap/password) is not evidence of rotation.

    The defensive branch keys on the explicit rotation marker, so replaying a
    token that was revoked by another cause rejects with 401 while the user's
    other sessions and access tokens survive.
    """
    client, fake_redis = production_tx_client
    await _release_fixture_savepoint(db_session)

    first = await _login(client)
    rotated = await _refresh(client, first)
    assert rotated.status_code == 200
    second = rotated.cookies.get("refresh_token")
    assert second is not None
    other_session = await _login(client)
    assert other_session != second

    await db_session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == _hash_refresh_token(second))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db_session.commit()
    second_record = await _record(db_session, second)
    assert second_record is not None
    assert second_record.rotated_to_id is None
    jtis_before = await _active_jtis(fake_redis, ADMIN_A_ID)
    assert jtis_before

    rejected = await _refresh(client, second)

    assert rejected.status_code == 401
    assert await _active_jtis(fake_redis, ADMIN_A_ID) == jtis_before
    still_valid = await _refresh(client, other_session)
    assert still_valid.status_code == 200


async def test_reuse_revokes_access_even_if_redis_denylist_write_fails(
    production_tx_client, db_session: AsyncSession, seed_data, monkeypatch
):
    from redis.exceptions import RedisError
    import app.modules.auth.service as service

    client, _redis = production_tx_client
    await _release_fixture_savepoint(db_session)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
    )
    assert login.status_code == 200
    access = login.json()["access_token"]
    first = login.cookies.get("refresh_token")
    assert first is not None
    assert (await _refresh(client, first)).status_code == 200

    async def fail_revoke(*args, **kwargs):
        raise RedisError("test denylist failure")

    monkeypatch.setattr(service, "revoke_captured_user_access_tokens", fail_revoke)
    assert (await _refresh(client, first)).status_code == 401
    client.cookies.clear()
    response = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("version", [None, True, False, "0", 0.0, -1, 1])
async def test_invalid_or_mismatched_version_rejected(
    production_tx_client, db_session: AsyncSession, seed_data, version
):
    client, _redis = production_tx_client
    await _release_fixture_savepoint(db_session)
    await _reset_credential_version(db_session)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
    )
    assert login.status_code == 200
    payload = decode_access_token(login.json()["access_token"])
    payload["credential_version"] = version
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    response = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert (await _refresh(client, login.cookies["refresh_token"])).status_code == 200


async def test_missing_version_is_accepted_for_initial_credentials(
    production_tx_client, db_session: AsyncSession, seed_data
):
    client, _redis = production_tx_client
    await _release_fixture_savepoint(db_session)
    await _reset_credential_version(db_session)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_A_EMAIL, "password": ADMIN_A_PASSWORD},
    )
    assert login.status_code == 200
    payload = decode_access_token(login.json()["access_token"])
    assert payload.pop("credential_version") == 0
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    response = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


async def test_normal_rotation_preserves_other_session(
    production_tx_client, db_session: AsyncSession, seed_data
):
    client, _redis = production_tx_client
    await _release_fixture_savepoint(db_session)
    first = await _login(client)
    other = await _login(client)
    rotated = await _refresh(client, first)
    assert rotated.status_code == 200
    assert rotated.json().get("access_token")
    assert (await _refresh(client, other)).status_code == 200


async def test_reuse_response_does_not_issue_tokens_over_http(
    production_tx_client, db_session: AsyncSession, seed_data
):
    """S2: the 401 body and headers carry no new credentials."""
    client, _redis = production_tx_client
    await _release_fixture_savepoint(db_session)

    first = await _login(client)
    rotated = await _refresh(client, first)
    assert rotated.status_code == 200

    replay = await _refresh(client, first)

    assert replay.status_code == 401
    assert set(replay.json()) == {"detail"}
    assert "set-cookie" not in {k.lower() for k in replay.headers}
