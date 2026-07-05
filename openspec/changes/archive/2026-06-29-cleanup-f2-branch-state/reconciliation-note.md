# Reconciliation Note: Cleanup F2 Branch State

## Source of Truth Decision

**`main` is the single source of truth.**

All future feature work branches from `main` and lands through reviewed PRs. The legacy `develop` integration branch is retired. This aligns the repository with the agreed workflow and removes ambiguity about which trunk carries authoritative history.

Rationale:
- `main` already reflects the reviewed, revert-corrected state (e.g., LLM abstraction revert in PR #4 revert).
- `develop` carries an unreviewed demo delta (PR #99) that must not enter `main` without its own PR.
- Dual-source or `develop`-first integration adds merge overhead and drift risk without benefit now that the team uses feature branches + PRs.

## Branch Classification Matrix

| Branch | Current Base / HEAD | Classification | Rationale | Action |
|--------|---------------------|----------------|-----------|--------|
| `main` | `93a1a06` | **Source of truth** | Clean trunk; all reverts and fixes applied | Continue branching from here |
| `develop` | `a63955b` (one merge ahead of `main`) | **Retired integration branch** | Holds only the PR #99 demo delta | Extract demo content, then stop using |
| `feat/f2-foundation-alignment` | `99692c4` (branched from `93a1a06`) | **Hold / rescue exceptions** | Contains F2 domain exceptions (`app/core/exceptions.py`, 18 LOC) plus the demo delta inherited from `develop` | Cherry-pick exceptions to a new small branch; do not merge wholesale |
| `feat/f2-pr-slicing` | `c2740b3` (based on stale `b05dfd4`) | **Needs rebase / reanchor** | Full F2 chain head; base predates `main` LLM abstraction revert | Rebase onto current `main` before any PR |
| `feat/f2-pr-slicing-01-migration` | `939af2f` | **Redundant / chain ancestor** | Merged back into the slicing chain | Archive note only; no separate PR |
| `feat/f2-pr-slicing-02-alembic-verify` | `8f7fac0` | **Redundant / chain ancestor** | Merged back into the slicing chain | Archive note only; no separate PR |
| `feat/f2-pr-slicing-03-unit-tests` | `4a158e3` | **Redundant / chain ancestor** | Merged back into the slicing chain | Archive note only; no separate PR |
| `feat/f2-pr-slicing-04-integration-asset-scan` | `adb862e` | **Redundant / chain ancestor** | Merged back into the slicing chain | Archive note only; no separate PR |
| `feat/f2-pr-slicing-05-integration-vuln-report-cascade` | `5cf7ca4` | **Redundant / chain ancestor** | Merged back into the slicing chain; cumulative content lives in `feat/f2-pr-slicing` | Archive note only; no separate PR |
| `feat/prd-v1-mvp-junio` | `f6ddf2f` | **Superseded / historical** | Pre-dates current `main`; planning artifacts no longer guide scope | Keep for audit, do not use for scope cuts |
| `chore/github-actions-ci` | current workspace branch | **Out of scope** | CI config work unrelated to F2 cleanup | Reference only; not part of this change |

## Demo Delta Rescue Path

`develop` adds 474 lines across 9 files (PR #99):

- `docker-compose.yml`
- `docker/vulnerable-target/` (`Dockerfile`, `entrypoint.sh`, four banner files)
- `docs/demo.md`
- `tests/verify_demo_target.sh`

Because this delta is useful demo infrastructure but must not be pulled into `main` unreviewed, rescue it via cherry-pick to a new branch:

```text
feat/demo-vulnerable-target  ← cherry-pick e87efe0 from develop
```

That branch will be reviewed and merged through a normal PR. It is **not** part of this cleanup change.

## F2 Domain Exceptions Rescue Decision

`feat/f2-foundation-alignment` adds F2 domain exceptions (`AssetError`, `ScanError`, `VulnerabilityError`, `ReportError`) in `app/core/exceptions.py` plus tests in `tests/unit/test_f2_exceptions.py`. These exceptions follow the existing `AppError` pattern and are safe, foundational infrastructure.

**Decision: Rescue the exceptions now via a separate small branch/work unit.**

```text
feat/f2-domain-exceptions  ← cherry-pick 99692c4 (or extract exceptions file only)
```

This keeps the rescue out of the docs-only cleanup change and gives it its own focused PR. If code is touched, it must be in this separate branch, not mixed into the cleanup branch.

## F2 Slicing Chain Stale / Reanchor Notes

The `feat/f2-pr-slicing` chain (including `feat/f2-pr-slicing-01..05`) is based on `b05dfd4`, an older point on `main` that still includes the LLM abstraction layer. Current `main` (`93a1a06`) has since reverted that layer. Consequently:

- The chain's cumulative diff against current `main` (~3,581 lines across 30 files) includes both the intended F2 models/migration/tests and stale LLM-abstraction files.
- A direct rebase will conflict on reverted LLM files (`app/core/llm.py`, `docs/llm-abstraction.md`, `tests/unit/test_llm_*.py`).

**Action**: Before any F2 PR is opened, reanchor the slicing chain onto current `main`. Resolve or drop stale LLM-abstraction changes so that only F2-domain work remains. The chain itself is redundant after consolidation; the canonical F2 implementation branch is `feat/f2-pr-slicing`.

## `prd-v1-mvp-junio` Superseded / Historical Decision

`feat/prd-v1-mvp-junio` and its OpenSpec folder (`openspec/changes/prd-v1-mvp-junio/`) represent historical planning for a June MVP scope cut. That constraint is now superseded.

**Decision**: Treat `prd-v1-mvp-junio` as historical documentation only. Future F2 planning uses the full project scope and incremental slices; do not use the June MVP artifacts to shorten or constrain scope. The folder may be archived later for audit purposes, but its planning decisions are no longer active.

## Summary of Immediate Consequences

- Branch new F2 work from `main`.
- Do not merge `develop` into `main` wholesale.
- Rescue demo content to `feat/demo-vulnerable-target`.
- Rescue F2 exceptions to `feat/f2-domain-exceptions`.
- Reanchor `feat/f2-pr-slicing` onto `main` before reopening F2 implementation PRs.
- Leave `prd-v1-mvp-junio` untouched except for the historical note above.
