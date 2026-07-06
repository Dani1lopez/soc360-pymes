"""Regression tests for issue #133 — event bus busy-poll replaced by blocking XREADGROUP.

Root cause: the consumer loop used `read_pending()` + `asyncio.sleep(1)` to
poll for new messages. This caused unnecessary CPU wake-ups every second even
when no messages were available, and the sleep could swallow CancelledError.

Fix: use `xreadgroup(block=5000)` which blocks for up to 5 seconds waiting
for new messages, eliminating the busy-poll entirely.  Pending (unacked)
messages from a previous crash are still recovered by calling
``read_pending()`` before the blocking read on each iteration.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, call

import pytest


# ---------------------------------------------------------------------------
# read_new() — blocking XREADGROUP
# ---------------------------------------------------------------------------

class TestReadNewUsesBlockingXreadgroup:
    """Verify read_new() passes block=5000 to xreadgroup()."""

    @pytest.mark.asyncio
    async def test_read_new_passes_block_5000_to_xreadgroup(self):
        """read_new() MUST call xreadgroup with block=5000 by default."""
        from app.event_bus import EventConsumer

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=None)
        mock_redis.xgroup_create = AsyncMock()

        consumer = EventConsumer(
            redis_client=mock_redis,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )

        await consumer.read_new()

        mock_redis.xreadgroup.assert_awaited_once()
        call_kwargs = mock_redis.xreadgroup.call_args.kwargs
        assert call_kwargs.get("block") == 5000, (
            f"xreadgroup must be called with block=5000, got {call_kwargs.get('block')}"
        )

    @pytest.mark.asyncio
    async def test_read_new_uses_greater_than_id_for_new_messages(self):
        """read_new() MUST use '>' as the message ID to read only new messages."""
        from app.event_bus import EventConsumer

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=None)
        mock_redis.xgroup_create = AsyncMock()

        consumer = EventConsumer(
            redis_client=mock_redis,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )

        await consumer.read_new()

        call_args = mock_redis.xreadgroup.call_args
        # Third positional arg is the streams dict
        streams_dict = call_args.args[2]
        stream_key = f"events:{consumer.event_type}"
        assert streams_dict[stream_key] == ">", (
            f"read_new must use '>' for new messages, got {streams_dict[stream_key]}"
        )

    @pytest.mark.asyncio
    async def test_read_new_returns_empty_list_when_no_messages(self):
        """read_new() MUST return [] when xreadgroup returns None (timeout)."""
        from app.event_bus import EventConsumer

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=None)
        mock_redis.xgroup_create = AsyncMock()

        consumer = EventConsumer(
            redis_client=mock_redis,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )

        result = await consumer.read_new()
        assert result == []

    @pytest.mark.asyncio
    async def test_read_new_parses_messages_correctly(self):
        """read_new() MUST decode bytes fields and return list of dicts."""
        from app.event_bus import EventConsumer

        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        # Simulate xreadgroup returning one stream with two messages
        mock_redis.xreadgroup = AsyncMock(return_value=[
            (b"events:auth.login", [
                (b"100-0", {b"user_id": b"u1", b"email_hash": b"a" * 32}),
                (b"101-0", {b"user_id": b"u2", b"email_hash": b"b" * 32}),
            ]),
        ])

        consumer = EventConsumer(
            redis_client=mock_redis,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )

        result = await consumer.read_new()
        assert len(result) == 2
        assert result[0]["message_id"] == b"100-0"
        assert result[0]["data"]["user_id"] == "u1"
        assert result[1]["message_id"] == b"101-0"
        assert result[1]["data"]["user_id"] == "u2"

    @pytest.mark.asyncio
    async def test_read_new_accepts_custom_block_value(self):
        """read_new() MUST allow overriding the block timeout."""
        from app.event_bus import EventConsumer

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=None)
        mock_redis.xgroup_create = AsyncMock()

        consumer = EventConsumer(
            redis_client=mock_redis,
            event_type="auth.login",
            consumer_name="worker-1",
            group_name="soc360-consumers",
        )

        await consumer.read_new(block=1000)

        call_kwargs = mock_redis.xreadgroup.call_args.kwargs
        assert call_kwargs.get("block") == 1000


# ---------------------------------------------------------------------------
# _consumer_loop — runtime behaviour (no source inspection)
# ---------------------------------------------------------------------------

class TestConsumerLoopRuntimeBehavior:
    """Runtime tests for _consumer_loop — no inspect.getsource().

    These tests drive the loop with mocks and verify *what it calls*,
    not what its source code looks like.
    """

    @pytest.mark.asyncio
    async def test_consumer_loop_calls_read_new_with_block(self):
        """_consumer_loop MUST call consumer.read_new() with a blocking timeout."""
        from app.main import _consumer_loop, _XREADGROUP_BLOCK_MS

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_consumer = AsyncMock()
        mock_consumer.read_pending = AsyncMock(return_value=[])
        # Stop after 2 iterations by raising StopAsyncIteration.
        call_count = 0

        async def read_new_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            return []

        mock_consumer.read_new = AsyncMock(side_effect=read_new_side_effect)

        stop_event = asyncio.Event()

        with pytest.raises(asyncio.CancelledError):
            await _consumer_loop(
                redis_client=mock_redis,
                consumer=mock_consumer,
                stop_event=stop_event,
            )

        # read_new must have been called with the configured block timeout.
        mock_consumer.read_new.assert_awaited()
        call_kwargs = mock_consumer.read_new.call_args.kwargs
        assert call_kwargs.get("block") == _XREADGROUP_BLOCK_MS

    @pytest.mark.asyncio
    async def test_consumer_loop_recovers_pending_before_blocking(self):
        """_consumer_loop MUST drain pending messages before calling read_new().

        When pending messages exist, the loop must process them and NOT call
        read_new() for that iteration — pending recovery takes priority.
        """
        from app.main import _consumer_loop

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        pending_msg = {
            "message_id": b"50-0",
            "data": {"user_id": "pending-user"},
        }

        # Iteration 1: pending exists → process it, no read_new.
        # Iteration 2: no pending → read_new called, then stop.
        iteration = 0

        async def read_pending_side_effect():
            nonlocal iteration
            iteration += 1
            if iteration == 1:
                return [pending_msg]
            # After iteration 2, stop the loop.
            raise asyncio.CancelledError()

        mock_consumer = AsyncMock()
        mock_consumer.read_pending = AsyncMock(side_effect=read_pending_side_effect)
        mock_consumer.read_new = AsyncMock(return_value=[])

        stop_event = asyncio.Event()

        with pytest.raises(asyncio.CancelledError):
            await _consumer_loop(
                redis_client=mock_redis,
                consumer=mock_consumer,
                stop_event=stop_event,
            )

        # read_pending was called at least twice (iteration 1 + iteration 2).
        assert mock_consumer.read_pending.await_count >= 2

        # On iteration 1, pending was non-empty, so read_new should NOT
        # have been called.  On iteration 2, pending raised CancelledError
        # before read_new.  So read_new should have 0 calls.
        assert mock_consumer.read_new.await_count == 0, (
            "read_new must NOT be called when pending messages exist"
        )

        # The pending message must have been acked.
        mock_consumer.ack.assert_awaited()

    @pytest.mark.asyncio
    async def test_consumer_loop_no_sleep_1_busy_poll(self):
        """_consumer_loop MUST NOT call asyncio.sleep(1) — the old busy-poll.

        Drives the loop with a mock that returns no messages and verifies
        that asyncio.sleep is never called with 1.0 seconds.
        """
        from app.main import _consumer_loop

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        call_count = 0

        async def read_new_then_stop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            return []

        mock_consumer = AsyncMock()
        mock_consumer.read_pending = AsyncMock(return_value=[])
        mock_consumer.read_new = AsyncMock(side_effect=read_new_then_stop)

        stop_event = asyncio.Event()
        sleep_calls: list[float] = []

        original_sleep = asyncio.sleep

        async def tracking_sleep(delay: float, *args, **kwargs):
            sleep_calls.append(delay)
            await original_sleep(0)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(asyncio, "sleep", tracking_sleep)
            with pytest.raises(asyncio.CancelledError):
                await _consumer_loop(
                    redis_client=mock_redis,
                    consumer=mock_consumer,
                    stop_event=stop_event,
                )

        # No sleep(1) call must appear — the old busy-poll is gone.
        assert not any(d == 1.0 for d in sleep_calls), (
            f"asyncio.sleep(1) busy-poll detected in calls: {sleep_calls}"
        )


# ---------------------------------------------------------------------------
# _consumer_loop — cancellation
# ---------------------------------------------------------------------------

class TestConsumerLoopCancellation:
    """Verify _consumer_loop properly handles asyncio.CancelledError."""

    @pytest.mark.asyncio
    async def test_cancelled_error_is_reraised(self):
        """_consumer_loop MUST re-raise asyncio.CancelledError after logging."""
        from app.main import _consumer_loop

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_consumer = AsyncMock()
        # read_pending raises CancelledError to simulate task cancellation
        mock_consumer.read_pending = AsyncMock(side_effect=asyncio.CancelledError())

        stop_event = asyncio.Event()

        with pytest.raises(asyncio.CancelledError):
            await _consumer_loop(
                redis_client=mock_redis,
                consumer=mock_consumer,
                stop_event=stop_event,
            )

        # Redis client must still be closed in the finally block
        mock_redis.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancelled_error_triggers_cleanup(self):
        """_consumer_loop MUST run finally block (aclose) even on CancelledError."""
        from app.main import _consumer_loop

        mock_redis = AsyncMock()
        close_called = False

        async def track_close():
            nonlocal close_called
            close_called = True

        mock_redis.aclose = track_close

        mock_consumer = AsyncMock()
        mock_consumer.read_pending = AsyncMock(side_effect=asyncio.CancelledError())

        stop_event = asyncio.Event()

        with pytest.raises(asyncio.CancelledError):
            await _consumer_loop(
                redis_client=mock_redis,
                consumer=mock_consumer,
                stop_event=stop_event,
            )

        assert close_called, "Redis client must be closed even on CancelledError"


# ---------------------------------------------------------------------------
# _consumer_loop — error backoff (non-cancellation)
# ---------------------------------------------------------------------------

class TestConsumerLoopErrorBackoff:
    """Verify _consumer_loop backs off on unexpected errors instead of busy-looping."""

    @pytest.mark.asyncio
    async def test_error_triggers_backoff_sleep(self):
        """After an unexpected error, _consumer_loop MUST sleep before retrying.

        This ensures the failure path does not become a tight busy loop.
        """
        from app.main import _consumer_loop, _ERROR_BACKOFF_SECONDS

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        call_count = 0

        async def fail_then_stop():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("transient failure")
            # Third call: stop the loop.
            raise asyncio.CancelledError()

        mock_consumer = AsyncMock()
        mock_consumer.read_pending = AsyncMock(side_effect=fail_then_stop)
        mock_consumer.read_new = AsyncMock(return_value=[])

        stop_event = asyncio.Event()
        sleep_durations: list[float] = []

        original_sleep = asyncio.sleep

        async def tracking_sleep(delay: float, *args, **kwargs):
            sleep_durations.append(delay)
            await original_sleep(0)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(asyncio, "sleep", tracking_sleep)
            with pytest.raises(asyncio.CancelledError):
                await _consumer_loop(
                    redis_client=mock_redis,
                    consumer=mock_consumer,
                    stop_event=stop_event,
                )

        # At least one backoff sleep must have occurred.
        assert len(sleep_durations) >= 1, "Expected at least one backoff sleep after errors"
        # The backoff must match the configured constant.
        assert all(d == _ERROR_BACKOFF_SECONDS for d in sleep_durations), (
            f"Expected backoff of {_ERROR_BACKOFF_SECONDS}s, got {sleep_durations}"
        )
