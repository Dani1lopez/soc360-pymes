from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import _acquire_session_cap_lock

ADMIN_A = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.mark.asyncio
async def test_advisory_lock_emits_correct_sql():
    """Verify _acquire_session_cap_lock emits lock_timeout then advisory lock SQL."""
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.in_transaction.return_value = True
    mock_db.execute = AsyncMock()

    await _acquire_session_cap_lock(ADMIN_A, mock_db)

    # Two executes: first SET LOCAL lock_timeout, then pg_advisory_xact_lock.
    assert mock_db.execute.await_count == 2

    # First call: lock_timeout SET with transaction-local flag.
    first_call = mock_db.execute.call_args_list[0]
    first_sql = str(first_call[0][0]).lower()
    assert "set_config" in first_sql
    assert "lock_timeout" in first_sql
    first_params = first_call[0][1]
    assert "timeout_ms" in first_params

    # Second call: advisory lock.
    second_call = mock_db.execute.call_args_list[1]
    second_sql = str(second_call[0][0])
    assert "pg_advisory_xact_lock" in second_sql
    assert "hashtextextended" in second_sql
    second_params = second_call[0][1]
    assert second_params["user_id"] == str(ADMIN_A)


@pytest.mark.asyncio
async def test_advisory_lock_raises_outside_transaction():
    """Advisory lock must refuse to run outside an active transaction."""
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.in_transaction.return_value = False

    with pytest.raises(RuntimeError, match="active transaction"):
        await _acquire_session_cap_lock(ADMIN_A, mock_db)
