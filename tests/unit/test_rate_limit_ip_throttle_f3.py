"""Unit tests for F3: fixed-window per-IP throttle behavior in RateLimiter."""

from __future__ import annotations

import pytest
from fakeredis.aioredis import FakeRedis

from app.core import rate_limit as rate_limit_module
from app.core.config import settings
from app.core.rate_limit import _IP_PREFIX, _IP_THROTTLE_THRESHOLD, RateLimiter


@pytest.mark.asyncio
async def test_ip_throttle_resets_window_after_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After an IP throttle expires, the IP gets a fresh threshold before re-throttling."""
    redis = FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis)
    now = 1_000_000.0
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: now)

    ip = "198.51.100.50"
    for i in range(_IP_THROTTLE_THRESHOLD + 1):
        status = await limiter.record_failure(
            ip, f"u{i}@example.com", record_email=False
        )

    assert status.is_locked is True
    assert status.retry_after == settings.RATE_LIMIT_IP_THROTTLE_SECONDS

    # Advance time past the fixed throttle window
    now += settings.RATE_LIMIT_IP_THROTTLE_SECONDS + 1

    # Next single failure must NOT immediately re-lock the IP; it starts at failure 1.
    after_expiry = await limiter.record_failure(
        ip, "fresh@example.com", record_email=False
    )
    assert after_expiry.is_locked is False
    assert after_expiry.failures == 1

    # Up to _IP_THROTTLE_THRESHOLD failures remain unlocked
    for i in range(2, _IP_THROTTLE_THRESHOLD + 1):
        mid = await limiter.record_failure(ip, f"m{i}@example.com", record_email=False)
        assert mid.is_locked is False
        assert mid.failures == i

    # Exceeding the threshold again triggers a fresh throttle window
    relocked = await limiter.record_failure(ip, "over@example.com", record_email=False)
    assert relocked.is_locked is True
    assert relocked.retry_after == settings.RATE_LIMIT_IP_THROTTLE_SECONDS


@pytest.mark.asyncio
async def test_ip_bucket_uses_bounded_fixed_window_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The IP bucket TTL stays bounded to RATE_LIMIT_IP_THROTTLE_SECONDS, not 25h."""
    redis = FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis)
    now = 2_000_000.0
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: now)

    ip = "198.51.100.51"
    ip_key = f"{_IP_PREFIX}{ip}"

    await limiter.record_failure(ip, "a@example.com", record_email=False)
    ttl_initial = await redis.ttl(ip_key)
    assert 0 < ttl_initial <= settings.RATE_LIMIT_IP_THROTTLE_SECONDS

    # Simulate 30s passing without exceeding threshold; subsequent failure must not
    # extend the counting window TTL back to full window_seconds.
    await redis.expire(ip_key, 30)
    await limiter.record_failure(ip, "b@example.com", record_email=False)
    ttl_after = await redis.ttl(ip_key)
    assert 0 < ttl_after <= 30


@pytest.mark.asyncio
async def test_ip_throttle_does_not_extend_while_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sustained failures while IP throttle is active do not extend locked_until."""
    redis = FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis)
    now = 3_000_000.0
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: now)

    ip = "198.51.100.52"
    for i in range(_IP_THROTTLE_THRESHOLD + 1):
        await limiter.record_failure(ip, f"s{i}@example.com", record_email=False)

    first = await limiter.check(ip, "legit@example.com")
    assert first.is_locked is True
    assert first.retry_after == settings.RATE_LIMIT_IP_THROTTLE_SECONDS

    # Advance 20s and send more failures
    now += 20
    for i in range(10):
        await limiter.record_failure(ip, f"more{i}@example.com", record_email=False)

    second = await limiter.check(ip, "legit@example.com")
    assert second.is_locked is True
    assert second.retry_after == settings.RATE_LIMIT_IP_THROTTLE_SECONDS - 20


@pytest.mark.asyncio
async def test_check_returns_at_least_one_second_retry_after_when_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sub-second remaining lockout still reports retry_after >= 1."""
    redis = FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis)
    now = 4_000_000.0
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: now)

    ip = "198.51.100.53"
    for i in range(_IP_THROTTLE_THRESHOLD + 1):
        await limiter.record_failure(ip, f"sub{i}@example.com", record_email=False)

    now += settings.RATE_LIMIT_IP_THROTTLE_SECONDS - 0.4
    status = await limiter.check(ip, "legit@example.com")
    assert status.is_locked is True
    assert status.retry_after == 1
