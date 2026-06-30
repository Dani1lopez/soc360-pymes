# Archive Report: fix-f1-remaining-rls-403-and-email-409

**Change**: `fix-f1-remaining-rls-403-and-email-409`
**Mode**: OPENSPEC (file-based; Engram has prior phase artifacts)
**Archived on**: 2026-06-30
**Source of truth**: PR #124 merged to `main`
**Archived to**: `openspec/changes/archive/2026-06-30-fix-f1-remaining-rls-403-and-email-409/`

## Outcome

**PASS.** The change is fully planned, implemented, verified, and archived. SDD cycle complete.

## Gates Evaluated

| Gate | Result | Evidence |
|------|--------|----------|
| PR #124 merged to `main` | PASS | Change is fully merged to main via PR #124 |
| Task Completion Gate (no unchecked impl tasks) | PASS | `tasks.md` shows all 23 tasks marked `[x]` across Phases 1-3 |
| Verify report verdict | PASS WITH WARNINGS | verify-report observation #332 records `PASS WITH WARNINGS` |
| CRITICAL issues in verify report | NONE | verify-report section "Issues Found → CRITICAL" contains `None` |
| Delta spec destination | N/A | The change's delta spec (`specs/fix-f1-remaining-rls-403-and-email-409/spec.md`) is scoped to this specific F1 fix, not a new reusable domain. The proposal explicitly declares "New Capabilities: None" and "Modified Capabilities: None" relative to existing `user-management` / `tenant-management` behavior. No main-spec merge was performed; the delta spec is preserved in the archive as an audit trail. |
| Change folder archived | PASS | `openspec/changes/fix-f1-remaining-rls-403-and-email-409/` contents copied to `openspec/changes/archive/2026-06-30-fix-f1-remaining-rls-403-and-email-409/`. Note: the source folder removal step (rmdir) was not performed in this archive phase because the archive executor did not have shell access; the source folder is now a duplicate of the archive and should be removed by the orchestrator/user as a follow-up housekeeping step. The archive copy itself is the authoritative audit trail. |
| Archive contains all artifacts | PASS | Archived folder holds `proposal.md`, `design.md`, `tasks.md`, and `specs/fix-f1-remaining-rls-403-and-email-409/spec.md` |
| No unrelated untracked paths touched | PASS | No changes outside the change folder and its archive destination |
| No staging, committing, pushing, or PR creation | PASS | `sdd-archive` only writes the archive report and copies files; no `git add`, `git commit`, `git push`, or `gh pr create` was invoked |

## Files Archived

| File | Source | Destination |
|------|--------|-------------|
| `proposal.md` | `openspec/changes/fix-f1-remaining-rls-403-and-email-409/proposal.md` | `openspec/changes/archive/2026-06-30-fix-f1-remaining-rls-403-and-email-409/proposal.md` |
| `design.md` | `openspec/changes/fix-f1-remaining-rls-403-and-email-409/design.md` | `openspec/changes/archive/2026-06-30-fix-f1-remaining-rls-403-and-email-409/design.md` |
| `tasks.md` | `openspec/changes/fix-f1-remaining-rls-403-and-email-409/tasks.md` | `openspec/changes/archive/2026-06-30-fix-f1-remaining-rls-403-and-email-409/tasks.md` |
| `specs/fix-f1-remaining-rls-403-and-email-409/spec.md` | `openspec/changes/fix-f1-remaining-rls-403-and-email-409/specs/fix-f1-remaining-rls-403-and-email-409/spec.md` | `openspec/changes/archive/2026-06-30-fix-f1-remaining-rls-403-and-email-409/specs/fix-f1-remaining-rls-403-and-email-409/spec.md` |
| `archive-report.md` | (created by this phase) | `openspec/changes/archive/2026-06-30-fix-f1-remaining-rls-403-and-email-409/archive-report.md` |

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| (none) | none | Proposal explicitly states `New Capabilities: None` and `Modified Capabilities: None`. The delta spec documents the R01–R10 requirements specific to this F1 fix; it is not a new reusable domain. The delta spec is preserved in the archive as an audit trail alongside `proposal.md` and `design.md`. No main spec (`openspec/specs/`) was modified. |

## Capabilities Touched

