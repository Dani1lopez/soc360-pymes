# ADR: PostgreSQL-backed asynchronous scan execution

## Status

Accepted, 2026-10-06.
The scan row is the work item; Redis messages only wake workers.
This ADR follows current code, not superseded message-as-work proposals.

## Context

Nmap can run for up to an hour per invocation. Keeping that work inside an
HTTP request would tie request availability to a long-running subprocess.
The executor uses a 3,600-second default (`app/modules/scans/executor.py`).

The application is multi-tenant: dispatch reserves tenant quota, while
execution must retain the claimed tenant's database context. Scanning
third-party hosts also carries legal risk; a valid target is not proof of
permission to scan it.

`SCAN_EXECUTION_ENABLED` defaults to false (`app/core/config.py`). Keep it off
until asset ownership verification is implemented. The switch blocks new
HTTP dispatches, worker claims and pump bells, including already-dispatched
pending rows. Running scans are stopped with `/cancel`; reaping is unaffected
(`app/modules/scans/router.py`, `app/worker/tasks.py`).

## Decision
**Flow:** request → PostgreSQL row → Redis bell → worker claim → supervised Nmap.
Beat drives the independent maintenance pump and reaper.

### 1. PostgreSQL is the queue; Redis is a doorbell

A ready row has `status='pending'` and non-null `dispatched_at`.
`scans.wake` takes no arguments and claims one row, not a message-supplied ID
(`app/modules/scans/dispatch.py`, `app/worker/tasks.py`).

`claim_next_scan` atomically updates the row selected with
`FOR UPDATE SKIP LOCKED`, repeating the ready predicate on the update.
Ordering by `dispatched_at`, then ID, gives FIFO among available rows; locked
rows are skipped rather than blocking other claimers (`app/modules/scans/state.py`).

The cross-tenant claim uses superadmin context only until commit. Execution
then uses the claimed tenant's context, a fresh event loop and a per-task
`NullPool` engine, disposed at task exit (`app/worker/tasks.py`).

Duplicate bells cannot execute an already-claimed row again. They may claim
other ready work; if none exists, they return `idle`. Lost bells leave work
in PostgreSQL for the pump to rediscover.

Message-as-work was rejected because row and message could disagree:
orphans, duplicate delivery, ambiguous publication and compensation would
require coordinating two sources of truth and their clocks. There is no
compensation or message expiry in the current dispatch path.

### 2. Use one clock for queue decisions

PostgreSQL `now()` sets `dispatched_at` and the worker claim's `started_at`.
It also defines the UTC quota day boundary and stale-running cutoff
(`app/modules/scans/service.py`, `app/modules/scans/state.py`).

Dispatch locks the tenant with `FOR NO KEY UPDATE`. Quota includes pending
reservations but excludes failed/cancelled rows that never started.
Celery limits are relative timers, not worker wall-clock comparisons.

This is not a claim that every timestamp uses PostgreSQL: the generic
`transition_scan` helper still uses Python time for its standalone running
transition and terminal timestamps (`app/modules/scans/state.py`).

### 3. Commit first; publish a bounded, best-effort bell

`POST /scans/{scan_id}/run` checks the switch and role, looks up the scan,
reserves dispatch and quota, then commits before publication. Missing scans
return 404; non-dispatchable scans return 409; exhausted quota returns 429
(`app/modules/scans/router.py`, `app/modules/scans/service.py`).

Publication uses `asyncio.to_thread` under a three-second `wait_for` deadline
with bounded retries. Redis socket/connect timeouts are five seconds; the
thread may outlive the request deadline (`app/modules/scans/dispatch.py`,
`app/worker/celery_app.py`).

A publication failure is logged and still returns 202. The committed row
remains reserved; there is no undo or broker-failure 503 response.

### 4. Recover lost bells and dead workers separately

Beat schedules `scans.pump` every 60 seconds. The pump counts at most ten
ready rows and sends that many bells (`app/worker/celery_app.py`,
`app/worker/tasks.py`, `app/modules/scans/state.py`).

Beat schedules `scans.reap` every 300 seconds. Running rows older than the
Celery hard limit plus margin become `failed/worker_lost`. Current limits
are 3,900 seconds soft, 4,200 hard, and a 4,500-second stale cutoff.

