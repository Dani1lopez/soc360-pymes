from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB

from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from app.modules.tenants.models import Tenant


# ---------------------------------------------------------------------------
# Helpers for model inspection (DB-free — no session needed)
# ---------------------------------------------------------------------------


def _non_nullable_columns(model_cls: Any) -> set[str]:
    return {str(c.name) for c in model_cls.__mapper__.columns if not c.nullable}


def _nullable_columns(model_cls: Any) -> set[str]:
    return {str(c.name) for c in model_cls.__mapper__.columns if c.nullable}


def _check_constraint_names(model_cls: Any) -> set[str]:
    return {
        str(c.name)
        for c in model_cls.__table__.constraints
        if c.name is not None
    }


def _column_default(table: Any, col_name: str) -> Any:
    """Return the Python-side ColumnDefault arg or None."""
    col = getattr(table.c, col_name)
    if col.default is not None:
        return col.default.arg
    return None


def _column_type(table: Any, col_name: str) -> type[Any]:
    """Return the SQLAlchemy column type class."""
    return getattr(table.c, col_name).type.__class__


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------


class TestAssetModel:
    """DB-free inspection tests for the Asset model."""

    def test_tablename(self) -> None:
        assert Asset.__tablename__ == "assets"

    def test_required_columns(self) -> None:
        nn = _non_nullable_columns(Asset)
        assert "id" in nn
        assert "tenant_id" in nn
        assert "name" in nn
        assert "asset_type" in nn
        assert "status" in nn
        assert "created_at" in nn
        assert "updated_at" in nn

    def test_nullable_columns(self) -> None:
        n = _nullable_columns(Asset)
        assert "hostname" in n
        assert "asset_metadata" in n

    def test_column_defaults(self) -> None:
        assert _column_default(Asset.__table__, "status") == "active"

    def test_jsonb_fields(self) -> None:
        assert _column_type(Asset.__table__, "asset_metadata") is JSONB

    def test_check_constraint_names(self) -> None:
        names = _check_constraint_names(Asset)
        assert "chk_assets_asset_type" in names
        assert "chk_assets_status" in names

    def test_fk_columns(self) -> None:
        fks = {
            fk.column.table.name: fk.parent.name
            for fk in Asset.__table__.foreign_keys
        }
        assert fks["tenants"] == "tenant_id"

    def test_repr_format(self) -> None:
        asset = Asset(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            name="server-01",
            asset_type="host",
        )
        result = repr(asset)
        assert "Asset" in result
        assert "server-01" in result


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


class TestScanModel:
    """DB-free inspection tests for the Scan model."""

    def test_tablename(self) -> None:
        assert Scan.__tablename__ == "scans"

    def test_required_columns(self) -> None:
        nn = _non_nullable_columns(Scan)
        assert "id" in nn
        assert "tenant_id" in nn
        assert "asset_id" in nn
        assert "name" in nn
        assert "scan_type" in nn
        assert "status" in nn
        assert "created_at" in nn
        assert "updated_at" in nn

    def test_nullable_columns(self) -> None:
        n = _nullable_columns(Scan)
        assert "config" in n
        assert "started_at" in n
        assert "completed_at" in n

    def test_column_defaults(self) -> None:
        assert _column_default(Scan.__table__, "status") == "pending"

    def test_jsonb_fields(self) -> None:
        assert _column_type(Scan.__table__, "config") is JSONB

    def test_check_constraint_names(self) -> None:
        names = _check_constraint_names(Scan)
        assert "chk_scans_scan_type" in names
        assert "chk_scans_status" in names

    def test_fk_columns(self) -> None:
        """Verify foreign keys point to expected parent tables."""
        fks = {
            fk.column.table.name: fk.parent.name
            for fk in Scan.__table__.foreign_keys
        }
        assert fks["tenants"] == "tenant_id"
        assert fks["assets"] == "asset_id"

    def test_repr_format(self) -> None:
        scan = Scan(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            name="scan-01",
            scan_type="vulnerability",
        )
        result = repr(scan)
        assert "Scan" in result
        assert "scan-01" in result


# ---------------------------------------------------------------------------
# Tenant plan extension
# ---------------------------------------------------------------------------


class TestTenantPlanExtension:
    """DB-free inspection tests for the tenant plan-extension columns."""

    def test_tablename(self) -> None:
        assert Tenant.__tablename__ == "tenants"

    def test_required_columns(self) -> None:
        nn = _non_nullable_columns(Tenant)
        assert "scans_per_day" in nn
        assert "ai_enrichment_level" in nn

    def test_report_types_is_nullable(self) -> None:
        n = _nullable_columns(Tenant)
        assert "report_types" in n

    def test_scans_per_day_server_default(self) -> None:
        col = getattr(Tenant.__table__.c, "scans_per_day")
        assert col.server_default is not None
        assert "1" in str(col.server_default.arg)
        assert _column_default(Tenant.__table__, "scans_per_day") == 1

    def test_ai_enrichment_level_server_default(self) -> None:
        col = getattr(Tenant.__table__.c, "ai_enrichment_level")
        assert col.server_default is not None
        assert "basic" in str(col.server_default.arg)
        assert _column_default(Tenant.__table__, "ai_enrichment_level") == "basic"

    def test_report_types_server_default(self) -> None:
        col = getattr(Tenant.__table__.c, "report_types")
        assert col.server_default is not None
        assert "vulnerability" in str(col.server_default.arg)
        default_factory = _column_default(Tenant.__table__, "report_types")
        assert default_factory is not None
        assert default_factory(None) == ["vulnerability"]
