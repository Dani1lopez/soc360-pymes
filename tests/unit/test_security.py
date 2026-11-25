# fmt: off
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.security import (
    can_assign_role,
    has_minimum_role,
    is_token_revoked,
    get_active_jtis,
    revoke_access_token,
    revoke_all_user_access_tokens,
    revoke_tokens_by_jtis,
    secure_compare,
    track_jti,
    untrack_jti,
)
from app.modules.auth.schemas import ChangePasswordRequest
from app.modules.users.schemas import RoleEnum, UserCreate


class TestUserCreatePasswordSchema:
    """Pydantic-level validation of password length (issue #130)."""

    def test_71_bytes_ok(self):
        # 71 ASCII chars = 71 bytes UTF-8
        password = "a" * 71
        user = UserCreate(
            email="a@b.com",
            password=password,
            full_name="Test User",
            role=RoleEnum.admin,
            tenant_id=uuid4(),
        )

        assert user.password == password

    def test_72_bytes_ok(self):
        # 72 ASCII chars = 72 bytes UTF-8 (the boundary)
        password = "a" * 72
        user = UserCreate(
            email="a@b.com",
            password=password,
            full_name="Test User",
            role=RoleEnum.admin,
            tenant_id=uuid4(),
        )

        assert user.password == password

    def test_73_bytes_raises_validation_error(self):
        # 73 ASCII chars = 73 bytes UTF-8 (just over the limit)
        with pytest.raises(ValidationError) as exc:
            UserCreate(
                email="a@b.com",
                password="a" * 73,
                full_name="Test User",
                role=RoleEnum.admin,
                tenant_id=uuid4(),
            )

        assert "password" in str(exc.value).lower() or "72" in str(exc.value)

    def test_multibyte_at_boundary_ok(self):
        # "ñ" is 2 bytes in UTF-8; 36 "ñ"s = 72 bytes (boundary)
        password = "ñ" * 36
        user = UserCreate(
            email="a@b.com",
            password=password,
            full_name="Test User",
            role=RoleEnum.admin,
            tenant_id=uuid4(),
        )

        assert user.password == password

    def test_multibyte_over_boundary_raises(self):
        # 37 "ñ"s = 74 bytes (over the limit)
        with pytest.raises(ValidationError):
            UserCreate(
                email="a@b.com",
                password="ñ" * 37,
                full_name="Test User",
                role=RoleEnum.admin,
                tenant_id=uuid4(),
            )


class TestChangePasswordRequestPasswordSchema:
    """Pydantic-level validation of changed password byte length."""

    def test_72_bytes_ok(self):
        # Includes uppercase, lowercase, and digit for strength validation.
        password = "Aa1" + ("b" * 69)
        request = ChangePasswordRequest(
            current_password="OldPassword123!",
            new_password=password,
        )

        assert request.new_password == password

    def test_multibyte_over_boundary_raises(self):
        # 3 ASCII bytes + 35 "ñ" chars * 2 bytes = 73 bytes.
        password = "Aa1" + ("ñ" * 35)

        with pytest.raises(ValidationError):
            ChangePasswordRequest(
                current_password="OldPassword123!",
                new_password=password,
            )


class TestPasswordLengthBoundaryDefenseInDepth:
    """Service-level validation of password length (issue #130 backstop)."""

    def test_72_bytes_hash_ok(self):
        from app.core.security import validate_password_length

        validate_password_length("a" * 72)

    def test_73_bytes_service_raises(self):
        from app.core.exceptions import UserError
        from app.core.security import validate_password_length

        with pytest.raises(UserError) as exc:
            validate_password_length("a" * 73)

        assert exc.value.status_code == 400


class TestSecureCompare:
    """Unit coverage for constant-time string comparisons."""

    def test_equal_strings_return_true(self):
        assert secure_compare("same-token", "same-token") is True

    def test_unequal_strings_return_false(self):
        assert secure_compare("same-token", "other-token") is False

    def test_different_lengths_return_false(self):
        assert secure_compare("short", "short-but-longer") is False

    def test_empty_strings_return_true(self):
        assert secure_compare("", "") is True


