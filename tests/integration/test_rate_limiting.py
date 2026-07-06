"""Integration tests for progressive lockout rate limiting.

Tests the dual-key (IP + email) progressive lockout mechanism with
escalating timeouts: 3min → 15min → 1h → 4h → 24h.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from fakeredis.aioredis import FakeRedis

from app.core.redis import get_redis
from app.core.rate_limit import RateLimiter, _get_lockout_seconds, _hash_email


# ---------------------------------------------------------------------------
# Unit tests for lockout escalation logic
# ---------------------------------------------------------------------------


class TestLockoutEscalation:
    """Test the lockout threshold → duration mapping."""

    def test_no_lockout_below_threshold(self):
        """No lockout when failures are below the first threshold."""
        assert _get_lockout_seconds(0) == 0
        assert _get_lockout_seconds(1) == 0
        assert _get_lockout_seconds(4) == 0

    def test_lockout_at_threshold(self):
        """Lockout starts when failures EXCEED the threshold (not at it)."""
        # At threshold: no lockout yet (allows one more attempt)
        assert _get_lockout_seconds(5) == 0
        # Exceeding threshold: lockout applies
        assert _get_lockout_seconds(6) == 3 * 60  # 3 min

    def test_escalation_table(self):
        """Verify all escalation levels."""
        # Below 5: no lockout
        assert _get_lockout_seconds(4) == 0
        
        # 5-10: 3 min (after exceeding 5)
        assert _get_lockout_seconds(6) == 3 * 60
        assert _get_lockout_seconds(10) == 3 * 60
        
        # 10-15: 15 min (after exceeding 10)
        assert _get_lockout_seconds(11) == 15 * 60
        assert _get_lockout_seconds(15) == 15 * 60
        
        # 15-20: 1 hour (after exceeding 15)
        assert _get_lockout_seconds(16) == 60 * 60
        assert _get_lockout_seconds(20) == 60 * 60
        
        # 20-25: 4 hours (after exceeding 20)
        assert _get_lockout_seconds(21) == 4 * 60 * 60
        assert _get_lockout_seconds(25) == 4 * 60 * 60
        
        # 25+: 24 hours (after exceeding 25)
        assert _get_lockout_seconds(26) == 24 * 60 * 60
        assert _get_lockout_seconds(100) == 24 * 60 * 60


class TestEmailHashing:
    """Test that emails are properly hashed for Redis keys."""

    def test_hash_is_deterministic(self):
        """Same email always produces the same hash."""
        h1 = _hash_email("user@example.com")
        h2 = _hash_email("user@example.com")
        assert h1 == h2

    def test_hash_is_case_insensitive(self):
        """Email hashing normalizes case."""
        assert _hash_email("User@Example.COM") == _hash_email("user@example.com")

    def test_hash_strips_whitespace(self):
        """Email hashing strips whitespace."""
        assert _hash_email("  user@example.com  ") == _hash_email("user@example.com")

    def test_hash_length(self):
        """Hash is truncated to 16 chars for readability."""
        assert len(_hash_email("any@email.com")) == 16

    def test_different_emails_different_hashes(self):
        """Different emails produce different hashes."""
        assert _hash_email("user1@example.com") != _hash_email("user2@example.com")


# ---------------------------------------------------------------------------
# Integration tests with FakeRedis
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRateLimiterIntegration:
    """Test RateLimiter with FakeRedis."""

    @pytest_asyncio.fixture(autouse=True)
    async def _cleanup_redis(self):
        """Clean up rate limit keys after each test."""
        self.redis = FakeRedis()
        yield
        await self.redis.flushall()
        await self.redis.aclose()

    @pytest_asyncio.fixture
    async def limiter(self) -> RateLimiter:
        return RateLimiter(self.redis)

    async def test_check_returns_not_locked_initially(self, limiter: RateLimiter):
        """Fresh IP+email should not be locked."""
        status = await limiter.check("10.0.0.1", "new@test.com")
        assert status.is_locked is False
        assert status.failures == 0

    async def test_record_failure_increments_counter(self, limiter: RateLimiter):
        """Recording failures increments the failure count."""
        await limiter.record_failure("10.0.0.1", "user@test.com")
        status = await limiter.check("10.0.0.1", "user@test.com")
        assert status.failures == 1

    async def test_lockout_after_exceeding_threshold(self, limiter: RateLimiter):
        """Lockout applies after exceeding the first threshold (5 failures)."""
        # 5 failures: at threshold, no lockout yet
        for _ in range(5):
            await limiter.record_failure("10.0.0.1", "user@test.com")
        
        status = await limiter.check("10.0.0.1", "user@test.com")
        assert status.is_locked is False, "At threshold: no lockout yet"

        # 6th failure: exceeds threshold, lockout applies
        await limiter.record_failure("10.0.0.1", "user@test.com")
        status = await limiter.check("10.0.0.1", "user@test.com")
        assert status.is_locked is True
        assert status.retry_after is not None
        assert status.retry_after > 0

    async def test_success_resets_counters(self, limiter: RateLimiter):
        """Successful login resets both IP and email failure counters."""
        # Build up some failures
        for _ in range(3):
            await limiter.record_failure("10.0.0.1", "user@test.com")
        
        # Verify failures are tracked
        status = await limiter.check("10.0.0.1", "user@test.com")
        assert status.failures == 3

        # Success resets
        await limiter.record_success("10.0.0.1", "user@test.com")
        status = await limiter.check("10.0.0.1", "user@test.com")
        assert status.is_locked is False
        assert status.failures == 0

    async def test_dual_key_ip_and_email(self, limiter: RateLimiter):
        """Lockout triggers on EITHER IP or email being locked."""
        # Lock the IP by failing with different emails
        for i in range(6):
            await limiter.record_failure("10.0.0.1", f"user{i}@test.com")
        
        # IP should be locked even though each email has only 1 failure
        status = await limiter.check("10.0.0.1", "any@test.com")
        assert status.is_locked is True

    async def test_dual_key_email_locked_from_different_ips(self, limiter: RateLimiter):
        """Email lockout persists even from different IPs."""
        # Lock the email from multiple IPs
        for i in range(6):
            await limiter.record_failure(f"10.0.0.{i}", "victim@test.com")
        
        # Email should be locked from any IP
        status = await limiter.check("10.99.99.99", "victim@test.com")
        assert status.is_locked is True

    async def test_lockout_extends_on_repeated_failures(self, limiter: RateLimiter):
        """If already locked, repeated failures extend the lockout window."""
        # Trigger initial lockout
        for _ in range(6):
            await limiter.record_failure("10.0.0.1", "user@test.com")
        
        status1 = await limiter.check("10.0.0.1", "user@test.com")
        assert status1.is_locked is True
        initial_retry = status1.retry_after

        # Another failure should extend the lockout
        await limiter.record_failure("10.0.0.1", "user@test.com")
        status2 = await limiter.check("10.0.0.1", "user@test.com")
        assert status2.is_locked is True
        # The lockout should be extended (or at least not shorter)
        assert status2.retry_after >= initial_retry - 1  # -1 for timing tolerance


# ---------------------------------------------------------------------------
# End-to-end tests with HTTP client
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRateLimitingE2E:
    """Test rate limiting through the actual HTTP endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def _cleanup_rate_limits(self, client: AsyncClient):
        """Clean up rate limit keys after each test."""
        yield
        redis_override = client._transport.app.dependency_overrides[get_redis]
        async for redis in redis_override():
            keys = await redis.keys("ratelimit:*")
            if keys:
                await redis.delete(*keys)
            break

    async def test_login_locked_returns_401_generic(self, client: AsyncClient, seed_data):
        """Rate-limited login returns 401 (not 429) for enumeration resistance."""
        # Trigger lockout: 6 failed attempts (exceeds threshold of 5)
        for i in range(6):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@alpha.test", "password": f"Wrong{i}!"},
            )
            assert resp.status_code == 401

        # 7th attempt: rate-limited, returns 401 (not 429)
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@alpha.test", "password": "WrongFinal!"},
        )
        assert resp.status_code == 401
        # Message should be generic, not revealing rate limit
        assert "rate" not in resp.json()["detail"].lower()
        assert "429" not in resp.json()["detail"]

    async def test_login_success_resets_rate_limit(self, client: AsyncClient, seed_data):
        """Successful login resets the rate limit counter."""
        # Build up failures (4, below threshold)
        for i in range(4):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@alpha.test", "password": f"Wrong{i}!"},
            )
            assert resp.status_code == 401

        # Successful login
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
        )
        assert resp.status_code == 200

        # Should be able to fail 5 more times before lockout
        for i in range(5):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@alpha.test", "password": f"Wrong{i}!"},
            )
            assert resp.status_code == 401

        # 6th failure: now locked
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@alpha.test", "password": "WrongFinal!"},
        )
        assert resp.status_code == 401  # locked

    async def test_different_emails_independent_rate_limits(self, client: AsyncClient, seed_data):
        """Rate limits are per-email AND per-IP (dual key).
        
        Note: In tests, all requests come from 127.0.0.1, so the IP gets locked
        after 6 total failures regardless of email. In production with different
        IPs, emails would be independent.
        """
        # Lock admin@alpha.test (6 failures from same IP)
        for i in range(6):
            await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@alpha.test", "password": f"Wrong{i}!"},
            )

        # IP is now locked, so analyst@alpha.test also gets blocked
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
        )
        # IP lockout affects all emails from that IP
        assert resp.status_code == 401

    async def test_rate_limit_message_matches_enum_resistance(self, client: AsyncClient, seed_data):
        """Rate-limited response is indistinguishable from wrong password."""
        # Wrong password (no lockout)
        resp_wrong = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@alpha.test", "password": "Wrong!"},
        )
        assert resp_wrong.status_code == 401

        # Trigger lockout
        for i in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"email": "viewer@alpha.test", "password": f"Wrong{i}!"},
            )

        # Rate-limited
        resp_limited = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@alpha.test", "password": "WrongFinal!"},
        )
        assert resp_limited.status_code == 401

        # Messages should be identical
        assert resp_wrong.json()["detail"] == resp_limited.json()["detail"]
