"""Approval tests for security dependency migration (issues #174, #179).

These tests capture current behavior of JWT token creation/decoding and
password hashing/verification. After migrating python-jose → PyJWT and
passlib → direct bcrypt, these tests MUST still pass — they assert the
externally observable contract, not the internal library used.
"""
from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    validate_password_length,
)
from app.core.config import settings


# ---------------------------------------------------------------------------
# JWT approval tests (contract: HS256 tokens, same claims, same errors)
# ---------------------------------------------------------------------------

class TestJWTApproval:
    """Capture the current JWT contract before migrating python-jose → PyJWT."""

    def test_create_and_decode_roundtrip(self):
        """A token created by create_access_token MUST be decodable."""
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        token, jti = create_access_token(
            user_id=user_id,
            tenant_id=tenant_id,
            role="admin",
            is_superadmin=False,
        )

        assert isinstance(token, str)
        assert len(token) > 0
        assert isinstance(jti, str)

        payload = decode_access_token(token)

        assert payload["sub"] == user_id
        assert payload["jti"] == jti
        assert payload["tenant_id"] == tenant_id
        assert payload["role"] == "admin"
        assert payload["is_superadmin"] is False
        assert "iat" in payload
        assert "exp" in payload

    def test_create_and_decode_superadmin(self):
        """Superadmin tokens must have tenant_id=None."""
        user_id = str(uuid.uuid4())

        token, jti = create_access_token(
            user_id=user_id,
            tenant_id=None,
            role="superadmin",
            is_superadmin=True,
        )

        payload = decode_access_token(token)

        assert payload["sub"] == user_id
        assert payload["tenant_id"] is None
        assert payload["is_superadmin"] is True
        assert payload["role"] == "superadmin"

    def test_token_expiry_is_honored(self):
        """Expired tokens MUST raise an error on decode."""
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        token, _ = create_access_token(
            user_id=user_id,
            tenant_id=tenant_id,
            role="viewer",
            is_superadmin=False,
            expires_delta=timedelta(seconds=-1),  # already expired
        )

        with pytest.raises(Exception) as exc_info:
            decode_access_token(token)

        error_msg = str(exc_info.value).lower()
        assert "expire" in error_msg or "signature" in error_msg or "exp" in error_msg

    def test_token_with_custom_expiry(self):
        """A token with a custom expiry delta must have the right exp claim."""
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        token, _ = create_access_token(
            user_id=user_id,
            tenant_id=tenant_id,
            role="viewer",
            is_superadmin=False,
            expires_delta=timedelta(hours=1),
        )

        payload = decode_access_token(token)

        # exp should be roughly ~3600 seconds from now
        import time as _time
        now_ts = int(_time.time())
        assert payload["exp"] - now_ts > 3500  # at least ~58 min
        assert payload["exp"] - now_ts < 3700  # at most ~62 min

    def test_tampered_token_raises(self):
        """A tampered (invalid signature) token MUST raise an error."""
        user_id = str(uuid.uuid4())

        token, _ = create_access_token(
            user_id=user_id,
            tenant_id=str(uuid.uuid4()),
            role="viewer",
            is_superadmin=False,
        )

        # Tamper with the payload by changing the last character
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

        with pytest.raises(Exception):
            decode_access_token(tampered)

    def test_token_with_different_roles(self):
        """All valid roles produce decodable tokens."""
        for role in ("viewer", "analyst", "ingestor", "admin", "superadmin"):
            user_id = str(uuid.uuid4())
            tenant_id = str(uuid.uuid4()) if role != "superadmin" else None
            is_sa = role == "superadmin"

            token, _ = create_access_token(
                user_id=user_id,
                tenant_id=tenant_id,
                role=role,
                is_superadmin=is_sa,
            )

            payload = decode_access_token(token)
            assert payload["role"] == role

    def test_decode_invalid_token_raises(self):
        """A completely invalid string MUST raise an error."""
        with pytest.raises(Exception):
            decode_access_token("not.a.valid.jwt")

    def test_decode_empty_token_raises(self):
        """An empty string MUST raise an error."""
        with pytest.raises(Exception):
            decode_access_token("")

    def test_decode_malformed_token_raises(self):
        """Malformed JWT MUST raise an error."""
        with pytest.raises(Exception):
            decode_access_token("abc.def")

    def test_various_algorithms_work(self):
        """Ensure the algorithm from settings is honored.

        Note: this tests whatever algorithm is configured (default: HS256).
        The token must be decodable with the same algorithm.
        """
        user_id = str(uuid.uuid4())
        token, _ = create_access_token(
            user_id=user_id,
            tenant_id=str(uuid.uuid4()),
            role="viewer",
            is_superadmin=False,
        )
        payload = decode_access_token(token)
        assert payload["sub"] == user_id