class TestBcryptShim:
    """Coverage for password hashing with 72-byte limit (now built-in)."""

    def test_hashes_71_byte_password(self):
        from app.core.security import hash_password, verify_password

        password = "a" * 71
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_hashes_72_byte_password(self):
        from app.core.security import hash_password, verify_password

        password = "a" * 72
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    @pytest.mark.parametrize("password_length", [73, 200])
    def test_passwords_over_72_bytes_are_truncated(
        self,
        password_length: int,
    ):
        from app.core.security import hash_password, verify_password

        password = "a" * password_length
        truncated = "a" * 72

        # Full password and truncated must both be hashable
        hashed = hash_password(password)

        # Verify with truncated version must succeed
        assert verify_password(truncated, hashed) is True
        # Verify with full version must also succeed (verify also truncates)
        assert verify_password(password, hashed) is True


class TestRoleHelpers:
    """Matrix coverage for role hierarchy helpers."""

    @pytest.mark.parametrize(
        ("user_role", "required_role", "expected"),
        [
            ("admin", "viewer", True),
            ("viewer", "admin", False),
            ("superadmin", "admin", True),
            ("analyst", "ingestor", True),
            ("ingestor", "analyst", True),
            ("analyst", "admin", False),
            ("unknown", "viewer", False),
            ("viewer", "unknown", True),
        ],
    )
    def test_has_minimum_role_matrix(
        self,
        user_role: str,
        required_role: str,
        expected: bool,
    ):
        assert has_minimum_role(user_role, required_role) is expected

    @pytest.mark.parametrize(
        ("assigner_role", "target_role", "expected"),
        [
            ("admin", "viewer", True),
            ("admin", "analyst", True),
            ("admin", "ingestor", True),
            ("admin", "admin", False),
            ("viewer", "admin", False),
            ("superadmin", "admin", True),
            ("superadmin", "superadmin", False),
            ("analyst", "viewer", True),
            ("analyst", "ingestor", False),
            ("unknown", "viewer", False),
        ],
    )
    def test_can_assign_role_matrix(
        self,
        assigner_role: str,
        target_role: str,
        expected: bool,
    ):
        assert can_assign_role(assigner_role, target_role) is expected


