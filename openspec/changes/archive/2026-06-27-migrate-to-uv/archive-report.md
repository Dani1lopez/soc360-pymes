# Archive Report: migrate-to-uv

**Change**: `migrate-to-uv`
**Mode**: HYBRID (Engram + filesystem)
**Archived on**: 2026-06-27
**Archived to**: `openspec/changes/archive/2026-06-27-migrate-to-uv/`

## Outcome

**PASS WITH WARNINGS — INTENTIONAL ARCHIVE**

The change is fully planned, implemented, verified, and archived.
SDD cycle complete for PR-1 of the staged migration to uv project-mode packaging.

This is an **intentional-with-warnings archive**: the user explicitly accepted
the residual WARNINGs from `verify-report.md` and instructed the orchestrator
to proceed with archive. The archive report records that explicit decision
and the precise list of accepted warnings so the audit trail is complete.

## Acceptance Reason (explicit user override)

The latest `verify-report.md` verdict is `PASS WITH WARNINGS` with **no
CRITICAL issues**. The user explicitly chose to accept the WARNINGs and
archive the SDD change. The strict archive policy blocks only CRITICAL
verification issues; non-critical WARNINGs are overridable when the user
explicitly accepts them. The exact reason is recorded verbatim here:

> "The user explicitly chose to accept the warnings and archive the SDD
> change. Accepted warnings: (1) New uv/OpenSpec files are not staged/
> tracked yet because the user did not ask to stage/commit. (2) Docker
> daemon unavailable locally, so runtime compose/Postgres/Redis checks
> were not executed. (3) Full-project ruff/mypy/alembic have pre-existing/
> local environment blockers. (4) Remote GitHub Actions CI has not run
> yet. (5) Minor Strict TDD triangulation-count warning."

## Gates Evaluated

| Gate | Result | Evidence |
|------|--------|----------|
| Task Completion Gate (no unchecked impl tasks) | PASS | `openspec/changes/migrate-to-uv/tasks.md` shows all 11 tasks marked `[x]` across Phases 1-3 (1.1-1.3, 2.1-2.4, 3.1-3.4). |
| Verify report verdict | PASS WITH WARNINGS | `verify-report.md` line 7 records `Verdict: PASS WITH WARNINGS`. |
| CRITICAL issues in verify report | NONE | `verify-report.md` section "Issues Found → CRITICAL" contains `None`. |
| Delta spec destination created | PASS | `openspec/specs/dependency-management/spec.md` was newly created (no prior main spec existed for this domain). |
| Change folder moved to archive | PASS | `openspec/changes/migrate-to-uv/` removed; `openspec/changes/archive/2026-06-27-migrate-to-uv/` populated. |
| Archive contains all artifacts | PASS | Archived folder holds `proposal.md`, `design.md`, `tasks.md`, `apply-progress.md`, `verify-report.md`, `exploration.md`, and `specs/dependency-management/spec.md`. |
| No unrelated untracked paths touched | PASS | `openspec/changes/cleanup-f2-branch-state/`, `openspec/config.yaml`, and `openspec/project/` remain untouched. |
| No staging, committing, pushing, or PR creation | PASS | `sdd-archive` only moves files and writes the archive report; no `git add`, `git commit`, `git push`, or `gh pr create` was invoked. |
| `rules.archive` from `openspec/config.yaml` applied | PASS | Config sets `archive: require_delta_sync: true`; the new `dependency-management` main spec was created by direct copy (new domain — no destructive merge). |

## Files Archived

| File | Tracked? | Source | Destination |
|------|----------|--------|-------------|
| `proposal.md` | untracked | `openspec/changes/migrate-to-uv/` | `openspec/changes/archive/2026-06-27-migrate-to-uv/proposal.md` |
| `design.md` | untracked | `openspec/changes/migrate-to-uv/` | `openspec/changes/archive/2026-06-27-migrate-to-uv/design.md` |
| `tasks.md` | untracked | `openspec/changes/migrate-to-uv/` | `openspec/changes/archive/2026-06-27-migrate-to-uv/tasks.md` |
| `apply-progress.md` | untracked | `openspec/changes/migrate-to-uv/` | `openspec/changes/archive/2026-06-27-migrate-to-uv/apply-progress.md` |
| `verify-report.md` | untracked | `openspec/changes/migrate-to-uv/` | `openspec/changes/archive/2026-06-27-migrate-to-uv/verify-report.md` |
| `exploration.md` | untracked | `openspec/changes/migrate-to-uv/` | `openspec/changes/archive/2026-06-27-migrate-to-uv/exploration.md` |
| `specs/dependency-management/spec.md` | untracked | `openspec/changes/migrate-to-uv/specs/dependency-management/` | `openspec/changes/archive/2026-06-27-migrate-to-uv/specs/dependency-management/spec.md` |
| `archive-report.md` | untracked | (created by this phase) | `openspec/changes/archive/2026-06-27-migrate-to-uv/archive-report.md` |

