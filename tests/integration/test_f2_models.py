from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.assets.models import Asset
from app.modules.reports.models import Report
from app.modules.scans.models import Scan
from app.modules.tenants.models import Tenant
from app.modules.vulnerabilities.models import Vulnerability

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NONEXISTENT_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# Asset — default persistence & constraints
# ---------------------------------------------------------------------------

class TestAssetPersistence:
    """DB-backed tests for Asset model persistence and constraints."""

    async def test_persist_minimal_asset_applies_defaults(
        self, db_session, seed_data
    ) -> None:
        """Persisting an Asset with minimal fields applies column defaults."""
        tenant = seed_data["tenant_a"]

        asset = Asset(
            tenant_id=tenant.id,
            name="server-01",
            asset_type="host",
        )
        db_session.add(asset)
        await db_session.flush()

        assert asset.status == "active"
        assert asset.id is not None
        assert asset.created_at is not None
        assert asset.updated_at is not None

    async def test_asset_without_tenant_fails(self, db_session, seed_data) -> None:
        """FK constraint rejects Asset without tenant_id.

        Uses seed_data to set superadmin context (bypasses RLS) so the
        FK constraint — not RLS — is what rejects the insert.
        """
        asset = Asset(name="orphan", asset_type="host")
        # tenant_id is NOT set — FK should reject on flush
        db_session.add(asset)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_asset_with_invalid_tenant_fails(self, db_session, seed_data) -> None:
        """FK constraint rejects Asset with non-existent tenant_id."""
        asset = Asset(
            tenant_id=NONEXISTENT_UUID,
            name="bad-tenant",
            asset_type="host",
        )
        db_session.add(asset)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_invalid_asset_type_rejected(self, db_session, seed_data) -> None:
        """CheckConstraint rejects invalid asset_type."""
        tenant = seed_data["tenant_a"]
        asset = Asset(
            tenant_id=tenant.id,
            name="bad-type",
            asset_type="invalid_type",
        )
        db_session.add(asset)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_invalid_status_rejected(self, db_session, seed_data) -> None:
        """CheckConstraint rejects invalid status."""
        tenant = seed_data["tenant_a"]
        asset = Asset(
            tenant_id=tenant.id,
            name="bad-status",
            asset_type="host",
            status="deleted",
        )
        db_session.add(asset)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_nullable_columns_accept_none(self, db_session, seed_data) -> None:
        """Nullable columns (hostname, asset_metadata) accept None."""
        tenant = seed_data["tenant_a"]
        asset = Asset(
            tenant_id=tenant.id,
            name="minimal",
            asset_type="ip",
            hostname=None,
            asset_metadata=None,
        )
        db_session.add(asset)
        await db_session.flush()

        assert asset.hostname is None
        assert asset.asset_metadata is None


# ---------------------------------------------------------------------------
# Scan — default persistence & constraints
# ---------------------------------------------------------------------------

class TestScanPersistence:
    """DB-backed tests for Scan model persistence and constraints."""

    async def test_persist_scan_applies_defaults(
        self, db_session, seed_data
    ) -> None:
        tenant = seed_data["tenant_a"]
        # Need an asset first (scan FK → asset)
        asset = Asset(tenant_id=tenant.id, name="target", asset_type="host")
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="vuln-scan-01",
            scan_type="vulnerability",
        )
        db_session.add(scan)
        await db_session.flush()

        assert scan.status == "pending"
        assert scan.id is not None
        assert scan.created_at is not None

    async def test_scan_without_asset_fails(self, db_session, seed_data) -> None:
        """FK to assets rejects Scan without asset_id."""
        tenant = seed_data["tenant_a"]
        scan = Scan(
            tenant_id=tenant.id,
            # asset_id intentionally omitted
            name="no-asset",
            scan_type="discovery",
        )
        db_session.add(scan)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_invalid_scan_type_rejected(self, db_session, seed_data) -> None:
        """CheckConstraint rejects invalid scan_type."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="t2", asset_type="domain")
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="bad-scan-type",
            scan_type="impossible",
        )
        db_session.add(scan)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_nullable_timestamps_accept_none(self, db_session, seed_data) -> None:
        """Nullable started_at/completed_at accept None."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="t3", asset_type="web_app")
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="timed-scan",
            scan_type="full",
            started_at=None,
            completed_at=None,
        )
        db_session.add(scan)
        await db_session.flush()

        assert scan.started_at is None
        assert scan.completed_at is None


