# Design: Cleanup F2 Branch State

## Technical Approach

Documentation-only reconciliation: produce a branch decision matrix, reconciliation note, and branch roadmap as OpenSpec artifacts under `openspec/changes/cleanup-f2-branch-state/`. No code changes, no branch merges/rebases/deletes executed in this change. All outputs are markdown documents that classify each branch and prescribe actions for later execution.

## Architecture Decisions

### Decision: Branch Governance Model

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `main` as single source of truth | Rejects develop's unreviewed delta; clean linear history | **Chosen** |
| `develop` as integration branch | Adds merge overhead; user confirmed this pattern is abandoned | Rejected |
| Dual source of truth | Ambiguous ownership; increases drift risk | Rejected |

**Rationale**: User confirmed `main` is the intended trunk. All future work uses feature branches from `main` + PRs. `develop` is retired as an integration branch.

### Decision: Develop Treatment

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Merge develop → main | Pulls unreviewed demo delta into trunk; conflicts with clean-main policy | Rejected |
| Cherry-pick demo delta to `feat/demo-vulnerable-target` | Isolates demo content; reviewable via PR; preserves audit trail | **Chosen** |
| Delete develop immediately | Loses demo delta before rescue | Rejected |

**Rationale**: Develop's only delta (PR #99, 474 lines across 9 files: `docker-compose.yml`, `docker/vulnerable-target/`, `docs/demo.md`, `tests/verify_demo_target.sh`) is useful demo infrastructure. Extract it to a feature branch for PR review, then stop using `develop`.

### Decision: F2 Branch Classification Strategy

| Branch | Base | Content | Classification | Action in this change |
|--------|------|---------|----------------|----------------------|
| `feat/f2-foundation-alignment` | `93a1a06` (main HEAD) | Demo delta + F2 exceptions (18 LOC) + exception tests (132 LOC) | **Classify — hold** | Document; no merge/delete |
| `feat/f2-pr-slicing` | `b05dfd4` (stale) | Full F2 chain: models, migration, alembic verify, unit + integration tests (3581 LOC) | **Classify — needs rebase** | Document; no merge/delete |
| `feat/f2-pr-slicing-01..05` | `b05dfd4` (stale) | Identical content (chain merged back); cumulative | **Classify — redundant** | Document; no merge/delete |
| `feat/prd-v1-mvp-junio` | older | SDD artifacts + older F2 experiments | **Archive** | Document; archive in later task |
| `chore/github-actions-ci` | N/A | CI config | **Out of scope** | Reference only |

**Rationale**: This change audits and classifies only. Execution (rebase, merge, delete) is deferred to sdd-tasks/sdd-apply. No functional F2 code is deleted per scope constraints.

### Decision: Deliverable Structure

| Deliverable | Format | Location |
|-------------|--------|----------|
| Branch decision matrix | Table in reconciliation note | `openspec/changes/cleanup-f2-branch-state/reconciliation-note.md` |
| Reconciliation note | Markdown narrative | Same file |
| Branch roadmap | Ordered list of F2 slices with base order | `openspec/changes/cleanup-f2-branch-state/branch-roadmap.md` |
| Next F2 slice recommendation | Section in roadmap | Same file |

## Data Flow

No application data flow — this is a documentation-only change.

```
Git branch inspection ──→ Decision matrix ──→ Reconciliation note
                                           ──→ Branch roadmap ──→ Next F2 slice
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `openspec/changes/cleanup-f2-branch-state/reconciliation-note.md` | Create | Branch decision matrix + reconciliation narrative |
| `openspec/changes/cleanup-f2-branch-state/branch-roadmap.md` | Create | Ordered F2 slice roadmap with next-step recommendation |

## Interfaces / Contracts

No new interfaces. Deliverables are markdown documents consumed by humans and later SDD phases.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Verification | Document correctness | Manual review: branch matrix matches `git branch -a` + `git log` output |
| Verification | No code changes | `git diff --stat` on apply must show only new markdown files |
| Verification | No F2 code deleted | Grep F2 module dirs — `__init__.py` stubs remain untouched |

No application test suite changes. This change produces documentation only.

## Migration / Rollout

No migration required. Documentation-only change.

## Rollback

Delete the two new markdown files. All changes are additive markdown under `openspec/changes/cleanup-f2-branch-state/`. Git reverts cleanly.

## Open Questions

- [ ] Should `feat/f2-foundation-alignment`'s F2 exceptions (18 LOC in `app/core/exceptions.py`) be cherry-picked to a new branch, or wait for the F2 slicing chain rebase? Deferred to tasks.
- [ ] Should `prd-v1-mvp-junio` be moved to `openspec/changes/archive/` or kept in-place with a superseded note? Deferred to tasks.