class TestBulkRevocation:
    """Unit coverage for bulk token revocation with fakeredis."""

    @pytest.mark.asyncio
    async def test_revoke_all_zero_success_is_typed_and_retains_tracking_set(self):
        """A first SET failure must classify the outage and preserve active JTIs."""
        class FailingRedis(FakeRedis):
            async def set(self, key: str, *args, **kwargs):  # type: ignore[override]
                raise RedisConnectionError("raw-redis-transport-detail")
        redis = FailingRedis()
        try:
            await redis.sadd("active_jtis:user-zero", "jti-zero")
            with patch("app.core.security.logger.warning") as warning:
                from app.core.exceptions import RedisUnreachableError

                with pytest.raises(RedisUnreachableError):
                    await revoke_all_user_access_tokens(
                        "user-zero", redis, ttl_seconds=60
                    )

            assert await redis.smembers("active_jtis:user-zero") == {b"jti-zero"}
            assert await redis.keys("revoked:*") == []
            assert "raw-redis-transport-detail" not in repr(warning.call_args)
        finally:
            await redis.aclose()
    @pytest.mark.asyncio
    async def test_revoke_all_partial_failure_stops_and_retains_tracking_set(self):
        """A later SET failure must not delete the tracking set or continue writes."""
        class FailingRedis(FakeRedis):
            def __init__(self) -> None:
                super().__init__()
                self.set_calls: list[str] = []
                self.delete_calls: list[str] = []

            async def smembers(self, key: str):  # type: ignore[override]
                if key == "active_jtis:user-partial":
                    return [b"jti-a", b"jti-b", b"jti-c"]
                return await super().smembers(key)

            async def set(self, key: str, *args, **kwargs):  # type: ignore[override]
                self.set_calls.append(key)
                if key == "revoked:jti-b":
                    raise RedisConnectionError("partial transport failure")
                return await super().set(key, *args, **kwargs)

            async def delete(self, key: str, *args, **kwargs):  # type: ignore[override]
                self.delete_calls.append(key)
                return await super().delete(key, *args, **kwargs)
        redis = FailingRedis()
        try:
            await redis.sadd("active_jtis:user-partial", "jti-a", "jti-b", "jti-c")
            from app.core.exceptions import RedisUnreachableError
            with pytest.raises(RedisUnreachableError):
                await revoke_all_user_access_tokens(
                    "user-partial", redis, ttl_seconds=60
                )

            assert redis.set_calls == ["revoked:jti-a", "revoked:jti-b"]
            assert redis.delete_calls == []
            assert set(await redis.smembers("active_jtis:user-partial")) == {
                b"jti-a",
                b"jti-b",
                b"jti-c",
            }
            assert await redis.exists("revoked:jti-a") == 1
            assert await redis.exists("revoked:jti-c") == 0
        finally:
            await redis.aclose()
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "operation",
        [
            "revoke_access_token",
            "is_token_revoked",
            "track_jti",
            "untrack_jti",
            "get_active_jtis",
        ],
    )
    async def test_revocation_primitive_transport_errors_are_typed(
        self, operation: str
    ):
        """Direct revocation Redis failures must expose RedisOutageError subclasses."""
        redis = MagicMock()
        failure = RedisConnectionError("transport unavailable")
        for method_name in ("set", "exists", "sadd", "srem", "smembers"):
            setattr(redis, method_name, AsyncMock(side_effect=failure))
        from app.core.exceptions import RedisOutageError
        operations = {
            "revoke_access_token": lambda: revoke_access_token(
                "jti-primitive", 60, redis
            ),
            "is_token_revoked": lambda: is_token_revoked("jti-primitive", redis),
            "track_jti": lambda: track_jti("user-primitive", "jti-primitive", redis),
            "untrack_jti": lambda: untrack_jti(
                "user-primitive", "jti-primitive", redis
            ),
            "get_active_jtis": lambda: get_active_jtis("user-primitive", redis),
        }
        with pytest.raises(RedisOutageError):
            await operations[operation]()

    @pytest.mark.asyncio
    async def test_revocation_outage_reaches_sanitized_http_boundary(self):
        """A typed revocation outage must retain the global sanitized 503 contract."""
        from app.core.config import settings
        from app.core.security import revoke_access_token
        from app.main import create_app

        raw_detail = "raw-redis-transport-detail"

        class BrokenRedis:
            async def set(self, *args, **kwargs):
                raise RedisConnectionError(raw_detail)

        app = create_app()

        @app.post("/_test/revoke-outage", include_in_schema=False)
        async def _revoke_outage():
            await revoke_access_token("jti-http", 60, BrokenRedis())
            return {"ok": True}

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post("/_test/revoke-outage")

        assert response.status_code == 503
        assert response.headers["Retry-After"] == str(
            settings.REDIS_OUTAGE_RETRY_AFTER_SECONDS
        )
        assert response.json() == {"detail": "service temporarily unavailable"}
        assert raw_detail not in response.text

    @pytest.mark.asyncio
    async def test_empty_jti_list_is_noop(self):
        redis = FakeRedis()
        try:
            await revoke_tokens_by_jtis([], redis, ttl_seconds=60)

            assert await redis.keys("revoked:*") == []
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_single_jti_is_revoked_with_ttl(self):
        redis = FakeRedis()
        try:
            await revoke_tokens_by_jtis(["jti-1"], redis, ttl_seconds=60)

            assert await is_token_revoked("jti-1", redis) is True
            assert await redis.ttl("revoked:jti-1") > 0
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_many_jtis_are_revoked(self):
        redis = FakeRedis()
        try:
            jtis = [f"jti-{index}" for index in range(100)]
            await revoke_tokens_by_jtis(jtis, redis, ttl_seconds=60)

            assert await redis.exists(*(f"revoked:{jti}" for jti in jtis)) == len(jtis)
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_arbitrary_jti_format_is_revoked(self):
        redis = FakeRedis()
        try:
            jti = "not-a-uuid"
            await revoke_tokens_by_jtis([jti], redis, ttl_seconds=60)

            assert await is_token_revoked(jti, redis) is True
        finally:
            await redis.aclose()


