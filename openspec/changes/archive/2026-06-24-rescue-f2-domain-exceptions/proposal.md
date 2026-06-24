# Proposal: Rescue F2 Domain Exceptions

## Intent
Land the foundational F2 domain exception types (`AssetError`, `ScanError`, `VulnerabilityError`, `ReportError`) on `main` as the first incremental slice of the main-based F2 rescue chain (issue #91). `main` is the source of truth; `develop` is retired/historical and is NOT a merge target. Smallest, lowest-risk F2 slice — no models, services, migrations, or routers — unblocks later F2 changes to raise typed domain errors instead of generic `AppError`.

> **CAUTION — structural rescue phase.** Do NOT broad `git cherry-pick` `feat/f2-foundation-alignment` unless explicitly approved. The exceptions commit (99692c4) sits on top of the demo-target commit (e87efe0, 474 LOC / 9 files) and a merge commit (a63955b), so a cherry-pick drags unrelated history. Use **manual path extraction only**.

## Scope

### In Scope
- Manually extract the four F2 domain exception classes from `origin/feat/f2-foundation-alignment` (commit 99692c4) into `app/core/exceptions.py`, preserving `AppError` subclass style (Spanish docstring, no custom `__init__`, inherited `status_code=400`).
- Restore the DB-free unit test file `tests/unit/test_f2_exceptions.py`, **cleaning odd test names** to readable form: `test_asserterror_*` → `test_asseterror_*`, `test_scannerror_*` → `test_scanerror_*` (fix doubled `n`). Assertions unchanged.
- Run targeted + full unit tests to prove hierarchy, status codes, detail, `str`, no module-state leak.
- OpenSpec artifact folder `openspec/changes/rescue-f2-domain-exceptions/`.

### Out of Scope (forbidden — must NOT be touched)
- `.github/workflows/ci.yml` (CI) — `main` already correct (PR #106).
- `tests/unit/test_main_lifespan.py` (lifespan tests) — correct on `main` (PR #110).
- `tests/unit/test_tenants.py` (tenant tests) — correct on `main` (PR #108).
- `docker/vulnerable-target/`, `docs/demo.md`, `docker-compose.yml` (demo target) — future separate workstream needing deep Docker/infra/security review (opt-in compose profile; services, container names, networks, ports, profiles, env vars, startup time, normal `docker compose up`).
- Migrations, routers, services, agents, runtime call sites.
- Broad branch merge / cherry-pick of `feat/f2-foundation-alignment`.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- None

> Internal foundation: no spec-level behavior visible to users. `openspec/specs/` holds only `readme/`; no capability covers core exceptions, so sdd-spec has no deltas.

## Approach
1. Branch `feat/f2-domain-exceptions` from `main` (source of truth per issue #91).
2. `git diff --stat main..origin/feat/f2-foundation-alignment -- app/core/exceptions.py tests/unit/test_f2_exceptions.py` confirms +18 / +132 = 150 LOC across exactly two files.
3. **Manual path extraction only** (apply the two file diffs by hand). Never `git cherry-pick` — it drags the demo-target and merge commits.
4. Preserve style: append after `LLMResponseError`, keep `# ── F2 Domain Exceptions ──` separator, Spanish docstrings matching `TenantError`/`UserError`. Rename odd test methods to readable names.
5. `pytest tests/unit/test_f2_exceptions.py -v`; confirm full unit suite green. `git diff --stat` audit proves only the two source files changed.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/core/exceptions.py` | Modified | Append 4 F2 domain exception classes (+18) |
| `tests/unit/test_f2_exceptions.py` | New | DB-free unit tests with cleaned names (+132) |
| `openspec/changes/rescue-f2-domain-exceptions/` | New | Proposal + downstream SDD artifacts |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Cherry-pick drags demo-target / merge commits | High if attempted | Manual extraction only; cherry-pick forbidden unless explicitly approved |
| Accidental edits to CI/lifespan/tenant/docker files | Low | Forbidden-paths list above; `git diff --stat` audit before commit |
| Test-name rename hides a behaviour change | Low | Rename identifiers only; assertions untouched; targeted tests prove equivalence |
| Branch base drift from `main` | Low | Branch fresh from `main`; never rebase on `develop` |

## Rollback Plan
Revert the single commit on `feat/f2-domain-exceptions`; `app/core/exceptions.py` returns to 63 lines and `tests/unit/test_f2_exceptions.py` is deleted. No migration or data impact.

## Dependencies
- `main` is source of truth; `develop` retired/historical (issue #91, OPEN, main-based rescue chain).
- Source branch `origin/feat/f2-foundation-alignment` (commit 99692c4) available for manual extraction.

## Success Criteria
- [ ] Four F2 domain exception classes in `app/core/exceptions.py`, each `issubclass(<Exc>, AppError)`.
- [ ] `pytest tests/unit/test_f2_exceptions.py` green.
- [ ] Full unit suite green; no integration/API/e2e regression.
- [ ] No forbidden-area files touched (CI, lifespan, tenant, docker/demo, migrations, routers/services).
- [ ] PR diff ≤ 400 changed lines; only the two source files plus OpenSpec artifacts.
