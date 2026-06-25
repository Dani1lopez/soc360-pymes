"""f2 assets scans tenant plan extension (PR-A)

Revision ID: 8f2c1a4b9d7e
Revises: b5e9d8c4a123
Create Date: 2026-06-25 14:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8f2c1a4b9d7e"
down_revision: Union[str, None] = "b5e9d8c4a123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Tenant plan extension ---
    op.add_column(
        "tenants",
        sa.Column("scans_per_day", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "ai_enrichment_level",
            sa.String(length=50),
            nullable=False,
            server_default="basic",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "report_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[\"vulnerability\"]'::jsonb"),
        ),
    )
    op.execute(
        "UPDATE tenants SET report_types = '[\"vulnerability\"]'::jsonb "
        "WHERE report_types IS NULL"
    )

    # --- assets ---
    op.create_table(
        "assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column(
            "asset_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "asset_type IN ('host', 'domain', 'ip', 'web_app')",
            name="chk_assets_asset_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="chk_assets_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- scans ---
    op.create_table(
        "scans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("scan_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "scan_type IN ('discovery', 'vulnerability', 'web', 'full')",
            name="chk_scans_scan_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_scans_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- Indexes ---
    op.create_index(op.f("ix_assets_tenant_id"), "assets", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_scans_tenant_id"), "scans", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_scans_asset_id"), "scans", ["asset_id"], unique=False)

    # --- Triggers ---
    op.execute("""
        CREATE TRIGGER trg_assets_updated_at
        BEFORE UPDATE ON assets
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    op.execute("""
        CREATE TRIGGER trg_scans_updated_at
        BEFORE UPDATE ON scans
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # --- RLS ---
    op.execute("ALTER TABLE assets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE scans ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY rls_assets ON assets USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR tenant_id::text = current_setting('app.current_tenant', TRUE)
        )
    """)
    op.execute("""
        CREATE POLICY rls_scans ON scans USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR tenant_id::text = current_setting('app.current_tenant', TRUE)
        )
    """)

    # --- Grants ---
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON assets TO soc360_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON scans TO soc360_app")


def downgrade() -> None:
    # --- Grants ---
    op.execute("REVOKE ALL ON assets FROM soc360_app")
    op.execute("REVOKE ALL ON scans FROM soc360_app")

    # --- RLS ---
    op.execute("DROP POLICY IF EXISTS rls_scans ON scans")
    op.execute("ALTER TABLE scans DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS rls_assets ON assets")
    op.execute("ALTER TABLE assets DISABLE ROW LEVEL SECURITY")

    # --- Triggers ---
    op.execute("DROP TRIGGER IF EXISTS trg_scans_updated_at ON scans")
    op.execute("DROP TRIGGER IF EXISTS trg_assets_updated_at ON assets")

    # --- Indexes ---
    op.drop_index(op.f("ix_scans_asset_id"), table_name="scans")
    op.drop_index(op.f("ix_scans_tenant_id"), table_name="scans")
    op.drop_index(op.f("ix_assets_tenant_id"), table_name="assets")

    # --- Tables ---
    op.drop_table("scans")
    op.drop_table("assets")

    # --- Tenant plan extension ---
    op.drop_column("tenants", "report_types")
    op.drop_column("tenants", "ai_enrichment_level")
    op.drop_column("tenants", "scans_per_day")
