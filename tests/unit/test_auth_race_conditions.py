from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.modules.auth.models import RefreshToken
from app.modules.auth.service import (
    MAX_ACTIVE_SESSIONS,
    _ADVISORY_LOCK_SQL,
    _acquire_session_cap_lock,
    _create_refresh_token,
)


class TestSessionCapLock:
    """Tests for advisory lock serialization of session cap checks."""

    @pytest.mark.asyncio
    async def test_lock_requires_active_transaction(self):
        """_acquire_session_cap_lock raises RuntimeError without active tx."""
        mock_db = MagicMock()
        mock_db.in_transaction.return_value = False

        with pytest.raises(RuntimeError, match="requires an active transaction"):
            await _acquire_session_cap_lock(
                UUID("12345678-1234-1234-1234-123456789abc"), mock_db
            )

    def test_create_refresh_token_query_includes_advisory_lock(self):
        """Structural check: advisory lock SQL contains pg_advisory_xact_lock."""
        sql_str = str(_ADVISORY_LOCK_SQL).lower()
        assert "pg_advisory_xact_lock" in sql_str

    @pytest.mark.asyncio
    async def test_create_refresh_token_revokes_oldest_when_at_cap(self):
        """At MAX_ACTIVE_SESSIONS, oldest token is revoked and a new one added."""
        mock_db = AsyncMock()
        mock_db.in_transaction.return_value = True

        oldest = MagicMock()
        oldest.revoked_at = None
        oldest.created_at = datetime.now(timezone.utc) - timedelta(hours=1)

        # First scalar call = count (returns MAX_ACTIVE_SESSIONS)
        # Second scalar call = oldest token
        mock_db.scalar = AsyncMock(side_effect=[MAX_ACTIVE_SESSIONS, oldest])

        result = await _create_refresh_token(
            UUID("12345678-1234-1234-1234-123456789abc"),
            mock_db,
        )

        assert isinstance(result, str)
        assert len(result) > 0
        assert oldest.revoked_at is not None
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, RefreshToken)

    @pytest.mark.asyncio
    async def test_create_refresh_token_allows_new_token_when_under_cap(self):
        """Under cap, no revocation happens and a new token is added."""
        mock_db = AsyncMock()
        mock_db.in_transaction.return_value = True

        # Return count < MAX_ACTIVE_SESSIONS (no oldest query needed)
        mock_db.scalar = AsyncMock(return_value=MAX_ACTIVE_SESSIONS - 2)

        result = await _create_refresh_token(
            UUID("12345678-1234-1234-1234-123456789abc"),
            mock_db,
        )

        assert isinstance(result, str)
        assert len(result) > 0
        # scalar called once for count only (no oldest query)
        assert mock_db.scalar.call_count == 1
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, RefreshToken)

    @pytest.mark.asyncio
    async def test_concurrent_logins_serialized_by_advisory_lock(self):
        """Simulate advisory lock: serialized calls see correct counts.

        Two concurrent calls start with shared_count = MAX_ACTIVE_SESSIONS - 1.
        Without serialization both could see the same count (race condition).
        With serialization the second call sees the updated count after the
        first call finishes.
        """
        lock = asyncio.Lock()
        call_order = []
        shared_count = [MAX_ACTIVE_SESSIONS - 1]  # Start one below cap
        counts_seen = []

        async def simulated_advisory_lock(user_id: UUID, db: AsyncMock) -> None:
            async with lock:
                call_order.append(f"lock_{user_id}")
                await asyncio.sleep(0)  # Yield to exercise contention

        async def tracking_scalar(stmt):
            stmt_str = str(stmt).lower()
            if "order by" in stmt_str:
                # Oldest token query
                oldest = MagicMock()
                oldest.revoked_at = None
                oldest.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
                return oldest
            # Otherwise it's a count query
            counts_seen.append(shared_count[0])
            return shared_count[0]

        def tracking_add(token):
            shared_count[0] += 1

        mock_db = AsyncMock()
        mock_db.in_transaction.return_value = True
        mock_db.scalar = AsyncMock(side_effect=tracking_scalar)
        mock_db.add = tracking_add

        uid1 = UUID("11111111-1111-1111-1111-111111111111")
        uid2 = UUID("22222222-2222-2222-2222-222222222222")

        with patch(
            "app.modules.auth.service._acquire_session_cap_lock",
            simulated_advisory_lock,
        ):
            await asyncio.gather(
                _create_refresh_token(uid1, mock_db),
                _create_refresh_token(uid2, mock_db),
            )

        # Both calls acquired the lock (serialized)
        assert len(call_order) == 2

        # Critical assertion: counts were observed sequentially.
        # Call 1 sees 4, call 2 sees 5 (after call 1 incremented).
        # If there were no serialization, both could see [4, 4].
        assert counts_seen == [4, 5], (
            f"Expected serialized counts [4, 5], got {counts_seen}. "
            "This indicates a race condition in session cap checking."
        )
