"""assets scans vulnerabilities reports (F2 self-contained)

Creates assets, scans, vulnerabilities, reports tables plus
tenants.report_types with server_default and NULL backfill.
Fully reversible in a single downgrade step.

Revision ID: 8f2c1a4b9d7e
Revises: b5e9d8c4a123
Create Date: 2026-05-04 11:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8f2c1a4b9d7e"
down_revision: Union[str, None]  = "b5e9d8c4a123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Alter tenants ---
    op.add_column("tenants", sa.Column("scans_per_day", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("tenants", sa.Column("ai_enrichment_level", sa.String(length=50), nullable=False, server_default="basic"))
    op.add_column(
        "tenants",
        sa.Column(
            "report_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[\"vulnerability\"]'::jsonb"),
        ),
    )
    # Backfill existing rows where the column was added as NULL
    # (server_default only applies to new rows inserted after this point)
    op.execute(
        "UPDATE tenants SET report_types = '[\"vulnerability\"]'::jsonb "
        "WHERE report_types IS NULL"
    )
    # Create assets
    op.create_table("assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("asset_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("asset_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
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
    # Create scans
    op.create_table(
        "scans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("scan_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
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
    # Create vulnerabilities
    op.create_table(
        "vulnerabilities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("scan_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
        sa.Column("cve_id", sa.String(length=50), nullable=True),
        sa.Column("cvss_score", sa.Numeric(4, 1), nullable=True),
        sa.Column("vulnerability_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low', 'info')",
            name="chk_vulnerabilities_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'fixed', 'accepted_risk', 'false_positive')",
            name="chk_vulnerabilities_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Create reports
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("report_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "report_type IN ('vulnerability', 'executive', 'technical', 'compliance')",
            name="chk_reports_report_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'generating', 'completed', 'failed')",
            name="chk_reports_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Indexes
    op.create_index(op.f("ix_assets_tenant_id"), "assets", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_scans_tenant_id"), "scans", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_scans_asset_id"), "scans", ["asset_id"], unique=False)
    op.create_index(op.f("ix_vulnerabilities_tenant_id"), "vulnerabilities", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_vulnerabilities_scan_id"), "vulnerabilities", ["scan_id"], unique=False)
    op.create_index(op.f("ix_reports_tenant_id"), "reports", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_reports_asset_id"), "reports", ["asset_id"], unique=False)


    # Triggers / functions
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
    op.execute("""
        CREATE TRIGGER trg_vulnerabilities_updated_at
        BEFORE UPDATE ON vulnerabilities
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    op.execute("""
        CREATE TRIGGER trg_reports_updated_at
        BEFORE UPDATE ON reports
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    # RLS
    op.execute("ALTER TABLE assets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE scans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vulnerabilities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reports ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY rls_assets ON assets USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR tenant_id::text = current_setting('app.current_tenant',TRUE)
        )
    """)
    op.execute("""
        CREATE POLICY rls_scans ON scans USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR tenant_id::text = current_setting('app.current_tenant', TRUE)
        )
    """)
    op.execute("""
        CREATE POLICY rls_vulnerabilities ON vulnerabilities USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR tenant_id::text = current_setting('app.current_tenant', TRUE)
        )
    """)
    op.execute("""
        CREATE POLICY rls_reports ON reports USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR tenant_id::text = current_setting('app.current_tenant', TRUE)
        )
    """)

    # Grants
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON assets TO soc360_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON scans TO soc360_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON vulnerabilities TO soc360_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON reports TO soc360_app")

    
def downgrade() -> None:
    # Revoke Grants
    op.execute("REVOKE ALL ON assets FROM soc360_app")
    op.execute("REVOKE ALL ON scans FROM soc360_app")
    op.execute("REVOKE ALL ON vulnerabilities FROM soc360_app")
    op.execute("REVOKE ALL ON reports FROM soc360_app")
    # Drop RLS
    op.execute("DROP POLICY IF EXISTS rls_assets ON assets")
    op.execute("ALTER TABLE assets DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS rls_scans ON scans")
    op.execute("ALTER TABLE scans DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS rls_vulnerabilities ON vulnerabilities")
    op.execute("ALTER TABLE vulnerabilities DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS rls_reports ON reports")
    op.execute("ALTER TABLE reports DISABLE ROW LEVEL SECURITY")

    # Drop triggers / functions
    op.execute("DROP TRIGGER IF EXISTS trg_assets_updated_at ON assets")
    op.execute("DROP TRIGGER IF EXISTS trg_scans_updated_at ON scans")
    op.execute("DROP TRIGGER IF EXISTS trg_vulnerabilities_updated_at ON vulnerabilities")
    op.execute("DROP TRIGGER IF EXISTS trg_reports_updated_at ON reports")
    # Drop Indexes
    op.drop_index(op.f("ix_assets_tenant_id"), table_name="assets")
    op.drop_index(op.f("ix_scans_tenant_id"), table_name="scans")
    op.drop_index(op.f("ix_scans_asset_id"), table_name="scans")
    op.drop_index(op.f("ix_vulnerabilities_tenant_id"), table_name="vulnerabilities")
    op.drop_index(op.f("ix_vulnerabilities_scan_id"), table_name="vulnerabilities")
    op.drop_index(op.f("ix_reports_tenant_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_asset_id"), table_name="reports")
    # Drop reports
    op.drop_table("reports")

    # Drop vulnerabilities
    op.drop_table("vulnerabilities")
    # Drop scans
    op.drop_table("scans")
    # Drop assets
    op.drop_table("assets")
    # Drop tenants
    op.drop_column("tenants", "scans_per_day")
    op.drop_column("tenants", "ai_enrichment_level")
    op.drop_column("tenants", "report_types")
