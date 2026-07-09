"""Tests for app/core/config.py — SECRET_KEY strength validation (issue #250)."""
from __future__ import annotations

import pytest

# Shared required fields to create Settings instances in tests
_REQUIRED = dict(
    DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
    DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
    POSTGRES_USER="test",
    POSTGRES_PASSWORD="test",
    POSTGRES_DB="test",
)

# Valid high-entropy key (~4.7 bits/char, 128 chars)
_VALID_KEY = "abcdefghijklmnopqrstuvwxyz" * 5  # 130 chars


class TestSecretKeyMinimumLength:
    """SECRET_KEY must be at least 128 characters."""

    def test_127_char_key_rejected(self):
        """A 127-character key must be rejected."""
        from app.core.config import Settings

        with pytest.raises(ValueError, match="128"):
            Settings(
                _env_file=None,
                SECRET_KEY="a" * 127,
                LLM_PROVIDER="ollama",
                **_REQUIRED,
            )

    def test_128_char_key_accepted(self):
        """A 128-character key with sufficient entropy must be accepted."""
        from app.core.config import Settings

        key = "abcdefghijklmnopqrstuvwxyz" * 5  # 130 chars > 128
        # Trim to exactly 128 with diverse chars
        key = "".join(chr(ord("a") + (i % 26)) for i in range(128))
        s = Settings(
            _env_file=None,
            SECRET_KEY=key,
            LLM_PROVIDER="ollama",
            **_REQUIRED,
        )
        assert len(s.SECRET_KEY) >= 128


class TestSecretKeyEntropy:
    """SECRET_KEY must have sufficient entropy."""

    def test_repeated_single_char_rejected(self):
        """A 128+ key consisting of a single repeated char must be rejected."""
        from app.core.config import Settings

        # 128 identical characters — max freq ratio = 1.0 > 0.5
        with pytest.raises(ValueError, match="entropía|entrop"):
            Settings(
                _env_file=None,
                SECRET_KEY="x" * 128,
                LLM_PROVIDER="ollama",
                **_REQUIRED,
            )

    def test_mostly_repeated_char_rejected(self):
        """A key where >50% of chars are the same must be rejected."""
        from app.core.config import Settings

        # 65 identical 'x' out of 128 — max freq ratio ≈ 0.508 > 0.5
        key = "x" * 65 + "".join(chr(ord("a") + (i % 26)) for i in range(63))
        with pytest.raises(ValueError, match="entropía|entrop"):
            Settings(
                _env_file=None,
                SECRET_KEY=key,
                LLM_PROVIDER="ollama",
                **_REQUIRED,
            )

    def test_low_shannon_entropy_rejected(self):
        """A key with Shannon entropy below 3.0 bits/char must be rejected."""
        from app.core.config import Settings

        # 128 chars with only 4 unique chars, each appearing 32 times
        # Shannon entropy = -4 * (32/128) * log2(32/128) = -1 * log2(0.25) = 2.0 bits/char
        key = "abcd" * 32  # 128 chars, only a/b/c/d
        with pytest.raises(ValueError, match="entropía|entrop"):
            Settings(
                _env_file=None,
                SECRET_KEY=key,
                LLM_PROVIDER="ollama",
                **_REQUIRED,
            )


class TestSecretKeyValidKeys:
    """Valid SECRET_KEY values must be accepted."""

    def test_valid_random_like_key_accepted(self):
        """A high-entropy key must pass validation."""
        from app.core.config import Settings

        s = Settings(
            _env_file=None,
            SECRET_KEY=_VALID_KEY,
            LLM_PROVIDER="ollama",
            **_REQUIRED,
        )
        assert s.SECRET_KEY == _VALID_KEY

    def test_token_urlsafe_style_accepted(self):
        """A key resembling secrets.token_urlsafe(64) output must be accepted."""
        from app.core.config import Settings

        # URL-safe base64-like alphabet (A-Z, a-z, 0-9, -, _) with 86 unique chars
        # 96 chars * 2 = 192 chars, well above 128, with high entropy
        key = (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        s = Settings(
            _env_file=None,
            SECRET_KEY=key,
            LLM_PROVIDER="ollama",
            **_REQUIRED,
        )
        assert len(s.SECRET_KEY) >= 128
