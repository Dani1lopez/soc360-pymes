"""Progressive lockout rate limiter for auth endpoints.

Design: dual-key lockout (IP + email) with two different policies.
- Failed attempts are tracked per IP and per email hash.
- The per-account (email) bucket escalates: 3min → 15min → 1h → 4h → 24h.
- The per-IP bucket only throttles for one short, fixed, non-escalating
  window: an IP is often shared (office NAT, carrier CGNAT, the compose
  network), so it must never hard-lock every user behind it.
- Successful login resets the failure counter.
- Lockout message is generic (doesn't reveal the duration).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
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
    (5, 3 * 60),  # 5 failures  → 3 min
    (10, 15 * 60),  # 10 failures → 15 min
    (15, 60 * 60),  # 15 failures → 1 hour
    (20, 4 * 60 * 60),  # 20 failures → 4 hours
    (25, 24 * 60 * 60),  # 25 failures → 24 hours
]

# Per-IP throttle: fixed, non-escalating window. One IP is shared by many
# users, so exceeding the first threshold only delays requests for a short
# while instead of applying the escalating account lockout above.
_IP_THROTTLE_THRESHOLD = 5


def _hash_email(email: str) -> str:
    """Hash email for Redis key — no PII stored."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]


def _get_hash_field(
    data: Mapping[str | bytes, str | bytes], field: str
) -> str | bytes | int:
    """Read a Redis hash field from text- or bytes-mode responses."""
    if field in data:
        return data[field]
    return data.get(field.encode(), 0)


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


