"""initial schema

Revision ID: 712a827b0929
Revises:
Create Date: 2026-03-12 20:52:30.039162

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '712a827b0929'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Tablas ---
    op.create_table('tenants',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )
    op.create_table('users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_superadmin', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'analyst', 'ingestor', 'admin', 'superadmin')", name='chk_valid_role'),
        sa.CheckConstraint('NOT (is_superadmin = FALSE AND tenant_id IS NULL)', name='chk_user_has_tenant'),
        sa.CheckConstraint('NOT (is_superadmin = TRUE AND tenant_id IS NOT NULL)', name='chk_superadmin_no_tenant'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_table('refresh_tokens',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.VARCHAR(length=255), nullable=False),
        sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('revoked_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_from_ip', postgresql.INET(), nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash')
    )

    # --- Índices autogenerados ---
    op.create_index(op.f('ix_users_tenant_id'), 'users', ['tenant_id'], unique=False)
    op.create_index('idx_refresh_active', 'refresh_tokens', ['token_hash'], unique=False, postgresql_where='revoked_at IS NULL')
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)

    # --- Índices adicionales (deuda técnica F1) ---
    op.create_index('ix_users_tenant_active', 'users', ['tenant_id', 'is_active'], unique=False)
    op.execute("CREATE INDEX ix_users_email_lower ON users (lower(email))")

    # --- Función y triggers updated_at ---
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    op.execute("""
        CREATE TRIGGER trg_tenants_updated_at
        BEFORE UPDATE ON tenants
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    op.execute("""
        CREATE TRIGGER trg_users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # --- RLS ---
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY rls_tenants ON tenants USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR id::text = current_setting('app.current_tenant', TRUE)
        )
    """)
    op.execute("""
        CREATE POLICY rls_users ON users USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR tenant_id::text = current_setting('app.current_tenant', TRUE)
        )
    """)
    op.execute("""
        CREATE POLICY rls_refresh_tokens ON refresh_tokens USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR user_id IN (
                SELECT id FROM users
                WHERE tenant_id::text = current_setting('app.current_tenant', TRUE)
            )
        )
    """)

    # --- Permisos soc360_app ---
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO soc360_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON users TO soc360_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_tokens TO soc360_app")


def downgrade() -> None:
    # --- Permisos ---
    op.execute("REVOKE ALL ON tenants FROM soc360_app")
    op.execute("REVOKE ALL ON users FROM soc360_app")
    op.execute("REVOKE ALL ON refresh_tokens FROM soc360_app")

    # --- RLS ---
    op.execute("DROP POLICY IF EXISTS rls_refresh_tokens ON refresh_tokens")
    op.execute("DROP POLICY IF EXISTS rls_users ON users")
    op.execute("DROP POLICY IF EXISTS rls_tenants ON tenants")
    op.execute("ALTER TABLE refresh_tokens DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")

    # --- Triggers y función ---
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users")
    op.execute("DROP TRIGGER IF EXISTS trg_tenants_updated_at ON tenants")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column")

    # --- Índices adicionales ---
    op.execute("DROP INDEX IF EXISTS ix_users_email_lower")
    op.drop_index('ix_users_tenant_active', table_name='users')

    # --- Índices autogenerados ---
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index('idx_refresh_active', table_name='refresh_tokens', postgresql_where='revoked_at IS NULL')
    op.drop_index(op.f('ix_users_tenant_id'), table_name='users')

    # --- Tablas ---
    op.drop_table('refresh_tokens')
    op.drop_table('users')
    op.drop_table('tenants')