# ---------------------------------------------------------------------------
# Vulnerability — default persistence & constraints
# ---------------------------------------------------------------------------


class TestVulnerabilityPersistence:
    """DB-backed tests for Vulnerability model persistence and constraints."""

    async def test_persist_minimal_vuln_applies_defaults(
        self, db_session, seed_data
    ) -> None:
        """Persisting a Vulnerability with minimal fields applies column defaults."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="vuln-target", asset_type="host")
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="vuln-scan",
            scan_type="vulnerability",
        )
        db_session.add(scan)
        await db_session.flush()

        vuln = Vulnerability(
            tenant_id=tenant.id,
            scan_id=scan.id,
            title="CVE-2024-1234",
            severity="high",
        )
        db_session.add(vuln)
        await db_session.flush()

        assert vuln.status == "open"
        assert vuln.id is not None
        assert vuln.created_at is not None
        assert vuln.updated_at is not None

    async def test_vuln_without_scan_fails(self, db_session, seed_data) -> None:
        """FK to scans rejects Vulnerability without scan_id."""
        tenant = seed_data["tenant_a"]
        vuln = Vulnerability(
            tenant_id=tenant.id,
            title="orphan-vuln",
            severity="medium",
        )
        db_session.add(vuln)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_invalid_severity_rejected(self, db_session, seed_data) -> None:
        """CheckConstraint rejects invalid severity."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="sev-target", asset_type="host")
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="sev-scan",
            scan_type="vulnerability",
        )
        db_session.add(scan)
        await db_session.flush()

        vuln = Vulnerability(
            tenant_id=tenant.id,
            scan_id=scan.id,
            title="bad-sev",
            severity="impossible",
        )
        db_session.add(vuln)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_invalid_status_rejected(self, db_session, seed_data) -> None:
        """CheckConstraint rejects invalid status."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="stat-target", asset_type="ip")
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="stat-scan",
            scan_type="vulnerability",
        )
        db_session.add(scan)
        await db_session.flush()

        vuln = Vulnerability(
            tenant_id=tenant.id,
            scan_id=scan.id,
            title="bad-status",
            severity="low",
            status="deleted",
        )
        db_session.add(vuln)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_nullable_columns_accept_none(self, db_session, seed_data) -> None:
        """Nullable columns (description, cve_id, cvss_score, metadata) accept None."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="null-target", asset_type="domain")
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="null-scan",
            scan_type="vulnerability",
        )
        db_session.add(scan)
        await db_session.flush()

        vuln = Vulnerability(
            tenant_id=tenant.id,
            scan_id=scan.id,
            title="nullable-fields",
            severity="info",
            description=None,
            cve_id=None,
            cvss_score=None,
            vulnerability_metadata=None,
        )
        db_session.add(vuln)
        await db_session.flush()

        assert vuln.description is None
        assert vuln.cve_id is None
        assert vuln.cvss_score is None
        assert vuln.vulnerability_metadata is None


# ---------------------------------------------------------------------------
# Report — default persistence & constraints
# ---------------------------------------------------------------------------


class TestReportPersistence:
    """DB-backed tests for Report model persistence and constraints."""

    async def test_persist_report_applies_defaults(
        self, db_session, seed_data
    ) -> None:
        """Persisting a Report with minimal fields applies column defaults."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="report-target", asset_type="web_app")
        db_session.add(asset)
        await db_session.flush()

        report = Report(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="monthly-report",
            report_type="vulnerability",
        )
        db_session.add(report)
        await db_session.flush()

        assert report.status == "pending"
        assert report.id is not None
        assert report.created_at is not None

    async def test_report_without_asset_fails(self, db_session, seed_data) -> None:
        """FK to assets rejects Report without asset_id."""
        tenant = seed_data["tenant_a"]
        report = Report(
            tenant_id=tenant.id,
            name="orphan-report",
            report_type="technical",
        )
        db_session.add(report)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_invalid_report_type_rejected(self, db_session, seed_data) -> None:
        """CheckConstraint rejects invalid report_type."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="rtype-target", asset_type="host")
        db_session.add(asset)
        await db_session.flush()

        report = Report(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="bad-type",
            report_type="invalid_type",
        )
        db_session.add(report)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_invalid_status_rejected(self, db_session, seed_data) -> None:
        """CheckConstraint rejects invalid status."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="rstat-target", asset_type="ip")
        db_session.add(asset)
        await db_session.flush()

        report = Report(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="bad-status",
            report_type="compliance",
            status="archived",
        )
        db_session.add(report)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_nullable_generated_at(self, db_session, seed_data) -> None:
        """Nullable generated_at accepts None."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="gen-target", asset_type="domain")
        db_session.add(asset)
        await db_session.flush()

        report = Report(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="no-gen-date",
            report_type="executive",
            generated_at=None,
        )
        db_session.add(report)
        await db_session.flush()

        assert report.generated_at is None


