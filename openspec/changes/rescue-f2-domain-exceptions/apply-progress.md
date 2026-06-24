# Apply Progress: Rescue F2 Domain Exceptions

**Change**: rescue-f2-domain-exceptions
**Mode**: Strict TDD (strict_tdd: true, pytest available)
**Branch**: feat/f2-domain-exceptions
**Source**: Manual extraction only from `origin/feat/f2-foundation-alignment` commit `99692c4`.

## Completed Tasks

### Phase 1: Guardrails / Extraction Prep
- [x] 1.1 Verified only `app/core/exceptions.py` and `tests/unit/test_f2_exceptions.py` are sourced from `99692c4`; manual path extraction used.
- [x] 1.2 No forbidden areas touched (CI, lifespan, tenant, docker/demo, migrations, routers/services, cherry-pick/merge).
- [x] 1.3 Preserved existing exception style: appended after `LLMResponseError`, Spanish docstrings, `# ── F2 Domain Exceptions ──` separator.

### Phase 2: RED — Test Rescue
- [x] 2.1 Created `tests/unit/test_f2_exceptions.py` from source branch; renamed `test_asserterror_*` → `test_asseterror_*` and `test_scannerror_*` → `test_scanerror_*` only.
- [x] 2.2 Test bodies unchanged (hierarchy, default/custom status, `str()`, no module-state leak).

### Phase 3: GREEN — Code Rescue
- [x] 3.1 Added `AssetError`, `ScanError`, `VulnerabilityError`, `ReportError` as bare `AppError` subclasses with no custom `__init__`.
- [x] 3.2 Targeted tests pass; broader DB-backed tests blocked by missing local PostgreSQL service (port 5433), not by code changes.
- [x] 3.3 No behavior drift, no new runtime imports, no module-state leak.

### Phase 4: Review / PR Prep / Rollback
- [x] 4.1 `git diff --stat` confirms only `app/core/exceptions.py` is modified among tracked files; `tests/unit/test_f2_exceptions.py` is new.
- [x] 4.2 Reviewed edge cases: all four classes inherit `AppError.__init__` defaults (`status_code=400`), custom detail/status flows preserved, `str()` includes detail.
- [x] 4.3 PR notes captured below; rollback is a single revert.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1–3.1 | `tests/unit/test_f2_exceptions.py` | Unit | N/A (new file) | ✅ Written (ImportError before impl) | ✅ 25/25 passed | ✅ Parametrized + custom detail/status cases | ✅ Cleaned odd test names only |

### Test Summary
- **Total tests written/rescued**: 25 (11 methods via parametrize + individual cases)
- **Total tests passing**: 25 (targeted F2 file)
- **Layers used**: Unit
- **Approval tests**: None — no refactoring of existing code
- **Pure functions created**: N/A (exception classes)

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `app/core/exceptions.py` | Modified | Appended 4 F2 domain exception classes (`AssetError`, `ScanError`, `VulnerabilityError`, `ReportError`) as bare `AppError` subclasses. |
| `tests/unit/test_f2_exceptions.py` | Created | Rescued DB-free unit tests from source branch; cleaned odd test names (`asserterror`/`scannerror`) without changing assertions. |
| `openspec/changes/rescue-f2-domain-exceptions/tasks.md` | Modified | Marked all tasks `[x]`. |
| `openspec/changes/rescue-f2-domain-exceptions/apply-progress.md` | Created | This apply-progress artifact. |
| `tests/unit/test_f2_exceptions.py` | Modified | Added missing `test_vulnerabilityerror_custom_status_code` case (post-apply review). |
| `openspec/changes/rescue-f2-domain-exceptions/apply-progress.md` | Modified | Removed trailing whitespace; updated test counts and `--confcutdir` evidence (post-apply review). |

## Post-Apply Review Fixes

1. **Trailing whitespace**: Removed trailing spaces in the front-matter of `apply-progress.md` (lines 3–5). `git diff --check main...HEAD` now reports no whitespace errors.
2. **Coverage gap**: Added `test_vulnerabilityerror_custom_status_code` so every F2 domain exception has an explicit custom-status-code test. Total targeted tests increased from 24 to 25; all pass.
3. **DB fixture isolation**: Confirmed the targeted test command must use `--confcutdir=tests/unit` to bypass the session-scoped `prepare_database` fixture in the root `tests/conftest.py`. Without it, every test errors while connecting to PostgreSQL on `localhost:5433`. No `conftest.py` changes were made.

## Deviations from Design

None — implementation matches design.

## Issues / Environment Blockers

- `pytest tests/unit/test_tenants.py` and full `pytest tests/unit/` cannot run locally because the session-scoped `prepare_database` fixture requires a PostgreSQL instance on `localhost:5433`, and the Docker daemon is not available in this environment. The failures are connection errors (`OSError: [Errno 111] Connect call failed`), not code regressions.
- The F2 exception tests are DB-free and pass with the isolated command `PYTHONPATH=. pytest --confcutdir=tests/unit tests/unit/test_f2_exceptions.py -v` (25 passed). Running the same file without `--confcutdir=tests/unit` errors during `prepare_database` setup because the root `tests/conftest.py` is loaded.

## Workload / PR Boundary

- **Mode**: single PR
- **Current work unit**: Unit 1 — manual extract of the two allowed files
- **Boundary**: Adds F2 exception classes + unit tests only; no runtime call-site changes
- **Estimated review budget impact**: ~150 changed lines (well under 400-line budget)

## PR Notes

- Manual extraction only; do **not** cherry-pick `feat/f2-foundation-alignment`.
- No forbidden-area files touched.
- Rollback: revert the single commit on `feat/f2-domain-exceptions`.

## Status

11/11 tasks complete. Ready for verify (noting local DB service is unavailable for full unit-suite execution).
