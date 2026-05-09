from __future__ import annotations

import uuid

from app.modules.assets.models import Asset
from app.modules.reports.models import Report
from app.modules.scans.models import Scan
from app.modules.vulnerabilities.models import Vulnerability


# ---------------------------------------------------------------------------
# Helpers for model inspection (DB-free — no session needed)
# ---------------------------------------------------------------------------

def _non_nullable_columns(model_cls: type) -> set[str]:
    return {c.name for c in model_cls.__mapper__.columns if not c.nullable}


def _nullable_columns(model_cls: type) -> set[str]:
    return {c.name for c in model_cls.__mapper__.columns if c.nullable}


def _check_constraint_names(model_cls: type) -> set[str]:
    return {
        c.name
        for c in model_cls.__table__.constraints
        if c.name is not None
    }


def _column_default(table, col_name: str):
    """Return the Python-side ColumnDefault arg or None."""
    col = getattr(table.c, col_name)
    if col.default is not None:
        return col.default.arg
    return None


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------

class TestAssetModel:
    """Tests unitarios de inspección del modelo Asset — DB-free"""

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
        """Verify column-level defaults (Python-side `default=` arg)."""
        assert _column_default(Asset.__table__, "status") == "active"

    def test_check_constraint_names(self) -> None:
        names = _check_constraint_names(Asset)
        assert "chk_assets_asset_type" in names
        assert "chk_assets_status" in names

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
    """Tests unitarios de inspección del modelo Scan — DB-free"""

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

    def test_check_constraint_names(self) -> None:
        names = _check_constraint_names(Scan)
        assert "chk_scans_scan_type" in names
        assert "chk_scans_status" in names

    def test_fk_columns(self) -> None:
        """Verify foreign keys point to expected parent tables."""
        fks = {fk.column.table.name: fk.parent.name for fk in Scan.__table__.foreign_keys}
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
# Vulnerability
# ---------------------------------------------------------------------------

class TestVulnerabilityModel:
    """Tests unitarios de inspección del modelo Vulnerability — DB-free"""

    def test_tablename(self) -> None:
        assert Vulnerability.__tablename__ == "vulnerabilities"

    def test_required_columns(self) -> None:
        nn = _non_nullable_columns(Vulnerability)
        assert "id" in nn
        assert "tenant_id" in nn
        assert "scan_id" in nn
        assert "title" in nn
        assert "severity" in nn
        assert "status" in nn
        assert "created_at" in nn
        assert "updated_at" in nn

    def test_nullable_columns(self) -> None:
        n = _nullable_columns(Vulnerability)
        assert "description" in n
        assert "cve_id" in n
        assert "cvss_score" in n
        assert "vulnerability_metadata" in n

    def test_column_defaults(self) -> None:
        assert _column_default(Vulnerability.__table__, "status") == "open"

    def test_check_constraint_names(self) -> None:
        names = _check_constraint_names(Vulnerability)
        assert "chk_vulnerabilities_severity" in names
        assert "chk_vulnerabilities_status" in names

    def test_fk_columns(self) -> None:
        fks = {fk.column.table.name: fk.parent.name for fk in Vulnerability.__table__.foreign_keys}
        assert fks["tenants"] == "tenant_id"
        assert fks["scans"] == "scan_id"

    def test_repr_format(self) -> None:
        vuln = Vulnerability(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            scan_id=uuid.uuid4(),
            title="SQL Injection",
            severity="high",
        )
        result = repr(vuln)
        assert "Vulnerability" in result
        assert "SQL Injection" in result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class TestReportModel:
    """Tests unitarios de inspección del modelo Report — DB-free"""

    def test_tablename(self) -> None:
        assert Report.__tablename__ == "reports"

    def test_required_columns(self) -> None:
        nn = _non_nullable_columns(Report)
        assert "id" in nn
        assert "tenant_id" in nn
        assert "asset_id" in nn
        assert "name" in nn
        assert "report_type" in nn
        assert "status" in nn
        assert "created_at" in nn
        assert "updated_at" in nn

    def test_nullable_columns(self) -> None:
        n = _nullable_columns(Report)
        assert "summary" in n
        assert "report_metadata" in n
        assert "generated_at" in n

    def test_column_defaults(self) -> None:
        assert _column_default(Report.__table__, "status") == "pending"

    def test_check_constraint_names(self) -> None:
        names = _check_constraint_names(Report)
        assert "chk_reports_report_type" in names
        assert "chk_reports_status" in names

    def test_fk_columns(self) -> None:
        fks = {fk.column.table.name: fk.parent.name for fk in Report.__table__.foreign_keys}
        assert fks["tenants"] == "tenant_id"
        assert fks["assets"] == "asset_id"

    def test_repr_format(self) -> None:
        report = Report(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            name="report-01",
            report_type="vulnerability",
        )
        result = repr(report)
        assert "Report" in result
        assert "report-01" in result