| Capability | Type | Notes |
|------------|------|-------|
| `user-management` | Documented (no spec file change) | Cross-tenant 403 contract (R01, R02, R03) and email 409 contract (R07) are enforced by code but the canonical `user-management` spec was not created. The behavior is captured in the archived delta spec as an audit trail. |
| `tenant-management` | Documented (no spec file change) | Cross-tenant 403 contract for `GET /tenants/{id}` (RK-6) is enforced. The behavior is captured in the archived delta spec. |

## Production Code Landed via PR #124

The change was delivered as a chained PR stack per `tasks.md`:

1. **PR-0** — `fix(rls): prevent session poisoning across pooled connections` (commit `7007cbf` on `fix/heal-f1`). Commit prerequisite: `app/core/database.py`, `app/dependencies.py`, `tests/integration/test_auth_login_event_flow.py`.
2. **PR-A** — `fix(users,tenants): return 403 on cross-tenant access via service-layer pre-check` (commit `cf72d73` on `fix/heal-f1`). Service-layer pre-check + new FastAPI Depends; R01–R06, RK-6.
3. **PR-B** — `fix(users): translate unique_violation to 409 on duplicate email` (commit `37b8cc1` on `fix/heal-f1`). IntegrityError → 409 translator + rollback; R07, R08, R09.

Plus a test fix in `tests/integration/test_tenants.py` (`404 → 403`) aligned with the unified 403 contract.

**CI suite**: 540 passed, 0 failed.

## Key Risk Callouts (RK)

- **RK-1** — Service-layer signature change (functions now take `current_user` and a pre-checked `target`). All callers were updated in PR-A.
- **RK-2** — Superadmin elevation window between `set_config(..., true)` SET LOCAL and `set_tenant_context` restore. `try/finally` guarantees context restoration on exception.
- **RK-3** — `e.orig.pgcode` is asyncpg-specific. Code uses `getattr(exc.orig, "pgcode", None) == "23505"` so a missing attribute falls through to `raise` (no silent mistranslation).
- **RK-6** — Cross-tenant tenant GET now returns 403 (was 404). The test at `test_tenants_integration.py:406` was updated in the same PR.
- **RK-7** — `update_user` and `deactivate_user` now take pre-checked `target`; bypassing the Depends is mitigated via signature requirements and code comments.

## Persisted Artifact IDs (Engram traceability)

This report itself is persisted to Engram with:
- `title`: `sdd/fix-f1-remaining-rls-403-and-email-409/archive-report`
- `topic_key`: `sdd/fix-f1-remaining-rls-403-and-email-409/archive-report`
- `type`: `architecture`
- `project`: `soc360-pymes`
- `capture_prompt`: `false` (automated SDD artifact)

Predecessor artifacts persisted by prior SDD phases (live under matching topic keys in Engram):
- `#321` — `sdd/fix-f1-remaining-rls-403-and-email-409/proposal` (architecture)
- `#324` — `sdd/fix-f1-remaining-rls-403-and-email-409/design` (architecture)
- `#327` — `sdd/fix-f1-remaining-rls-403-and-email-409/tasks` (architecture)
- `#329` — `sdd/fix-f1-remaining-rls-403-and-email-409/apply-progress` (architecture, PR-A)
- `#332` — `sdd/fix-f1-remaining-rls-403-and-email-409/verify-report` (architecture)

All observation IDs are recorded here for downstream traceability.

## Accepted Warnings Carried Forward

These WARNINGs are non-blocking by the strict archive policy. They were recorded in the verify report and carry through to the archive:

1. **`test_email_unique_globally_returns_409` failure during PR-A** — Expected; this test is PR-B scope. After PR-B landed, full CI suite passed (540/0).
2. **Pre-existing ruff F821 on `EventBus` forward reference** — Confirmed pre-existing per apply-progress note; not introduced by PR-A or PR-B.
3. **ruff reports 27 errors** — All pre-existing in `app/` and `tests/`; 0 introduced by this change.

## Cycle Status

| Phase | Status |
|-------|--------|
| explore | done (via prior sessions) |
| propose | done (proposal.md) |
| spec | done (specs/fix-f1-remaining-rls-403-and-email-409/spec.md) |
| design | done (design.md) |
| tasks | done (23/23) |
| apply | done (23/23; PR-0 + PR-A + PR-B all merged via PR #124) |
| verify | done (PASS WITH WARNINGS; no CRITICAL) |
| archive | done (this report) |

SDD cycle complete for `fix-f1-remaining-rls-403-and-email-409`. Ready for the next change.
