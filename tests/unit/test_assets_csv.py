"""Unit tests for CSV export formula-injection sanitization (Phase 1 S12 L1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.assets.router import _row_to_csv_dict, _sanitize_csv_cell
from app.modules.assets.schemas import AssetResponse


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("=CMD|' /C calc'!A0", "'=CMD|' /C calc'!A0"),
        ("+1+1", "'+1+1"),
        ("-1+1", "'-1+1"),
        ("@SUM(1+1)", "'@SUM(1+1)"),
        ("\t=1+1", "'\t=1+1"),
        ("\r=1+1", "'\r=1+1"),
        ("  =1+1", "'  =1+1"),
        (" \t+1", "' \t+1"),
        ("example.com", "example.com"),
        ("192.168.1.10", "192.168.1.10"),
        ("", ""),
        (None, ""),
    ],
)
def test_sanitize_csv_cell_neutralizes_formula_prefixes(
    raw: str | None, expected: str
) -> None:
    assert _sanitize_csv_cell(raw) == expected


def test_row_to_csv_dict_sanitizes_text_fields_only() -> None:
    asset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 11, 27, 2, 0, 0, tzinfo=timezone.utc)
    asset = AssetResponse(
        id=asset_id,
        tenant_id=tenant_id,
        type="domain",
        value="=HYPERLINK(\"http://evil.test\",\"click\")",
        created_at=now,
        updated_at=now,
    )

    row = _row_to_csv_dict(asset)

    assert row["id"] == str(asset_id)
    assert row["tenant_id"] == str(tenant_id)
    assert row["type"] == "domain"
    assert row["value"] == "'=HYPERLINK(\"http://evil.test\",\"click\")"
    assert row["created_at"] == now.isoformat()
    assert row["updated_at"] == now.isoformat()
