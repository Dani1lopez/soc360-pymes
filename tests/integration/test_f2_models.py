from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from app.modules.tenants.models import Tenant

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
