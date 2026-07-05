# Branch Roadmap: Incremental F2 Delivery

This roadmap defines the order in which F2 work should be reintroduced from the existing branch inventory. It is a planning document only; execution happens in later changes.

## Guiding Principles

1. **Source of truth is `main`.** Every slice branches from the current `main` HEAD.
2. **One concern per PR.** Keep rescue PRs and cleanup PRs separate from implementation PRs.
3. **Rescue before reimplementation.** Recover safe foundational assets (exceptions) before rebasing the full F2 model chain.
4. **Historical planning does not constrain scope.** `prd-v1-mvp-junio` is superseded; future F2 work uses full project scope and incremental slices.

## Immediate Follow-up PRs (outside this cleanup change)

These PRs are listed here for visibility but are **not** part of `cleanup-f2-branch-state`. They should be opened as separate, focused work units immediately after the cleanup decisions are accepted.

| # | Branch / PR | Purpose | Source Material | Approx. Size |
|---|-------------|---------|-----------------|--------------|
| 1 | `chore/github-actions-ci` | CI configuration (already in flight) | workspace branch | out of scope |
| 2 | `feat/demo-vulnerable-target` | Rescue isolated vulnerable-target demo from `develop` | Cherry-pick `e87efe0` from `develop` | ~474 lines / 9 files |
| 3 | `feat/f2-domain-exceptions` | Rescue F2 domain exceptions from `feat/f2-foundation-alignment` | Cherry-pick `99692c4` or extract `app/core/exceptions.py` + tests | ~150 lines / 2 files |

## F2 Implementation Slices (base order)

After the immediate rescue PRs, reintroduce F2 functionality in the following order. Each slice is a logical PR targeting `main`.

| Order | Slice | Goal | Branch Strategy | Notes |
|-------|-------|------|-----------------|-------|
| 1 | **F2 foundation — exceptions** | Land rescued `AssetError`, `ScanError`, `VulnerabilityError`, `ReportError` | `feat/f2-domain-exceptions` → `main` | Must merge before model code references these exceptions |
| 2 | **F2 models and migration** | Add Asset, Scan, Vulnerability, Report SQLAlchemy models plus Alembic migration | Reanchor `feat/f2-pr-slicing` onto `main`, then slice `feat/f2-models-migration` | Drop stale LLM-abstraction changes during rebase |
| 3 | **Alembic verification** | Verify migration graph integrity and downgrade roundtrip | `feat/f2-alembic-verify` | Can ride along with slice 2 if small |
| 4 | **Model unit tests** | DB-free unit tests for the four F2 models | `feat/f2-model-unit-tests` | Base on slice 2 |
| 5 | **Integration — Asset / Scan persistence** | DB-backed persistence tests for Asset and Scan | `feat/f2-integration-asset-scan` | Base on slice 2 |
| 6 | **Integration — Vulnerability / Report cascade** | DB-backed tests for Vulnerability and Report, including cascade deletes | `feat/f2-integration-vuln-report-cascade` | Base on slices 4–5 |
| 7 | **F2 service layer** | Services, use cases, API routers for F2 domains | New feature branches from `main` | Not present in existing branches; future work |

## Recommended Next Step

**Open `feat/f2-domain-exceptions` first.**

It is the smallest, safest rescue (~150 lines, well-scoped, follows existing patterns), unblocks later F2 code that needs these exception types, and keeps the cleanup change strictly documentation-only.

## Branch Inventory Status After Roadmap

| Branch | Final Disposition |
|--------|-------------------|
| `develop` | Retired; demo content extracted to `feat/demo-vulnerable-target` |
| `feat/f2-foundation-alignment` | Exceptions extracted; branch becomes historical |
| `feat/f2-pr-slicing` | Reanchored onto `main`; content split into slices 2–6 |
| `feat/f2-pr-slicing-01..05` | Redundant chain ancestors; no further use |
| `feat/prd-v1-mvp-junio` | Historical/superseded; kept for audit only |