All files were untracked per the verified `git ls-files` warning, so the
move used plain `mv` (no rename history to preserve). The empty source
directory was removed via `rmdir`.

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| `dependency-management` | Created (new domain) | 9 requirements added with 11 scenarios. Source was a full spec, not a delta — `openspec/specs/dependency-management/` did not exist before this archive. Copy performed as `cp` of the full spec file (no destructive merge). |

The new main spec at `openspec/specs/dependency-management/spec.md` now
serves as the source of truth for the uv project-mode packaging contract
and the pip rollback path. No other main spec was modified (proposal
explicitly defers any `readme` spec amendment to PR-3).

## Capabilities Touched

| Capability | Type | Notes |
|------------|------|-------|
| `dependency-management` | New | First canonical home for the uv packaging contract. |

Per the proposal, `readme` and other existing capabilities were not
modified in PR-1 — their amendments are deferred to follow-up SDD cycles.

## Persisted Artifact IDs (Engram traceability)

This report itself is persisted to Engram with:

- `title`: `sdd/migrate-to-uv/archive-report`
- `topic_key`: `sdd/migrate-to-uv/archive-report`
- `type`: `architecture`
- `project`: `soc360-pymes`
- `capture_prompt`: `false` (automated SDD artifact)

Predecessor artifacts persisted by prior SDD phases (proposal, design,
tasks, apply-progress, verify-report) live under the matching topic keys
in Engram and remain queryable for the next PRs of the migration chain
(PR-2, PR-3).

## Archive Operation Detail

- New main spec created via direct `cp` (no delta merge logic required —
  the destination did not exist, so the source spec is a full new spec,
  not a delta).
- Source change folder moved via `mv` of all contents into the archive
  folder, followed by `rmdir` on the now-empty source directory.
- `git status` post-archive shows the move; the new main spec at
  `openspec/specs/dependency-management/spec.md` is untracked, which is
  expected because the user did not ask to stage or commit.
- No rename detection is triggered by git because all files were already
  untracked; the move is a pure filesystem relocation.

## Accepted Warnings Carried Forward

These WARNINGs are non-blocking by the strict archive policy. They are
recorded here for traceability so the eventual PR can address them
without losing context.

1. **Pre-stage tracking is not proven.** `pyproject.toml`,
   `.python-version`, `uv.lock`, `tests/sdd/**`, and OpenSpec artifacts
   are untracked locally. The user explicitly instructed not to stage
   during this SDD cycle. The eventual PR must include the staged uv
   artifacts and a fresh `git ls-files` proof.
2. **Runtime infrastructure checks are blocked locally.** Docker daemon
   is unavailable (`connect: no such file or directory`), so runtime
   compose / Postgres / Redis / alembic migration cycle could not be
   executed. Static audit and CI parity are present.
3. **Full-project quality / infrastructure commands are not clean
   locally.** `uv run ruff check .` reports 28 pre-existing / out-of-
   scope findings; `uv run mypy .` is blocked by `docker/postgres-data`
   permissions; `uv run alembic upgrade head` is blocked by missing
   `GROQ_API_KEY` for the current local settings. These are
   pre-existing app / env issues, not uv migration implementation
   failures. Focused SDD test files pass ruff and mypy.
4. **Remote CI parity is statically verified only.** GitHub Actions
   was not executed in the local verify phase. The `test-uv` and `test`
   jobs are present in `.github/workflows/ci.yml` per static inspection.
5. **Minor Strict TDD triangulation-count mismatch.** `apply-progress.md`
   task 2.4 reports `✅ 2 cases`, while the Docker / Compose coverage
   is one combined static test (`test_no_dockerfile_and_compose_has_
   only_infrastructure_services`). The mismatch is informational and
   non-blocking.

## Cycle Status

| Phase | Status |
|-------|--------|
| explore | done (exploration.md) |
| propose | done (proposal.md) |
| spec | done (specs/dependency-management/spec.md) |
| design | done (design.md) |
| tasks | done (11/11) |
| apply | done (11/11; all_done) |
| verify | done (PASS WITH WARNINGS; no CRITICAL) |
| archive | done (this report; intentional-with-warnings) |

## Roadmap Recommendation

Per the proposal, this archive is the **first slice** of a three-PR
staged migration. The next slices are:

1. **PR-2 (future SDD cycle)** — drop the pip CI job once uv is proven
   on `main` for one or more merges; keep `requirements*.txt` tracked
   for one more release so the rollback path remains instant.
2. **PR-3 (future SDD cycle)** — delete `requirements.txt` and
   `requirements-dev.txt`, amend `openspec/specs/readme/spec.md` setup
   order, and re-anchor PRD `T-007` to `pyproject.toml` as the single
   source of truth.
3. **Future app image (out of scope of this change)** — when a
   `Dockerfile` is introduced, the design already documents the
   foresight rule: use `uv sync --frozen` with BuildKit cache mounts.

## Warnings From the Spec Merge

No destructive merge was performed. The new `dependency-management`
spec was copied into a previously non-existent destination, so no
existing requirements were removed, modified, or renamed. No
`config.yaml` `rules.archive` override was required.

## Cycle Status (final)

SDD cycle complete for `migrate-to-uv` (PR-1, intentional-with-warnings).
Ready for the next change.