def _get_ip_throttle_seconds(failures: int) -> int:
    """Return the per-IP throttle duration (0 = not throttled).

    Deliberately NOT escalating: a shared IP is throttled for one short fixed
    window, so an attacker spraying accounts can never lock every user of that
    IP out for hours.
    """
    if failures > _IP_THROTTLE_THRESHOLD:
        return settings.RATE_LIMIT_IP_THROTTLE_SECONDS
    return 0


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
        ip_locked_until = float(_get_hash_field(ip_data, "locked_until"))
        if ip_locked_until > now:
            remaining = max(1, int(ip_locked_until - now))
            logger.warning(
                "rate_limit_locked", key_type="ip", ip=ip, retry_after=remaining
            )
            return LockoutStatus(
                is_locked=True,
                retry_after=remaining,
                failures=int(_get_hash_field(ip_data, "failures")),
            )

        # Check email lockout
        email_locked_until = float(_get_hash_field(email_data, "locked_until"))
        if email_locked_until > now:
            remaining = max(1, int(email_locked_until - now))
            logger.warning(
                "rate_limit_locked",
                key_type="email",
                email_hash=_hash_email(email),
                retry_after=remaining,
            )
            return LockoutStatus(
                is_locked=True,
                retry_after=remaining,
                failures=int(_get_hash_field(email_data, "failures")),
            )

        # Not locked — return current failure count
        max_failures = max(
            int(_get_hash_field(ip_data, "failures")),
            int(_get_hash_field(email_data, "failures")),
        )
        return LockoutStatus(is_locked=False, failures=max_failures)

    async def record_failure(
        self,
        ip: str,
        email: str,
        *,
        record_email: bool = True,
    ) -> LockoutStatus:
        """Record a failed login attempt for IP and optionally email.

        The email bucket escalates and extends an active lockout. The IP bucket
        only ever applies one fixed short throttle window and never extends it
        while it is active, so a shared IP cannot be hard-locked. When
        ``record_email`` is False (e.g., unknown account), only the IP bucket
        is updated so non-existent emails do not bloat Redis.
        """
        ip_key = f"{_IP_PREFIX}{ip}"
        email_key = f"{_EMAIL_PREFIX}{_hash_email(email)}"
        now = time.time()

        await self._record_ip_failure(ip_key, now)
        if record_email:
            await self._record_email_failure(email_key, now)

        # Return the combined status
        return await self.check(ip, email)

    async def _record_ip_failure(self, ip_key: str, now: float) -> None:
        """Record a failed attempt in the fixed-window per-IP throttle bucket."""
        current_locked = float(await self._redis.hget(ip_key, "locked_until") or 0)
        if current_locked > now:
            # Fixed window is active: sustained failures cannot stretch locked_until or TTL.
            await self._redis.hincrby(ip_key, "failures", 1)
            return

        if current_locked > 0:
            # Previous throttle window expired: start a fresh counting window.
            await self._redis.delete(ip_key)

        failures = await self._redis.hincrby(ip_key, "failures", 1)
        window_seconds = settings.RATE_LIMIT_IP_THROTTLE_SECONDS
        if failures == 1 or await self._redis.ttl(ip_key) < 0:
            await self._redis.expire(ip_key, window_seconds)

        throttle_seconds = _get_ip_throttle_seconds(failures)
        if throttle_seconds <= 0:
            return

        await self._redis.hset(ip_key, "locked_until", str(now + throttle_seconds))
        await self._redis.expire(ip_key, throttle_seconds)
        logger.warning(
            "rate_limit_ip_throttled",
            failures=failures,
            throttle_seconds=throttle_seconds,
        )

    async def _record_email_failure(self, email_key: str, now: float) -> None:
        """Record a failed attempt in the escalating per-email lockout bucket."""
        failures = await self._redis.hincrby(email_key, "failures", 1)
        await self._redis.expire(email_key, settings.RATE_LIMIT_WINDOW_SECONDS + 3600)

        lockout_seconds = _get_lockout_seconds(failures)
        if lockout_seconds > 0:
            # If already locked, extend from current locked_until
            current_locked = float(
                await self._redis.hget(email_key, "locked_until") or 0
            )
            base_time = max(now, current_locked)
            new_locked_until = base_time + lockout_seconds

            await self._redis.hset(email_key, "locked_until", str(new_locked_until))
            logger.warning(
                "rate_limit_lockout_applied",
                key=email_key.split(":")[1],  # "email"
                failures=failures,
                lockout_seconds=lockout_seconds,
                locked_until=new_locked_until,
            )

    async def record_success(self, ip: str, email: str) -> None:
        """Reset failure counters after successful login.

        Clears both IP and email failure tracking.
        """
        ip_key = f"{_IP_PREFIX}{ip}"
        email_key = f"{_EMAIL_PREFIX}{_hash_email(email)}"

        await self._redis.delete(ip_key)
        await self._redis.delete(email_key)

        logger.info("rate_limit_reset", ip=ip, email_hash=_hash_email(email))


_USER_PREFIX = "ratelimit:user:"


@dataclass
class UserRateLimitStatus:
    """Result of a per-user fixed-window rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int = 0


class UserRateLimiter:
    """Fixed-window per-user rate limiter backed by Redis."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check_and_increment(
        self,
        user_id: str,
        bucket: str,
        limit: int,
        window_seconds: int,
    ) -> UserRateLimitStatus:
        """Increment the user's bucket counter and check against ``limit``."""
        key = f"{_USER_PREFIX}{bucket}:{user_id}"
        count = await self._redis.incr(key)
        ttl: int | None = None
        if count == 1:
            await self._redis.expire(key, window_seconds)
            ttl = window_seconds
        else:
            ttl = await self._redis.ttl(key)
            if ttl < 0:
                await self._redis.expire(key, window_seconds)
                ttl = window_seconds

        if count > limit:
            retry_after = max(1, int(ttl) if ttl and ttl > 0 else window_seconds)
            logger.warning(
                "user_rate_limit_exceeded",
                user_id=user_id,
                bucket=bucket,
                count=count,
                limit=limit,
                retry_after=retry_after,
            )
            return UserRateLimitStatus(
                allowed=False,
                limit=limit,
                remaining=0,
                retry_after=retry_after,
            )

        return UserRateLimitStatus(
            allowed=True,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after=0,
        )
