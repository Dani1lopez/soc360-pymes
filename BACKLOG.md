# Deferred engineering work

Triage rule: fix now only security issues, data-loss risks, or cheap changes.
Everything else lands here with enough context to resume without reopening
slice 6's design. Sizes are rough implementation effort, not commitments.
Historical review and runtime observations come from
`odd/tasks/f2-slice-6-celery.md`; current code takes precedence.

## Scan execution and runtime

### Bound pump/bell amplification
- **Why deferred:** advisory, not lost work; each pump caps new bells but does
  not account for bells already queued while workers are down.
- **Where:** `app/worker/tasks.py:145` (`_pump`),
  `app/worker/celery_app.py` (`PUMP_MAX_BELLS`); review R4-pump-amplification.
- **Size:** small–medium; bound backlog without making Redis authoritative.

### Bound multi-family execution to one task deadline
- **Why deferred:** one Nmap per address family runs sequentially, each up to
  `NMAP_TIMEOUT_SECONDS`; dual-stack targets can exceed the Celery hard limit.
- **Where:** `app/worker/celery_app.py:63-64`,
  `app/modules/scans/executor.py` (family loop); review R3-multifamily-deadline.
- **Size:** small–medium; share a deadline across families and test dual-stack.

### Separate supervisor and runner deadlines
- **Why deferred:** review R3-001 is non-blocking at the integral default;
  `int(timeout)` truncates fractional values and gives the supervisor the
  same deadline as Python, so either timeout path may win.
- **Where:** `app/modules/scans/executor.py:121` (run call; conversion follows).
- **Size:** small; define rounding/margin and test fractional timeouts.

### Add a build-context exclusion policy
- **Why deferred:** no `.dockerignore` exists; Dockerfile copies are scoped,
  but that does not exclude local environment files from the build context.
- **Where:** repository root; `Dockerfile` COPY instructions.
- **Size:** small; add exclusions and verify required build inputs remain.

### Filter worker network egress
- **Why deferred:** production hardening was outside this portfolio slice;
  the overlay currently provides no worker-specific egress policy. Reassess
  before enabling real scans, alongside asset ownership verification.
- **Where:** `docker-compose.worker.yml`; `app/modules/scans/targets.py`.
- **Size:** medium; select deployment-specific controls and test allowed traffic.

### Gate worker image and Nmap smoke scans in CI
- **Why deferred:** runtime smoke evidence is manual in the plan; current
  container regression checks inspect configuration, not a running image.
- **Where:** `tests/unit/test_worker_container_config.py`, `Dockerfile`.
- **Size:** medium; build worker and verify SYN/UDP with only `NET_RAW`,
  plus clear failure without the capability.

### Refresh executor module documentation
- **Why deferred:** cheap documentation cleanup, but outside this two-file
  documentation task's authorized surfaces.
- **Where:** `app/modules/scans/executor.py:1`; still says no HTTP trigger
  and defers live cancellation to slice 6 despite the router and watcher.
- **Size:** extra-small.

### Record Celery task compatibility before any rollout
- **Why deferred:** informational review R3-task-compatibility; the plan says
  this branch was never deployed, so no deployed queue migration is needed.
- **Where:** `app/worker/tasks.py` registers `scans.wake`, not removed
  `scans.run_scan`; `app/modules/scans/dispatch.py` sends argument-free bells.
- **Size:** small if rollout history changes; check legacy queued messages
  and agree a migration policy before deploying over an older worker.

## Dashboard

### Add a superadmin platform view
- **Why deferred:** `/dashboard/summary` always describes one tenant by design;
  a per-tenant breakdown with totals beside it is a separate endpoint.
- **Where:** proposed `GET /api/v1/dashboard/platform`;
  `docs/adr/f2-slice-7-dashboard.md`.
- **Size:** small–medium; reuse the service per tenant, decide caching.

### Revisit the scan success-rate failure classification
- **Why deferred:** `scan_success_30d` counts every failure reason, so
  infrastructure failures (`worker_lost`, `timeout`, `nonzero_exit`) lower a
  client's rate; separating infra from target failures needs a taxonomy.
- **Where:** `app/modules/dashboard/service.py` (scan success query);
  failure reasons in `app/modules/scans/nmap/runner.py` and
  `app/modules/scans/state.py`.
- **Size:** small once the classification is decided.

### Measure dashboard query plans on realistic data
- **Why deferred:** tests only check index definitions; on empty test tables
  every tenant-first index costs the same, so plans prove nothing.
- **Where:** `app/modules/dashboard/service.py`; migration `9e7a3b6c1f85`.
- **Size:** small; seed a large tenant locally and run `EXPLAIN ANALYZE`.

## LLM enrichment

