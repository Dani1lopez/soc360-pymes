"""Tests for app/core/redis.py ping_redis_with_retry — issue #128.

The FastAPI lifespan calls this helper once at startup. We mock the inner
`ping_redis` (which performs the actual network round-trip) so these tests
run without a real Redis. Backoff sleeps are also patched out for speed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestPingRedisWithRetry:
    """Validate retry behavior of ping_redis_with_retry."""

    @pytest.mark.asyncio
    async def test_returns_true_on_first_success(self):
        """Single successful ping → returns True, no backoff, no extra calls."""
        from app.core.redis import ping_redis_with_retry

        with patch("app.core.redis.ping_redis", AsyncMock(return_value=True)) as mock_ping:
            with patch("app.core.redis.asyncio.sleep", AsyncMock()) as mock_sleep:
                result = await ping_redis_with_retry(
                    max_attempts=3,
                    backoff_base_seconds=0.01,
                )
                assert result is True
                assert mock_ping.call_count == 1
                mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_transient_failure_then_succeeds(self):
        """Two failed pings followed by success → returns True, 3 attempts, 2 backoffs."""
        from app.core.redis import ping_redis_with_retry

        call_count = 0

        async def flaky_ping():
            nonlocal call_count
            call_count += 1
            return call_count >= 3

        with patch("app.core.redis.ping_redis", flaky_ping):
            with patch("app.core.redis.asyncio.sleep", AsyncMock()) as mock_sleep:
                result = await ping_redis_with_retry(
                    max_attempts=3,
                    backoff_base_seconds=0.01,
                )
                assert result is True
                assert call_count == 3
                # Backoff between attempts 1→2 and 2→3; none after the success
                assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_false_after_exhausting_attempts(self):
        """All pings fail → returns False, no backoff after the last attempt."""
        from app.core.redis import ping_redis_with_retry

        with patch("app.core.redis.ping_redis", AsyncMock(return_value=False)) as mock_ping:
            with patch("app.core.redis.asyncio.sleep", AsyncMock()) as mock_sleep:
                result = await ping_redis_with_retry(
                    max_attempts=3,
                    backoff_base_seconds=0.01,
                )
                assert result is False
                assert mock_ping.call_count == 3
                # Backoff only between attempts; none after the final failure
                assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_raised_connection_error(self):
        """A raised exception is treated the same as a falsy ping — retry happens."""
        from app.core.redis import ping_redis_with_retry

        call_count = 0

        async def ping_that_recovers():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("redis is down")
            return True

        with patch("app.core.redis.ping_redis", ping_that_recovers):
            with patch("app.core.redis.asyncio.sleep", AsyncMock()):
                result = await ping_redis_with_retry(
                    max_attempts=3,
                    backoff_base_seconds=0.01,
                )
                assert result is True
                assert call_count == 2

    @pytest.mark.asyncio
    async def test_exponential_backoff_schedule(self):
        """Backoff follows 2**(attempt-1) * base (default 1s, 2s, 4s)."""
        from app.core.redis import ping_redis_with_retry

        sleep_calls: list[float] = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("app.core.redis.ping_redis", AsyncMock(return_value=False)):
            with patch("app.core.redis.asyncio.sleep", side_effect=fake_sleep):
                await ping_redis_with_retry(
                    max_attempts=3,
                    backoff_base_seconds=1.0,
                )
        assert sleep_calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_logs_each_failure_with_error_type(self):
        """Each failed attempt logs the underlying error_type (no swallow)."""
        from app.core.redis import ping_redis_with_retry

        with patch("app.core.redis.ping_redis", AsyncMock(side_effect=TimeoutError("slow"))):
            with patch("app.core.redis.asyncio.sleep", AsyncMock()):
                with patch("app.core.redis.logger") as mock_logger:
                    result = await ping_redis_with_retry(
                        max_attempts=2,
                        backoff_base_seconds=0.01,
                    )
                    assert result is False
                    # Two warnings for the two failing attempts (attempt 1 retries, attempt 2 exhausts)
                    assert mock_logger.warning.call_count == 1
                    assert mock_logger.error.call_count == 1
                    warning_kwargs = mock_logger.warning.call_args.kwargs
                    assert warning_kwargs["error_type"] == "TimeoutError"
                    assert "slow" in warning_kwargs["error"]
                    error_kwargs = mock_logger.error.call_args.kwargs
                    assert error_kwargs["error_type"] == "TimeoutError"
                    assert error_kwargs["attempt"] == 2
                    assert error_kwargs["max_attempts"] == 2
