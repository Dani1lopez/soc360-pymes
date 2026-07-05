# Proposal: Cleanup F2 Branch State

## Intent
F2 work is split across stale, drifted branches; `develop` holds a vulnerable-target demo delta (PR #99) absent from `main`; and `prd-v1-mvp-junio` planning no longer matches the incremental path. This housekeeping reconciles branch and artifact state so F2 proceeds incrementally — state first, cleanup later. No F2 implementation; no functional F2 code deletion.

## Scope

### In Scope
- Inventory and classify F2 branches/artifacts: `keep` / `rebase` / `archive` / `ignore`.
- Declare F2 source of truth (`main` vs `develop`) with rationale.
- Decide fate of `develop`'s demo delta (merge / keep / extract).
- Document fate of `feat/f2-*` branches; decide `prd-v1-mvp-junio` archive/trim (no spec rewrites).
- Branch roadmap: incremental F2 slices, base order, next-step recommendation.
- Record decisions in one reconciliation note.

### Out of Scope
- F2 functionality (services, routers, agents, migrations beyond prerequisites).
- Deletion of functional F2 code — deferred to the later cleanup change.
- Broader cleanup: code, test dedup, dependencies, docstrings, security comments.
- Rebase/merge execution — this change decides and documents only.
- Formal PRD/README rewrite; demo doc edits.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- None

> Pure Git/OpenSpec housekeeping; no spec-level changes, so sdd-spec has no deltas.

## Approach
1. Diff `main` vs `develop` (PR #99) and each F2 branch base vs current `main`.
2. Build a decision matrix (branch -> keep/rebase/archive/ignore) with rationale, conflict risk.
3. Pick source of truth; recommend demo delta disposition.
4. Write `branch-roadmap.md` plus a reconciliation note.
5. Archive or trim `prd-v1-mvp-junio` to remove stale drift.

## Affected Areas
- `openspec/changes/cleanup-f2-branch-state/` (New): proposal, roadmap, matrix, note.
- `openspec/changes/prd-v1-mvp-junio/` (Modified/Archived): stale planning reconciled.
- Git branches `feat/f2-*`, `develop` (Classified): notes only; no merges/deletes.

## Risks
- Branch base drift -> rebase conflicts later (High): matrix flags risk; rebase deferred.
- Wrong source-of-truth bakes demo delta into trunk (Med): tradeoffs recorded; reversible.
- Archiving `prd-v1-mvp-junio` loses context (Low): archive preserves audit trail.

## Rollback Plan
Docs/decisions only. Revert by deleting the change folder and restoring `prd-v1-mvp-junio/` from git. Dependencies: repo state, PR #99.

## Success Criteria
- [ ] F2 source of truth declared and justified.
- [ ] Every F2 feature branch classified with rationale.
- [ ] Branch roadmap lists incremental F2 slices in base order with next-step recommendation.
- [ ] `prd-v1-mvp-junio` fate decided.
- [ ] No F2 feature code implemented or functional F2 code deleted.

## Proposal question round
> Interactive mode — orchestrator surfaces to user before finalizing.
1. Source of truth: `main` (assume) — keep demo delta in trunk or extract it?
2. Rebase vs archive: `feat/f2-foundation-alignment` vs the `feat/f2-pr-slicing` chain?
3. `prd-v1-mvp-junio`: archive or trim (assume archive)?