class TestRevokeAllUserAccessTokensBatch:
    """Tests for batch token revocation (issue #104)."""

    @pytest.mark.asyncio
    async def test_batch_revokes_multiple_users(self):
        """Batch revocation must revoke all JTIs for all users in O(1) pipelines."""
        from app.core.security import revoke_all_user_access_tokens_batch

        redis = FakeRedis()
        try:
            # Setup: add JTIs for 3 users (note: prefix is "active_jtis:" with 's')
            await redis.sadd("active_jtis:user-1", "jti-1", "jti-2")
            await redis.sadd("active_jtis:user-2", "jti-3")
            await redis.sadd("active_jtis:user-3", "jti-4", "jti-5", "jti-6")

            # Execute batch revocation
            await revoke_all_user_access_tokens_batch(
                user_ids=["user-1", "user-2", "user-3"],
                redis=redis,
                ttl_seconds=3600,
            )

            # Verify all JTIs are in denylist
            for jti in ["jti-1", "jti-2", "jti-3", "jti-4", "jti-5", "jti-6"]:
                assert await is_token_revoked(jti, redis) is True

            # Verify all active_jtis sets are deleted
            for uid in ["user-1", "user-2", "user-3"]:
                assert await redis.exists(f"active_jtis:{uid}") == 0
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_batch_with_empty_user_list(self):
        """Batch revocation with empty user list must be a no-op."""
        from app.core.security import revoke_all_user_access_tokens_batch

        redis = FakeRedis()
        try:
            # Should not raise
            await revoke_all_user_access_tokens_batch(
                user_ids=[],
                redis=redis,
                ttl_seconds=3600,
            )
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_batch_with_users_without_jtis(self):
        """Batch revocation must handle users with no active JTIs gracefully."""
        from app.core.security import revoke_all_user_access_tokens_batch

        redis = FakeRedis()
        try:
            # user-1 has JTIs, user-2 has none (note: prefix is "active_jtis:" with 's')
            await redis.sadd("active_jtis:user-1", "jti-1")

            await revoke_all_user_access_tokens_batch(
                user_ids=["user-1", "user-2"],
                redis=redis,
                ttl_seconds=3600,
            )

            # user-1's JTI should be revoked
            assert await is_token_revoked("jti-1", redis) is True
            # user-2 should not cause any errors
            assert await redis.exists("active_jtis:user-2") == 0
        finally:
            await redis.aclose()


class TestBcryptAsyncWrappers:
    """Verify async wrappers offload bcrypt to threadpool (issue #195)."""

    @pytest.mark.asyncio
    async def test_hash_password_async_produces_valid_hash(self):
        """hash_password_async must return a bcrypt hash string."""
        from app.core.security import hash_password_async

        result = await hash_password_async("testpassword123")

        assert result.startswith("$2")
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_verify_password_async_correct(self):
        """verify_password_async returns True for matching passwords."""
        from app.core.security import hash_password, verify_password_async

        h = hash_password("testpassword123")

        assert await verify_password_async("testpassword123", h) is True

    @pytest.mark.asyncio
    async def test_verify_password_async_wrong(self):
        """verify_password_async returns False for mismatched passwords."""
        from app.core.security import hash_password, verify_password_async

        h = hash_password("testpassword123")

        assert await verify_password_async("wrongpassword", h) is False

    @pytest.mark.asyncio
    async def test_concurrent_bcrypt_does_not_block_event_loop(self):
        """10 concurrent verifications must complete faster than sequential."""
        from app.core.security import hash_password, verify_password_async

        h = hash_password("testpassword123")
        tasks = [verify_password_async("testpassword123", h) for _ in range(10)]

        # If these run sequentially: ~10 × 200 ms = 2 s+
        # If offloaded to threadpool: all run in parallel < 1 s
        results = await asyncio.wait_for(
            asyncio.gather(*tasks), timeout=1.5
        )
        assert all(results)