# ---------------------------------------------------------------------------
# Password hashing approval tests (contract: bcrypt, 72-byte limit)
# ---------------------------------------------------------------------------

class TestPasswordHashingApproval:
    """Capture the current password hashing contract before migrating passlib → direct bcrypt."""

    def test_hash_returns_string(self):
        """hash_password MUST return a string."""
        result = hash_password("my_secret_password")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_is_deterministic_for_same_salt(self):
        """Each call to hash_password MUST produce a different hash (different salts)."""
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2  # different salts

    def test_verify_correct_password_returns_true(self):
        """verify_password MUST return True for the correct password."""
        hashed = hash_password("correct_password_123")
        assert verify_password("correct_password_123", hashed) is True

    def test_verify_wrong_password_returns_false(self):
        """verify_password MUST return False for an incorrect password."""
        hashed = hash_password("correct_password_123")
        assert verify_password("wrong_password_456", hashed) is False

    def test_verify_empty_password_returns_false(self):
        """verify_password with empty password MUST return False."""
        hashed = hash_password("some_password")
        assert verify_password("", hashed) is False

    def test_verify_case_sensitive(self):
        """Bcrypt is case-sensitive."""
        hashed = hash_password("MyPassword")
        assert verify_password("mypassword", hashed) is False
        assert verify_password("MyPassword", hashed) is True

    def test_hashes_72_byte_password(self):
        """Password of exactly 72 bytes MUST be hashable and verifiable."""
        password = "a" * 72  # 72 ASCII bytes
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_hashes_71_byte_password(self):
        """Password of 71 bytes MUST be hashable and verifiable."""
        password = "a" * 71
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_passwords_over_72_bytes_are_truncated(self):
        """Passwords over 72 bytes MUST be truncated before hashing.

        This means verify_password with the full 73-byte password
        should still succeed because the hash was computed on the
        first 72 bytes.
        """
        password = "a" * 73
        truncated = "a" * 72
        hashed = hash_password(password)

        # The hash was computed on the truncated password,
        # so verifying with the truncated version should match
        assert verify_password(truncated, hashed) is True

        # The full 73-byte password should ALSO verify because
        # verify_password also truncates to 72 bytes
        assert verify_password(password, hashed) is True

    def test_cross_compatibility_roundtrip(self):
        """hash_password output MUST be verifiable by verify_password.

        This ensures the two functions stay in sync after migration.
        """
        for _ in range(5):
            password = f"pw_{uuid.uuid4().hex[:16]}"
            hashed = hash_password(password)
            assert verify_password(password, hashed) is True

    def test_unicode_password(self):
        """Unicode passwords (beyond ASCII) MUST work."""
        password = "café_mañana_テスト_пароль"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True
        assert verify_password("wrong", hashed) is False

    def test_long_unicode_truncation(self):
        """37 'ñ' chars = 74 bytes → truncated to 72 bytes (36 chars)."""
        password = "ñ" * 37
        truncated = "ñ" * 36
        hashed = hash_password(password)

        assert verify_password(truncated, hashed) is True
        assert verify_password(password, hashed) is True


# ---------------------------------------------------------------------------
# Validation boundary defense
# ---------------------------------------------------------------------------

class TestPasswordLengthValidationApproval:
    """Service-level validation must still work post-migration."""

    def test_72_bytes_passes(self):
        """72-byte password must pass validation."""
        validate_password_length("a" * 72)

    def test_73_bytes_raises(self):
        """73-byte password must be rejected."""
        from app.core.exceptions import UserError

        with pytest.raises(UserError) as exc:
            validate_password_length("a" * 73)
        assert exc.value.status_code == 400

    def test_unicode_at_72_bytes_passes(self):
        """36 'ñ' chars = 72 bytes."""
        validate_password_length("ñ" * 36)

    def test_unicode_over_72_raises(self):
        """37 'ñ' chars = 74 bytes."""
        from app.core.exceptions import UserError

        with pytest.raises(UserError):
            validate_password_length("ñ" * 37)