### Replace generated references with deterministic lookup
What: resolve supplied identifiers through NVD/MITRE instead of generating
reference prose with the LLM. Why: citation filtering does not verify record
contents. Where: `app/modules/enrichment/prompts.py` and `service.py`.

### Measure cost and bound tenant relaunch usage
What: measure token usage/cost per run and add a per-tenant budget or rate limit
on relaunch endpoints. Why: concurrency and time limits do not cap monetary
cost or repeated requests. Where: `app/modules/enrichment/service.py` and
`router.py`.

### Account for publishing threads after timeout
What: address the fact that a publishing timeout does not cancel the
`apply_async` thread. Why: a request can report failure while publication later
succeeds. Where: `app/modules/enrichment/dispatch.py`; the same pattern exists
in `app/modules/scans/dispatch.py`.

### Report partial scan relaunch publication
What: report how many tasks were queued before a mid-loop publish failure.
Why: scan relaunch currently returns 503 without that count, obscuring partial
progress. Where: `app/modules/enrichment/router.py`.

### Scan relaunch misses stale successes
What: include stale successful rows in scan relaunch selection. Why:
`POST /scans/{id}/enrichment` only counts `ok` rows, so findings whose input,
prompt version or model changed are not queued when successful coverage is
complete; task-level identity checks only help if the task runs. Where:
`app/modules/enrichment/queries.py` (`scan_pending`, around line 65).

### Make the budget test robust on slow CI
What: revisit the 0.2-second budget in the integration test. Why: scheduling
on slow CI may exhaust it before fast outputs finish. Where:
`tests/integration/test_enrichment_service.py`.

### Cover the enrichment updated_at trigger
What: add a database-level test of timestamp updates. Why: the
`vulnerability_enrichments` trigger has no covering test recorded in the Slice 8
review. Where: migration `20261008_1200_add_vulnerability_enrichments_af8b4c7d2e96.py`
and enrichment integration tests.

### Add Spanish prompts
What: add `es` to the prompt language map and keep the settings validator literal
in sync. Why: language is parameterized but only English is accepted today.
Where: `app/modules/enrichment/prompts.py` and `app/core/config.py`.

### Render nested metadata deterministically
What: consider canonical JSON for nested metadata rather than `str()`.
Why: dictionary insertion order can change prompt rendering even though the
input hash uses canonical JSON. Where: `app/modules/enrichment/prompts.py`
(`_render_value`).

### Clean up minor enrichment inconsistencies
What: standardize `datetime.UTC` versus `timezone.utc`, review the redundant
single-column `vulnerability_id` index, expose a public prompt-sanitization
helper instead of importing `_sanitize_prompt_user_data`, and normalize CWE
metadata without the `CWE-` prefix. Why: reduce convention drift and avoid
removing otherwise relevant CWE citations. Where:
`app/modules/vulnerabilities/enrichment_models.py`, its migration,
`app/modules/enrichment/prompts.py` and `app/core/llm/providers.py`.

## Test and tooling debt

### Key the inline-import allowlist by name, not line number
- **Why deferred:** cheap but unrelated; any edit above the allowed imports in
  `app/main.py` shifts the line numbers and fails the test. This broke again
  in Slice 8 when `app/main.py` gained a router import.
- **Where:** `tests/unit/test_imports.py:41` (`PR1_INDENT_IMPORT_ALLOWLIST`).
- **Size:** small.

### Set Ruff's target Python version
- **Why deferred:** without `target-version`, Ruff reports builtins such as
  `anext` as undefined (F821) although the project runs Python 3.12.
- **Where:** `pyproject.toml` (no `[tool.ruff]` section yet).
- **Size:** small; fold into the Ruff debt cleanup below.

### Resolve repository-wide Ruff lint/format debt
- **Why deferred:** pre-existing and unrelated; the plan recorded 49 lint
  findings and 108 unformatted files, not remeasured by this documentation task.
- **Where:** repository-wide Python files; plan T1 verification status.
- **Size:** medium; separate mechanical cleanup from behavioral changes.

### Align Toxiproxy Redis authentication with local infrastructure
- **Why deferred:** environment-specific historical setup errors; the plan
  reports AUTH sent to passwordless Redis. Current cleanup uses an optional
  environment-sourced password, so reproduce before changing the fixture.
- **Where:** `tests/conftest.py:1330` (`_flush_toxiproxy_database`) and
  `tests/conftest.py:1340` (`toxiproxy_client`).
- **Size:** small; cover authenticated and passwordless local Redis.

### Isolate global claim tests from crashed-test leftovers
- **Why deferred:** test reliability advisory, not a production claim defect;
  global claims can select committed ready rows left by an earlier crash.
- **Where:** `tests/integration/test_scan_claim_next.py:110` (cross-tenant test).
- **Size:** small–medium; isolate the queue without weakening global-claim tests.
