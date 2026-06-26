"""f2 vulnerabilities reports (PR-B)

Revision ID: bfca7016cbb7
Revises: 8f2c1a4b9d7e
Create Date: 2026-06-25 15:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "bfca7016cbb7"
down_revision: Union[str, None] = "8f2c1a4b9d7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Parent unique constraints required for composite FK targets ---
    op.create_unique_constraint(
        "uq_scans_id_tenant_id", "scans", ["id", "tenant_id"]
    )
    op.create_unique_constraint(
        "uq_assets_id_tenant_id", "assets", ["id", "tenant_id"]
    )

    # --- vulnerabilities ---
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
        sa.Column(
            "vulnerability_metadata",
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
            "severity IN ('critical', 'high', 'medium', 'low', 'info')",
            name="chk_vulnerabilities_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'fixed', 'accepted_risk', 'false_positive')",
            name="chk_vulnerabilities_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["scan_id", "tenant_id"],
            ["scans.id", "scans.tenant_id"],
            ondelete="CASCADE",
            name="fk_vulnerabilities_scan_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- reports ---
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "report_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
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
            "report_type IN ('vulnerability', 'executive', 'technical', 'compliance')",
            name="chk_reports_report_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'generating', 'completed', 'failed')",
            name="chk_reports_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_id", "tenant_id"],
            ["assets.id", "assets.tenant_id"],
            ondelete="CASCADE",
            name="fk_reports_asset_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- Indexes ---
    op.create_index(
        op.f("ix_vulnerabilities_tenant_id"), "vulnerabilities", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_vulnerabilities_scan_id"), "vulnerabilities", ["scan_id"], unique=False
    )
    op.create_index(op.f("ix_reports_tenant_id"), "reports", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_reports_asset_id"), "reports", ["asset_id"], unique=False)

    # --- Triggers ---
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

    # --- RLS ---
    op.execute("ALTER TABLE vulnerabilities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reports ENABLE ROW LEVEL SECURITY")

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

    # --- Grants ---
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON vulnerabilities TO soc360_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON reports TO soc360_app")


def downgrade() -> None:
    # --- Grants ---
    op.execute("REVOKE ALL ON vulnerabilities FROM soc360_app")
    op.execute("REVOKE ALL ON reports FROM soc360_app")

    # --- RLS ---
    op.execute("DROP POLICY IF EXISTS rls_reports ON reports")
    op.execute("ALTER TABLE reports DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS rls_vulnerabilities ON vulnerabilities")
    op.execute("ALTER TABLE vulnerabilities DISABLE ROW LEVEL SECURITY")

    # --- Triggers ---
    op.execute("DROP TRIGGER IF EXISTS trg_reports_updated_at ON reports")
    op.execute("DROP TRIGGER IF EXISTS trg_vulnerabilities_updated_at ON vulnerabilities")

    # --- Indexes ---
    op.drop_index(op.f("ix_reports_asset_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_tenant_id"), table_name="reports")
    op.drop_index(op.f("ix_vulnerabilities_scan_id"), table_name="vulnerabilities")
    op.drop_index(op.f("ix_vulnerabilities_tenant_id"), table_name="vulnerabilities")

    # --- Tables ---
    op.drop_table("reports")
    op.drop_table("vulnerabilities")

    # --- Parent unique constraints ---
    op.drop_constraint("uq_assets_id_tenant_id", "assets", type_="unique")
    op.drop_constraint("uq_scans_id_tenant_id", "scans", type_="unique")
