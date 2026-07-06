from __future__ import annotations

from uuid import uuid4

import bcrypt
import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import ValidationError

from app.core.security import (
    can_assign_role,
    has_minimum_role,
    is_token_revoked,
    revoke_tokens_by_jtis,
    secure_compare,
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
    """Direct coverage for the bcrypt hashpw compatibility shim."""

    def test_hashes_71_byte_password(self):
        password = b"a" * 71
        hashed = bcrypt.hashpw(password, bcrypt.gensalt())

        assert bcrypt.checkpw(password, hashed) is True

    def test_hashes_72_byte_password(self):
        password = b"a" * 72
        hashed = bcrypt.hashpw(password, bcrypt.gensalt())

        assert bcrypt.checkpw(password, hashed) is True

    @pytest.mark.parametrize("password_length", [73, 200])
    def test_passwords_over_72_bytes_are_truncated_by_compat_shim(
        self,
        password_length: int,
    ):
        password = b"a" * password_length
        truncated = password[:72]
        salt = bcrypt.gensalt()

        assert bcrypt.hashpw(password, salt) == bcrypt.hashpw(truncated, salt)


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
            await redis.aclose()