Under the configured hard-limit contract, worker loss is “a fact, not a
guess”: the task cannot still be alive past that bound. Pending rows are
not guessed lost or failed; they remain claimable. One scan per wake task
keeps the claim age aligned with the task lifetime.

### 5. Isolate maintenance from scan execution

Pump and reaper route to `maintenance`; scan workers consume only `scans`.
A separate unprivileged service consumes maintenance with concurrency one,
60-second soft and 120-second hard task limits (`app/worker/celery_app.py`,
`app/worker/tasks.py`, `docker-compose.worker.yml`).

Thus the reaper does not depend on the scan workers it watches. Beat and
maintenance use the API runtime image, no capabilities, read-only roots,
and `no-new-privileges`. If all services are down, recovery requires
operational restart and monitoring, not another task.

### 6. Grant only Nmap's required privilege

The worker runs as non-root `scanner`. Only `/usr/bin/nmap` receives the file
capability `cap_net_raw`; setuid/setgid bits are stripped (`Dockerfile`).
The container drops all capabilities and adds only `NET_RAW`, with a
read-only root, temporary `/tmp`, init and resource limits
(`docker-compose.worker.yml`).

`NET_ADMIN` is not needed for the fixed profile: the plan's T7-0/T7a smoke
record reports successful SYN/UDP scanning with `NET_RAW` only. Current
configuration is also checked by `tests/unit/test_worker_container_config.py`;
those checks do not reproduce the live scan.

The worker cannot use `no-new-privileges` with this file-capability design:
it prevents acquiring those capabilities on execution. Beat and maintenance
use it. Nmap's `--privileged` flag tells Nmap to trust available privileges;
it is not Docker `--privileged`, which is never used
(`app/modules/scans/nmap/command.py`, `docker-compose.worker.yml`).

### 7. Do not leave orphan Nmap processes

Linux clears the parent-death signal on exec of file-capability binaries
(`prctl(2)`). Setting it directly on Nmap therefore does not protect this
runtime. The runner instead launches:

```text
setpriv --pdeathsig TERM timeout --kill-after=5 <seconds> nmap ...
```

`timeout` retains the signal and forwards termination to Nmap.
The runner starts a new session and cleans up the process group
with TERM followed by KILL, including surviving descendants
(`app/modules/scans/nmap/runner.py`).

Supervised exit 126 maps to `nmap_not_permitted`; 124 maps to `timeout`.
Direct permission failures also map to `nmap_not_permitted`. Any other
nonzero exit fails before XML parsing, even if the XML looks valid.

Supervision is opt-in through `NMAP_PROCESS_SUPERVISION`, false by default
and enabled in the worker image because macOS development lacks `setpriv`
(`app/core/config.py`, `Dockerfile`, `app/modules/scans/executor.py`).
The fixed profile also bounds hosts to 55 minutes and scripts to five
minutes (`app/modules/scans/nmap/command.py`).

## Consequences

**Positive:** durable work has one source of truth; duplicate delivery is
safe; HTTP requests do not wait for Nmap; recovery is independent of scan
worker availability; raw-socket privilege is narrowly scoped.

**Negative:** PostgreSQL availability is required for dispatch and claims.
Lost bells wait for maintenance; repeated pumps can accumulate bells while
workers are down. Container runtime smoke coverage is not yet a CI gate.

**Accepted trade-offs:** no per-tenant scheduling fairness or concurrency
limits beyond daily quota; no live result backend; no worker-wide
`no-new-privileges`. Deferred work is recorded in `BACKLOG.md`.

## How to run
Prepare the required, gitignored `.env.worker` locally; never commit it.
It overrides the shared environment file. Configure the database for the
Compose `postgres` service on port 5432, or an external database; Redis uses
the Compose `redis` service. Keep scan execution disabled pending ownership
verification. Do not place credentials in commands or documentation.

```bash
docker compose -f docker-compose.yml -f docker-compose.worker.yml --profile worker up worker maintenance beat
```

Enable the infrastructure's `dev` profile as well when using local Postgres.
Run exactly one beat scheduler; duplicate schedulers multiply maintenance
messages (`docker-compose.worker.yml`).
