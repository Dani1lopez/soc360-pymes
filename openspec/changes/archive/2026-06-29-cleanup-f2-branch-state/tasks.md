# Tasks: Cleanup F2 Branch State

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80-180 (docs only) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single docs PR now; separate rescue PRs later |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Reconcile branch state and write roadmap docs | PR 1 | Base on `main`; docs-only change |
| 2 | Rescue demo delta and F2 exceptions in separate branches | Immediate follow-up PRs | Keep outside this cleanup change |

## Phase 1: Branch Ground Truth

- [x] 1.1 Verify `main`, `develop`, `feat/f2-foundation-alignment`, `feat/f2-pr-slicing`, `feat/f2-pr-slicing-01..05`, and `feat/prd-v1-mvp-junio` with `git branch -a`, `git log --decorate`, and `git diff --stat`.
- [x] 1.2 Record `main` as source of truth, `develop` as retired integration branch, and `prd-v1-mvp-junio` as superseded/historical.
- [x] 1.3 Capture the branch classification matrix: `develop` → rescue/extract demo delta to `feat/demo-vulnerable-target`; `feat/f2-foundation-alignment` → rescue domain exceptions now in a separate small branch; `feat/f2-pr-slicing` and `feat/f2-pr-slicing-01..05` → stale/reanchor plan with explicit ancestry notes.

## Phase 2: Reconciliation Artifacts

- [x] 2.1 Create `openspec/changes/cleanup-f2-branch-state/reconciliation-note.md` with the matrix, rationale, and explicit `main` source-of-truth decision.
- [x] 2.2 Create `openspec/changes/cleanup-f2-branch-state/branch-roadmap.md` with incremental F2 slices, base order, and next-step recommendation.
- [x] 2.3 Note that `feat/f2-foundation-alignment`’s domain exceptions must be rescued now via a separate small work unit/branch if code is touched.

## Phase 3: Historical Cleanup Notes

- [x] 3.1 Mark `prd-v1-mvp-junio` as obsolete historical planning; do not use it to shorten scope.
- [x] 3.2 State that June MVP constraints are superseded; future F2 planning uses full project scope and incremental design.
- [x] 3.3 Record the demo delta rescue path as a future `feat/demo-vulnerable-target` cherry-pick branch, not part of this cleanup branch.

## Phase 4: Verification

- [x] 4.1 Re-check the docs against `proposal.md` and `design.md`.
- [x] 4.2 Confirm no code, merge, rebase, or delete action is performed in this change.
- [x] 4.3 Validate the final diff is limited to OpenSpec planning artifacts.
