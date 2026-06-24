# Archive Report: Rescue F2 Domain Exceptions

**Change**: `rescue-f2-domain-exceptions`
**Mode**: HYBRID (Engram + filesystem)
**Archived on**: 2026-06-24
**Source of truth**: PR #111 merged at `056cdf9` on `main` (2026-06-24T14:26:01Z)
**Archived to**: `openspec/changes/archive/2026-06-24-rescue-f2-domain-exceptions/`

## Outcome

PASS. The change is fully planned, implemented, verified, and archived.
SDD cycle complete for the first incremental slice of the main-based F2 rescue chain.

## Gates Evaluated

| Gate | Result | Evidence |
|------|--------|----------|
| PR #111 merged to `main` | PASS | `gh pr view 111` returns `state: MERGED`; `mergeCommit.oid = 056cdf9`; `mergedAt = 2026-06-24T14:26:01Z`. |
| Local `main` synced to `origin/main` | PASS | `git log main --oneline -1` → `056cdf9`; `git status` shows the fast-forward merge and no local drift. |
| F2 exception classes present on `main` | PASS | `grep "AssetError\|ScanError\|VulnerabilityError\|ReportError" app/core/exceptions.py` shows all four at lines 68/72/76/80; `tests/unit/test_f2_exceptions.py` exists (137 lines). |
| Task Completion Gate (no unchecked impl tasks) | PASS | `openspec/changes/.../tasks.md` shows all 11 tasks in Phases 1-4 marked `[x]` (1.1-1.3, 2.1-2.2, 3.1-3.3, 4.1-4.3). |
| Verify gate (no CRITICAL issues) | PASS | `verify-report.md` verdict is `PASS WITH WARNINGS`; explicit `CRITICAL: None`. Only WARNINGs are: local full-suite DB blocker, intentional `test_vulnerabilityerror_custom_status_code` addition, unrelated untracked OpenSpec/project artifacts. |
| No spec deltas to sync | PASS | Proposal declares `Capabilities: New = None, Modified = None`; the change folder contains no `specs/` subdirectory. `openspec/specs/` only holds `readme/` (no capability covers core exceptions). |
| Untracked files preserved | PASS | `cleanup-f2-branch-state/`, `openspec/config.yaml`, `openspec/project/`, `.python-version`, plus the untracked `proposal.md` / `design.md` carried through the archive move. |

## Files Archived

| File | Tracked? | Source | Destination |
|------|----------|--------|-------------|
| `proposal.md` | untracked | `openspec/changes/rescue-f2-domain-exceptions/` | `openspec/changes/archive/2026-06-24-rescue-f2-domain-exceptions/proposal.md` |
| `design.md` | untracked | `openspec/changes/rescue-f2-domain-exceptions/` | `openspec/changes/archive/2026-06-24-rescue-f2-domain-exceptions/design.md` |
| `tasks.md` | tracked (commit `056cdf9`) | `openspec/changes/rescue-f2-domain-exceptions/` | `openspec/changes/archive/2026-06-24-rescue-f2-domain-exceptions/tasks.md` |
| `apply-progress.md` | tracked (commit `056cdf9`) | `openspec/changes/rescue-f2-domain-exceptions/` | `openspec/changes/archive/2026-06-24-rescue-f2-domain-exceptions/apply-progress.md` |
| `verify-report.md` | tracked (commit `056cdf9`) | `openspec/changes/rescue-f2-domain-exceptions/` | `openspec/changes/archive/2026-06-24-rescue-f2-domain-exceptions/verify-report.md` |

No `specs/` subfolder existed in the change; therefore no main-spec merge was required.

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| (none) | none | Proposal explicitly states `New Capabilities: None` and `Modified Capabilities: None`. `openspec/specs/` holds only `readme/`; no F2 capability covers core exception classes. |

## Archive Operation Detail

- Tracked files moved with `git mv` (preserves rename history in git index).
- Untracked files moved with plain `mv` (no history to preserve).
- Empty source directory removed via `rmdir`.
- `git status` now shows three rename entries (`R`) plus the two moved untracked files at the new path.

## Production Code Landed via PR #111

| File | Change | Lines |
|------|--------|-------|
| `app/core/exceptions.py` | Appended four bare `AppError` subclasses with Spanish docstrings and `# ── F2 Domain Exceptions ──` separator | +18 |
| `tests/unit/test_f2_exceptions.py` | New DB-free unit tests (hierarchy, default/custom status, detail, `str()`, module-state invariance; 25 tests) | +137 (new file) |

Forbidden-area diff was empty. The PR is the first slice of the main-based F2 rescue chain (issue #91).

## Persisted Artifact IDs (Engram traceability)

This report itself is persisted to Engram with:
- `title`: `sdd/rescue-f2-domain-exceptions/archive-report`
- `topic_key`: `sdd/rescue-f2-domain-exceptions/archive-report`
- `type`: `architecture`
- `project`: `soc360-pymes`
- `capture_prompt`: `false` (automated SDD artifact)

Predecessor artifacts persisted by prior SDD phases (proposal, design, tasks, apply-progress, verify-report) live under the matching topic keys in Engram and remain queryable for the next slices of the F2 rescue chain.

## Staging State

- The three `git mv` operations show as renames in the working tree (not yet committed).
- The two untracked files (`proposal.md`, `design.md`) moved to the archive path but remain untracked.
- A commit is NOT created by `sdd-archive`. The orchestrator / user decides whether to commit the rename as a separate housekeeping commit.

## Roadmap Recommendation

PR #111 is the **first incremental slice** of the main-based F2 rescue chain. Per the proposal and the `cleanup-f2-branch-state` reconciliation, the next slices are likely:

1. **F2 foundation alignment** — continue manual extraction of low-risk F2 surface (no models, no migrations, no routers). Candidates per the rescue scope: domain helpers, enums, Pydantic schemas, lightweight invariants that do not require a DB or runtime wiring.
2. **F2 PR-slicing chain** — the existing `feat/f2-pr-slicing-*` branches on `origin` are out of scope for the main-based rescue (they sit on top of demo-target commits). Re-evaluate those branches and re-slice from `main` if any of their surface is still needed.
3. **DB-free unit test isolation** — follow the verify-report SUGGESTION: isolate pure unit files from the root autouse DB fixture so `--confcutdir=tests/unit` is no longer required for DB-free files.

## Warnings Carried Forward

- Local full unit suite is environment-blocked (no PostgreSQL on `localhost:5433`); CI is the source of truth for full-suite verification. Not a release blocker; already PASS WITH WARNINGS in `verify-report.md`.
- The test file intentionally adds `test_vulnerabilityerror_custom_status_code` (test-only, improves edge coverage). Tracked in `verify-report.md` WARNINGs.
- Workspace still contains unrelated untracked artifacts (`openspec/project/`, `openspec/config.yaml`, `cleanup-f2-branch-state/`, `.python-version`). They are out of scope for this change and were preserved untouched per the rescue-phase safety contract.

## Cycle Status

| Phase | Status |
|-------|--------|
| propose | done |
| spec | skipped (no capabilities; n/a) |
| design | done |
| tasks | done (11/11) |
| apply | done (11/11; verified by PR #111 review) |
| verify | done (PASS WITH WARNINGS; no CRITICAL) |
| archive | done (this report) |

SDD cycle complete for `rescue-f2-domain-exceptions`. Ready for the next change.