class TestRevokeAllUserAccessTokensOrdered:
    """REQ-140-R05: Ordered token revocation with fail-closed cleanup."""

    @pytest.mark.asyncio
    async def test_success_path(self):
        """All JTIs denylisted, active set deleted on success."""
        from app.core.security import revoke_all_user_access_tokens

        redis = FakeRedis()
        try:
            await redis.sadd("active_jtis:user-1", "jti-a", "jti-b", "jti-c")

            await revoke_all_user_access_tokens(
                user_id="user-1",
                redis=redis,
                ttl_seconds=3600,
            )

            # All JTIs in denylist
            assert await is_token_revoked("jti-a", redis) is True
            assert await is_token_revoked("jti-b", redis) is True
            assert await is_token_revoked("jti-c", redis) is True

            # Active set deleted
            assert await redis.exists("active_jtis:user-1") == 0
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_no_jtis_is_noop(self):
        """No active JTIs → no-op, no error."""
        from app.core.security import revoke_all_user_access_tokens

        redis = FakeRedis()
        try:
            await revoke_all_user_access_tokens(
                user_id="user-empty",
                redis=redis,
                ttl_seconds=3600,
            )
            # No keys should have been created
            assert await redis.keys("revoked:*") == []
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_partial_failure_retains_tracking_set(self):
        """After a partial denylist write, DELETE must not be attempted."""
        from app.core.security import revoke_all_user_access_tokens
        from app.core.exceptions import RedisUnreachableError

        redis = AsyncMock()
        redis.smembers = AsyncMock(return_value=[b"jti-1", b"jti-2", b"jti-3"])

        call_count = 0

        async def mock_set(key, value, ex):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ConnectionError("Redis dropped mid-flight")
            return True

        redis.set = mock_set
        redis.delete = AsyncMock()

        with pytest.raises(RedisUnreachableError):
            await revoke_all_user_access_tokens(
                user_id="user-pfail",
                redis=redis,
                ttl_seconds=3600,
            )

        # First JTI should have been denylisted
        assert call_count == 2  # Only 2 set calls made (third not attempted after fail)

        # DELETE must not be attempted while tracking state is incomplete.
        redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_zero_success_raises_error(self):
        """Zero denylist writes → classified error propagates for retry."""
        from app.core.security import revoke_all_user_access_tokens
        from app.core.exceptions import RedisUnreachableError

        redis = AsyncMock()
        redis.smembers = AsyncMock(return_value={b"jti-1", b"jti-2"})

        async def mock_set(key, value, ex):
            raise ConnectionError("Redis down")

        redis.set = mock_set
        redis.delete = AsyncMock()

        with pytest.raises(RedisUnreachableError):
            await revoke_all_user_access_tokens(
                user_id="user-zero",
                redis=redis,
                ttl_seconds=3600,
            )

        # DELETE must NOT have been called (no denylist writes succeeded)
        redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_failure_is_typed_and_logs(self):
        """DELETE failure after successful denylist must remain recoverable."""
        from app.core.security import revoke_all_user_access_tokens
        from app.core.exceptions import RedisUnreachableError

        redis = AsyncMock()
        redis.smembers = AsyncMock(return_value={b"jti-1", b"jti-2"})
        redis.set = AsyncMock(return_value=True)
        redis.delete = AsyncMock(side_effect=ConnectionError("Delete failed"))

        with patch("app.core.security.logger") as mock_logger:
            with pytest.raises(RedisUnreachableError):
                await revoke_all_user_access_tokens(
                    user_id="user-del-fail",
                    redis=redis,
                    ttl_seconds=3600,
                )

        # Denylist entries written
        assert redis.set.await_count == 2

        # DELETE was attempted (and failed)
        redis.delete.assert_awaited_once_with("active_jtis:user-del-fail")

        # Warning logged for cleanup failure
        mock_logger.warning.assert_any_call(
            "redis_active_jtis_cleanup_failed",
            extra={"user_id": "user-del-fail"},
        )

    @pytest.mark.asyncio
    async def test_command_order_denylist_before_delete(self):
        """Denylist SET commands MUST precede DELETE (recorded order)."""
        from app.core.security import revoke_all_user_access_tokens

        redis = AsyncMock()
        redis.smembers = AsyncMock(return_value=[b"jti-second", b"jti-first"])

        command_log: list[str] = []

        async def logged_set(key, value, ex):
            command_log.append(f"SET {key}")
            return True

        async def logged_delete(key):
            command_log.append(f"DELETE {key}")
            return 1

        redis.set = logged_set
        redis.delete = logged_delete

        await revoke_all_user_access_tokens(
            user_id="user-order",
            redis=redis,
            ttl_seconds=3600,
        )

        # All SETs must come before DELETE
        set_indices = [i for i, cmd in enumerate(command_log) if cmd.startswith("SET")]
        delete_indices = [i for i, cmd in enumerate(command_log) if cmd.startswith("DELETE")]

        assert len(set_indices) == 2
        assert len(delete_indices) == 1
        assert set_indices[-1] < delete_indices[0], f"SET indices {set_indices} must all be before DELETE at {delete_indices}"
        assert command_log[:2] == [
            "SET revoked:jti-first",
            "SET revoked:jti-second",
        ]