# ---------------------------------------------------------------------------
# ON DELETE CASCADE integrity
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    """DB-backed tests for ON DELETE CASCADE across the F2 model graph."""

    async def test_delete_asset_cascades_to_scans(
        self, db_session, seed_data
    ) -> None:
        """ON DELETE CASCADE: deleting an asset removes its scans."""
        tenant = seed_data["tenant_a"]
        asset = Asset(tenant_id=tenant.id, name="cascade-asset", asset_type="host")
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="cascade-scan",
            scan_type="discovery",
        )
        db_session.add(scan)
        await db_session.flush()

        asset_id = asset.id
        scan_id = scan.id

        # Delete asset — ON DELETE CASCADE removes the scan
        await db_session.delete(asset)
        await db_session.flush()

        # Verify scan is gone
        result = await db_session.execute(
            text("SELECT 1 FROM scans WHERE id = :id"), {"id": scan_id}
        )
        assert result.fetchone() is None

    async def test_delete_scan_cascades_to_vulnerabilities(
        self, db_session, seed_data
    ) -> None:
        """ON DELETE CASCADE: deleting a scan removes its vulnerabilities."""
        tenant = seed_data["tenant_a"]
        asset = Asset(
            tenant_id=tenant.id, name="vuln-cascade-asset", asset_type="host"
        )
        db_session.add(asset)
        await db_session.flush()

        scan = Scan(
            tenant_id=tenant.id,
            asset_id=asset.id,
            name="vuln-cascade-scan",
            scan_type="vulnerability",
        )
        db_session.add(scan)
        await db_session.flush()

        vuln = Vulnerability(
            tenant_id=tenant.id,
            scan_id=scan.id,
            title="cascade-vuln",
            severity="medium",
        )
        db_session.add(vuln)
        await db_session.flush()

        scan_id = scan.id
        vuln_id = vuln.id

        # Delete scan — ON DELETE CASCADE removes the vulnerability
        await db_session.delete(scan)
        await db_session.flush()

        # Verify vulnerability is gone
        result = await db_session.execute(
            text("SELECT 1 FROM vulnerabilities WHERE id = :id"), {"id": vuln_id}
        )
        assert result.fetchone() is None

    async def test_delete_tenant_cascades_to_assets(
        self, db_session, seed_data
    ) -> None:
        """ON DELETE CASCADE: deleting a tenant removes its assets."""
        unique_tag = uuid.uuid4().hex[:8]
        tenant = Tenant(
            name=f"Test Cascade {unique_tag}",
            slug=f"test-cascade-{unique_tag}",
            plan="free",
        )
        db_session.add(tenant)
        await db_session.flush()

        asset = Asset(
            tenant_id=tenant.id, name="tenant-cascade-asset", asset_type="ip"
        )
        db_session.add(asset)
        await db_session.flush()

        tenant_id = tenant.id
        asset_id = asset.id

        # Delete tenant — ON DELETE CASCADE removes the asset
        await db_session.delete(tenant)
        await db_session.flush()

        # Verify asset is gone
        result = await db_session.execute(
            text("SELECT 1 FROM assets WHERE id = :id"), {"id": asset_id}
        )
        assert result.fetchone() is None


# ---------------------------------------------------------------------------
# Table existence — schema verification
# ---------------------------------------------------------------------------


class TestF2TableExistence:
    """Verify all 4 F2 tables exist in the public schema."""

    async def test_f2_tables_present_in_information_schema(
        self, db_session
    ) -> None:
        """Assert assets, scans, vulnerabilities, reports tables exist."""
        result = await db_session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' "
                "AND table_name IN "
                "('assets', 'scans', 'vulnerabilities', 'reports')"
            )
        )
        tables = {row[0] for row in result}
        expected = {"assets", "scans", "vulnerabilities", "reports"}
        assert tables == expected
