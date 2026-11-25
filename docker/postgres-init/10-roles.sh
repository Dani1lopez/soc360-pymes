#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Creates the application database role, with row level security enforced.
#
# Runs once, on first initialisation of the PostgreSQL volume, mounted at
# /docker-entrypoint-initdb.d/.
#
# WHY TWO ROLES: PostgreSQL skips row level security for a superuser or for a
# role with BYPASSRLS. If the application connected as the schema owner (the
# migration role), every policy would be ignored, the multi-tenant isolation
# would protect nothing, and nothing would fail visibly. The application
# connects as `soc360_app` — NOSUPERUSER NOBYPASSRLS — while the migrations run
# as the owner, which grants the table privileges to it.
#
# The login secret is never passed on the command line: `\getenv` reads it from
# the process environment inside psql, so it does not appear in `ps` output or
# in the shell's history.
# ---------------------------------------------------------------------------
set -euo pipefail

if [ -z "${APP_DB_PASSWORD:-}" ]; then
    echo "APP_DB_PASSWORD must be set" >&2
    exit 1
fi

echo "Creating RLS-enforced role '${APP_DB_USER:-soc360_app}'..."

# `:"app_user"` quotes the value as an identifier and `:'app_secret'` as a
# literal, so a login secret containing quotes cannot break the statement.
# \gexec executes whatever statement the SELECT produced.
psql \
    --set=ON_ERROR_STOP=1 \
    --username "${POSTGRES_USER:?POSTGRES_USER must be set}" \
    --dbname "${POSTGRES_DB:?POSTGRES_DB must be set}" \
    --set=app_user="${APP_DB_USER:-soc360_app}" <<'SQL'
\getenv app_secret APP_DB_PASSWORD

SELECT format(
    'CREATE ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS',
    :'app_user', :'app_secret'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

-- Re-assert the flags on every run: a role left with BYPASSRLS by hand would
-- silently disable every policy.
SELECT format(
    'ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS',
    :'app_user', :'app_secret'
)
\gexec

GRANT USAGE ON SCHEMA public TO :"app_user";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO :"app_user";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
-- Tables created by later migrations are covered by the default privileges
-- below, which is why the explicit ALL TABLES grant is not enough on its own.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE ON SEQUENCES TO :"app_user";
SQL

echo "Role ready."
