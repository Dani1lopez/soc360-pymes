---
# OpenSpec Project-Level Handoff Document
project: soc360-pymes
title: Session Handoff — Next Steps
type: handoff
status: active
created: 2026-06-23
updated: 2026-06-25
artifact_store: hybrid
---

# Session Handoff — Next Steps

## Current Main State

- **Active branch at handoff time:** `feat/f2-models-migration-pr-a` (local branch already merged remotely)
- **Remote main latest confirmed merge:** `5359a06` PR #113 — `feat(f2): add asset scan migration slice`
- **Local main sync:** must be refreshed next session (`git checkout main && git pull --ff-only`) before starting PR-B
- **Recent merges on main:**
  - `056cdf9` PR #111 — `feat(core): rescue F2 domain exception classes and tests`
  - `270fb1d` PR #112 — `chore(archive): archive rescue-f2-domain-exceptions`
  - `5359a06` PR #113 — `feat(f2): add asset scan migration slice`
- **CI baseline:** PR #106 (`ci: add GitHub Actions test workflow`) is merged and active
- **Issue #91:** rewritten to describe a main-based rescue of F2 domain exceptions; historical branches are **not** deleted

## F2 Recovery Status

| Area | State |
|------|-------|
| CI workflow | Exists and green baseline established |
| F2 domain exceptions | Rescued into `main` via PR #111 |
| SDD archive | `rescue-f2-domain-exceptions` archived via PR #112 |
| F2 models/migration PR-A | Merged via PR #113: Asset + Scan + tenant plan extension + R1 migration + DB-free tests |
| F2 models/migration PR-B | Next slice: Vulnerability + Report + R2 migration + minimal tests |
| Source-of-truth for models/migration | **NOT** `origin/develop`; valid source is `origin/feat/f2-pr-slicing-01-migration` and its chain |
| Historical F2 branches | Preserved as reference; not merged broadly |

## Next Slice Decision

Continue the **F2 models/migration split** via SDD:

- **Change name:** `feat/f2-models-migration`
- **Completed slice:** PR-A (`feat/f2-models-migration-pr-a`) merged as PR #113 / `5359a06`
- **Next starting phase:** sync `main`, then continue from existing tasks/apply-progress for PR-B
- **Next branch from:** refreshed `main` at `5359a06` or later
- **Next branch name:** `feat/f2-models-migration-pr-b`
- **PR style:** formal PR with review; do not bypass review rules

## Scope Decisions for `feat/f2-models-migration`

1. PR-A is complete: `Asset`, `Scan`, tenant plan columns, R1 (`8f2c1a4b9d7e`), DB-free tests.
2. PR-B should include `Vulnerability`, `Report`, R2 chained to R1, and DB-free tests for those models.
3. Include `tests/integration/conftest.py` in PR-B only if still needed for stale-table / Alembic loader protection.
4. Exclude `tests/integration/test_alembic_migration_graph.py`; it remains a separate focused PR.
5. Extract models/migration code from the F2 slicing chain (`origin/feat/f2-pr-slicing-01-migration`), **not** from `origin/develop`.
6. Use exact-path or highly controlled commit/path extraction; no broad cherry-picks or branch merges during structural rescue.
7. Do **not** add SQLAlchemy `relationship()` declarations in PR-B unless explicitly approved; ORM relationships are deferred to later slices.

## Structural Rescue Policy (Critical)

During F2 structural rescue, the following are **forbidden** unless explicitly approved after deep review:

- Broad cherry-picks across old F2 branches
- Whole-branch merges of `origin/develop` or historical F2 branches into `main`
- Blind copy-paste of old F2 code without spec/design/tasks review

Allowed:

- Manual exact-path extraction with line-by-line review
- Highly controlled commit/path extraction with documented rationale
- New code written to spec under full SDD cycle

## Demo-Vulnerable-Target Workstream

A future `demo-vulnerable-target` workstream is identified but **not** part of F2 rescue. Before any apply:

- Requires deep Docker/infra/security review
- Requires opt-in profile validation
- Requires direct user questions about intent and scope
- Must pass **Judgment Day** dual review before implementation

## Local Test Environment Notes

- Docker + PostgreSQL for tests was available during PR-A verification.
- Unit auth tests pass.
- Previous integration subset failure was a **stale DB `DuplicateTableError`**; reset the test database before rerunning integration tests.
- `httpx` warning seen in the editor is likely an LSP/venv issue, not a test failure.
- PR-A verify evidence: `uv run pytest -m "not integration"` passed (`371 passed, 84 deselected`), `uv run alembic heads` reported single head `8f2c1a4b9d7e`, and live PostgreSQL upgrade/downgrade passed.

## Proposed Future CI Optimization

Consider a dedicated SDD change for CI speed:

- Add pytest markers and split CI jobs
- Add path filters to avoid running the full suite on unrelated changes
- **Do not** add `pytest-xdist` until database isolation is guaranteed

## Immediate Next Steps (in order)

1. **Refresh local state after PR #113 merge**
   - `git checkout main && git pull --ff-only`
   - Confirm `main` includes merge commit `5359a06`
   - Preserve unrelated untracked files unless user explicitly decides otherwise: `.python-version`, `openspec/changes/cleanup-f2-branch-state/`, `openspec/config.yaml`, `openspec/project/`

2. **Start PR-B from updated main**
   - Branch: `feat/f2-models-migration-pr-b`
   - Continue SDD apply for tasks 3.1–4.2 only
   - Implement `Vulnerability`, `Report`, R2 migration, and minimal DB-free tests
   - Keep PR-A frozen as merged baseline; do not rewrite R1 unless a real blocker appears

3. **Verify PR-B before opening PR**
   - `uv run pytest tests/unit/test_f2_models.py -q`
   - `uv run pytest tests/unit -m "not integration"`
   - `uv run pytest -m "not integration"` if DB is available
   - `uv run alembic heads`
   - Live PostgreSQL upgrade/downgrade R2 → R1 if DB is available

4. **Keep old F2 branches untouched**
   - Do not delete or merge `origin/feat/f2-pr-slicing-*`, `origin/feat/f2-foundation-alignment`, or similar historical branches without explicit cleanup SDD

5. **Track CI optimization as a separate future change**
   - Do not mix CI speed work into `feat/f2-models-migration`

## Sensitive-Data Checklist for OpenSpec Artifacts

Before committing any OpenSpec artifact, verify it contains none of the following:

- Real customer names or data
- Private IP addresses
- Credentials, tokens, or API keys
- Real scan outputs
- Third-party vulnerability details
- PII
- Private notes or emotional commentary
- Security-sensitive operational details
