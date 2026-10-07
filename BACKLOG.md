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

## Test and tooling debt

### Key the inline-import allowlist by name, not line number
- **Why deferred:** cheap but unrelated; any edit above the allowed imports in
  `app/main.py` shifts the line numbers and fails the test.
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
