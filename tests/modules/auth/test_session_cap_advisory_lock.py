from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import _acquire_session_cap_lock

ADMIN_A = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.mark.asyncio
async def test_advisory_lock_emits_correct_sql():
    """Verify _acquire_session_cap_lock emits pg_advisory_xact_lock SQL."""
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.in_transaction.return_value = True
    mock_db.execute = AsyncMock()

    await _acquire_session_cap_lock(ADMIN_A, mock_db)

    mock_db.execute.assert_awaited_once()
    call_args = mock_db.execute.call_args
    sql_text = str(call_args[0][0])
    assert "pg_advisory_xact_lock" in sql_text
    assert "hashtextextended" in sql_text
    params = call_args[0][1]
    assert params["user_id"] == str(ADMIN_A)


@pytest.mark.asyncio
async def test_advisory_lock_raises_outside_transaction():
    """Advisory lock must refuse to run outside an active transaction."""
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.in_transaction.return_value = False

    with pytest.raises(RuntimeError, match="active transaction"):
        await _acquire_session_cap_lock(ADMIN_A, mock_db)
