# Tasks: Rescue F2 Domain Exceptions

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~150 (+ tasks artifact) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | N/A |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: N/A
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Manual extract only the two allowed files from `origin/feat/f2-foundation-alignment` (`99692c4`) | PR 1 | No cherry-pick, no forbidden paths, no runtime call-site changes |

## Phase 1: Guardrails / Extraction Prep

- [x] 1.1 Verify only `app/core/exceptions.py` and `tests/unit/test_f2_exceptions.py` are sourced from `origin/feat/f2-foundation-alignment` commit `99692c4`; use manual path extraction only.
- [x] 1.2 Keep forbidden areas untouched: `.github/workflows/ci.yml`, `tests/unit/test_main_lifespan.py`, `tests/unit/test_tenants.py`, `docker/**`, `docker-compose.yml`, `docs/demo.md`, `tests/verify_demo_target.sh`, migrations, routers/services/runtime call sites; no broad branch merge or broad cherry-pick.
- [x] 1.3 Preserve existing exception style in `app/core/exceptions.py`: append after `LLMResponseError` with `# ── F2 Domain Exceptions ──` and Spanish docstrings.

## Phase 2: RED — Test Rescue

- [x] 2.1 Create `tests/unit/test_f2_exceptions.py` from the source branch and rename `test_asserterror_*`/`test_scannerror_*` to readable names only.
- [x] 2.2 Keep the test body unchanged: hierarchy, default/custom status code, `str()`, and no module-state leak.

## Phase 3: GREEN — Code Rescue

- [x] 3.1 Add `AssetError`, `ScanError`, `VulnerabilityError`, and `ReportError` to `app/core/exceptions.py` as bare `AppError` subclasses with no custom `__init__`.
- [x] 3.2 Re-run `pytest tests/unit/test_f2_exceptions.py -v` and then `pytest tests/unit/ -v`; fix only rescue-related issues if they appear.
- [x] 3.3 Confirm no behavior drift, no new imports in runtime call sites, and no hidden state changes in the exception module.

## Phase 4: Review / PR Prep / Rollback

- [x] 4.1 Audit `git diff --stat` and `git diff` to ensure only the two allowed files changed.
- [x] 4.2 Review edge cases and adjacent exception files; if any failure mode is unclear, stop and ask rather than shallow-pass.
- [x] 4.3 Prepare PR notes with manual extraction only, explicit no-cherry-pick warning, and rollback via a single revert.
