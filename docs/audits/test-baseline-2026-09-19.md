# Test Baseline — soc360-pymes (2026-09-19)

A reproducible, classified snapshot of what the test suite does **not** pass on
branch `feat/f2-slice-2-scans` (Slice 2 of F2 — Scans CRUD).

The purpose is attribution: without a measured baseline, a later failure cannot
be honestly assigned to "the change under review" or "already broken before".
Every number below was measured, not estimated.

## How to reproduce

```bash
uv run pytest tests/ -q
```

Runtime is roughly 8m25s because the session provisions a real PostgreSQL
database and replays the full Alembic chain.

## Measured result

```text
8 failed, 1297 passed, 7 skipped, 2 xfailed, 28 errors
```

## Classified failures

None of these belongs to Slice 2.

| File | Count | Kind | Cause | Owner |
| --- | --- | --- | --- | --- |
| `tests/integration/test_toxiproxy_scan_lock_faults.py` | 17 | error | no toxiproxy server running | environment |
| `tests/integration/test_toxiproxy_fault_injection.py` | 6 | error | no toxiproxy server running | environment |
| `tests/integration/test_toxiproxy_revocation_event_faults.py` | 4 | error | no toxiproxy server running | environment |
| `tests/integration/test_toxiproxy_baseline.py` | 1 | error | no toxiproxy server running | environment |
| `tests/unit/test_llm_config.py` | 5 | failure | `ValidationError: GROQ_API_KEY debe empezar con 'gsk_'` — the value supplied by `tests/.env` fails the Settings validator | local config |
| `tests/unit/test_imports.py` | 1 | failure | inline import at `app/main.py:290` (`from app.core.metrics_auth import _current_bytes, _previous_bytes`) | pre-existing (Slice 1) |
| `tests/integration/test_redis_noeviction_pressure.py` | 1 | failure | `REDIS_PRESSURE_PORT` is not set — the test requires a dedicated Redis instance | environment |
| `tests/sdd/test_restore-indexes-concurrently.py` | 1 | failure | `SCN-5.1: indexes still present after downgrade` — an index-state problem, deliberately left failing | pre-existing, different root cause |

### Unit-suite-only failures when run in isolation

Running `uv run pytest tests/unit/` alone adds **4 errors** in
`tests/unit/test_assets.py`:

- `TestAssetUniquenessAtSQLAlchemyLayer::test_duplicate_insert_raises_integrity_error_with_constraint_name`
- `TestAssetServiceFullContract::test_list_assets_uses_created_at_desc_then_id_desc`
- `TestAssetServiceFullContract::test_update_asset_persists_canonical_value`
- `TestAssetServiceFullContract::test_update_asset_canonical_equivalence_is_a_noop`

All four fail with `UndefinedTableError: relation "tenants" does not exist`.
They use the `db_session` and `seed_data` fixtures from the root
`tests/conftest.py`, but they live under `tests/unit/`, whose `conftest.py`
overrides `prepare_database` as a **deliberate no-op** ("no-op for unit tests").
No database is provisioned, so any test in that directory that needs one cannot
work. In a full `tests/` run the integration conftest's real `prepare_database`
wins for the whole session, which is why these four pass there.

These tests belong in `tests/integration/`. That relocation has not been made.

## Failures repaired on this branch

Recorded so the repairs are not mistaken for test weakening.

**`ca79bcf` — stale fixtures aligned with the `Asset` model shape.** An earlier
slice renamed `Asset.name` to `value`, dropped `Asset.hostname`, and changed the
`asset_type` allowlist value `'host'` to `'hostname'`. Five files were never
updated and produced 35 failures from that one cause:
`tests/unit/test_f2_models.py` (3 assertions and one repr test),
`tests/integration/test_f2_tenant_isolation.py` (6 `Asset(...)` constructions),
`tests/sdd/conftest.py` (2 `pg_insert(Asset)` seeds), and raw SQL in
`tests/sdd/test_rls_cross_tenant_crud.py` and
`tests/sdd/test_restore-indexes-concurrently.py`.

Only identifiers and column names invalidated by the rename were changed. No
assertion was weakened or deleted, and cross-tenant test intent is unchanged.
Note that `scans`, `reports` and `refresh_tokens` still **have** a `name`
column — only `assets` was renamed.

**`f5a94cd` — migration chain pinned.** Adding Slice 2's migration
(`f92b1c0fa120`) made it the Alembic head, and `tests/unit/test_assets.py`
computed its target revision dynamically via `alembic heads` plus
`alembic show`. Its `new_revision_sql` fixture therefore began rendering the
new migration, so 16 assertions about the Slice 1 assets DDL failed and 4 online
tests errored. The chain is now pinned to `a1b2c3d4e5f6 → e0eafdf389fc`. These
tests exist to validate that specific migration, so auto-detection was wrong by
construction: it only ever worked while exactly one new migration existed. This
was a regression introduced by Slice 2's own PR0, caught only by running the
full suite.

## Prerequisites missing locally

- **toxiproxy** — 28 errors. The fault-injection integration tests need a
  running toxiproxy; without it every one of them errors during setup, and the
  errors say nothing about the code under test.
- **`REDIS_PRESSURE_PORT`** — 1 failure, requires a dedicated Redis instance.

## Hazard: `uv run alembic` targets the development database

`uv run alembic` resolves `DATABASE_URL_MIGRATION` from the application's `.env`
(`localhost:5433/soc360` — the **development** database). The test suite instead
loads `tests/.env` (`localhost:5434/soc360_test`). Two different databases for
two different runners.

The repository does have a guard, `_assert_safe_test_database()` in
`tests/conftest.py:106`, which refuses to run when the environment is
production/staging or the database name does not contain `test`. But only
`conftest` calls it, so a raw `alembic` invocation bypasses it entirely.

Observed consequence: a raw `uv run alembic upgrade head` connected to the
development database and failed with `DuplicateTableError: relation
"vulnerabilities" already exists`, because that database is drifted — it holds
the `vulnerabilities` and `reports` tables while `alembic_version` still reports
`8f2c1a4b9d7e`, and its `scans` table has no `ix_scans_asset_tenant`.
Transactional DDL rolled the attempt back, so nothing was applied. Verified
afterwards: no schema change.

**Always point `DATABASE_URL_MIGRATION` at the test database when running
alembic by hand.**

Two related traps worth knowing:

- `str(sqlalchemy.engine.URL)` renders the password as `***`. Building a derived
  URL with `str(url.set(database=...))` produces an unusable URL and fails with
  `InvalidPasswordError`. Use `render_as_string(hide_password=False)`.
- Test fixtures that auto-detect "the newest migration" via `alembic heads` break
  as soon as a second migration lands. Pin the revision pair whenever the test
  is about one specific migration.
