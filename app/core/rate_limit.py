"""Progressive lockout rate limiter for auth endpoints.

Design: dual-key lockout (IP + email) with escalating timeouts.
- Failed attempts are tracked per IP and per email hash.
- Lockout duration escalates with each batch of failures.
- Successful login resets the failure counter.
- Lockout message is generic (doesn't reveal the duration).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Redis key prefixes
_IP_PREFIX = "ratelimit:ip:"
_EMAIL_PREFIX = "ratelimit:email:"

# Lockout escalation table: (threshold, lockout_seconds)
# When cumulative failures reach `threshold`, lockout is `lockout_seconds`.
_LOCKOUT_TABLE: list[tuple[int, int]] = [
    (5, 3 * 60),         # 5 failures  → 3 min
    (10, 15 * 60),       # 10 failures → 15 min
    (15, 60 * 60),       # 15 failures → 1 hour
    (20, 4 * 60 * 60),   # 20 failures → 4 hours
    (25, 24 * 60 * 60),  # 25 failures → 24 hours
]


def _hash_email(email: str) -> str:
    """Hash email for Redis key — no PII stored."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]


def _get_lockout_seconds(failures: int) -> int:
    """Return lockout duration for the given failure count.

    Returns 0 if no lockout threshold has been reached.
    For failures beyond the last threshold, uses the max lockout (24h).
    
    Lockout only applies when failures EXCEED the threshold, not when they
    equal it. This allows one more attempt at the threshold before locking.
    """
    # Find the highest threshold that failures has exceeded
    result = 0
    for threshold, seconds in _LOCKOUT_TABLE:
        if failures > threshold:
            result = seconds
        else:
            break
    return result


@dataclass
class LockoutStatus:
    """Result of a rate limit check."""
    is_locked: bool
    retry_after: int | None = None  # seconds until unlock, None if not locked
    failures: int = 0


class RateLimiter:
    """Progressive lockout rate limiter backed by Redis.

    Usage:
        limiter = RateLimiter(redis_client)
        status = await limiter.check("192.168.1.1", "user@example.com")
        if status.is_locked:
            raise HTTPException(429, detail="Too many attempts")

        # After failed login:
        await limiter.record_failure("192.168.1.1", "user@example.com")

        # After successful login:
        await limiter.record_success("192.168.1.1", "user@example.com")
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(self, ip: str, email: str) -> LockoutStatus:
        """Check if IP or email is currently locked out.

        Returns LockoutStatus with is_locked=True if either key is locked.
        """
        ip_key = f"{_IP_PREFIX}{ip}"
        email_key = f"{_EMAIL_PREFIX}{_hash_email(email)}"

        # Check both keys in parallel
        ip_data = await self._redis.hgetall(ip_key)
        email_data = await self._redis.hgetall(email_key)

        now = time.time()

        # Check IP lockout
        ip_locked_until = float(ip_data.get(b"locked_until", 0))
        if ip_locked_until > now:
            remaining = int(ip_locked_until - now)
            logger.warning("rate_limit_locked", key_type="ip", ip=ip, retry_after=remaining)
            return LockoutStatus(is_locked=True, retry_after=remaining,
                                 failures=int(ip_data.get(b"failures", 0)))

        # Check email lockout
        email_locked_until = float(email_data.get(b"locked_until", 0))
        if email_locked_until > now:
            remaining = int(email_locked_until - now)
            logger.warning("rate_limit_locked", key_type="email",
                           email_hash=_hash_email(email), retry_after=remaining)
            return LockoutStatus(is_locked=True, retry_after=remaining,
                                 failures=int(email_data.get(b"failures", 0)))

        # Not locked — return current failure count
        max_failures = max(
            int(ip_data.get(b"failures", 0)),
            int(email_data.get(b"failures", 0)),
        )
        return LockoutStatus(is_locked=False, failures=max_failures)

    async def record_failure(self, ip: str, email: str) -> LockoutStatus:
        """Record a failed login attempt for both IP and email.

        Increments failure counters and applies lockout if threshold reached.
        If already locked, extends the lockout window.
        """
        ip_key = f"{_IP_PREFIX}{ip}"
        email_key = f"{_EMAIL_PREFIX}{_hash_email(email)}"
        now = time.time()

        for key in (ip_key, email_key):
            # Increment failure count atomically
            failures = await self._redis.hincrby(key, "failures", 1)
            # Set TTL for auto-cleanup (24h + buffer)
            await self._redis.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS + 3600)

            # Check if we should lock
            lockout_seconds = _get_lockout_seconds(failures)
            if lockout_seconds > 0:
                # If already locked, extend from current locked_until
                current_locked = float(await self._redis.hget(key, "locked_until") or 0)
                base_time = max(now, current_locked)
                new_locked_until = base_time + lockout_seconds

                await self._redis.hset(key, "locked_until", str(new_locked_until))
                logger.warning(
                    "rate_limit_lockout_applied",
                    key=key.split(":")[1],  # "ip" or "email"
                    failures=failures,
                    lockout_seconds=lockout_seconds,
                    locked_until=new_locked_until,
                )

        # Return the combined status
        return await self.check(ip, email)

    async def record_success(self, ip: str, email: str) -> None:
        """Reset failure counters after successful login.

        Clears both IP and email failure tracking.
        """
        ip_key = f"{_IP_PREFIX}{ip}"
        email_key = f"{_EMAIL_PREFIX}{_hash_email(email)}"

        await self._redis.delete(ip_key)
        await self._redis.delete(email_key)

        logger.info("rate_limit_reset", ip=ip, email_hash=_hash_email(email))
