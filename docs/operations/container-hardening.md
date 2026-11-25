# Container hardening

How the shipped images and compose stacks are locked down, and the two knobs that
differ on a developer machine. This document is the reference behind the
`NMAP_PROCESS_SUPERVISION` comment in `app/core/config.py`.

## Runtime identity

The `worker` and `runtime` targets both end with `USER 10001:10001`. Nothing in the
image runs as root: the application, Gunicorn workers and the Nmap subprocesses all
inherit the unprivileged uid. Any file the container must write has to be owned by
`10001` (the image does this at build time with `COPY --chown`) or live on a writable
mount.

The runtime image copies exactly one file from `scripts/`: `scripts/seed_db.py`. The
seed script is what gives a fresh demo stack somebody to log in as, and it refuses to
run outside development. Every other operational script stays out of the build
context through `.dockerignore`, so an image layer never carries deploy tooling.

## Read-only root filesystem and `/tmp`

Application services run with `read_only: true` and a `tmpfs` mounted on `/tmp`.
Consequences:

- The root filesystem cannot be tampered with at runtime; a compromised process cannot
  drop a persistent binary into the image.
- `/tmp` is ephemeral memory, not the image's `/tmp` layer. Anything the image placed
  under `/tmp` at build time is hidden at runtime.
- Because of that, `entrypoint.sh` recreates `PROMETHEUS_MULTIPROC_DIR`
  (default `/tmp/prometheus_multiproc`) on every start: it removes stale per-worker
  `.db` files from a previous deployment and then `mkdir -p`s the directory before
  Gunicorn launches. Do not move that directory out of `/tmp` without giving it a
  writable mount.
- `HOME` is redirected to the writable tmpfs as well, so libraries that fall back to
  `$HOME` for caches do not fail on the read-only root.

## Capabilities

Every application service drops all Linux capabilities and sets
`no-new-privileges`, so a process cannot regain privileges through setuid binaries:

```yaml
cap_drop: [ALL]
security_opt: ["no-new-privileges:true"]
```

The `worker` service is the one deliberate exception for `no-new-privileges`: Nmap
relies on file capabilities for raw-socket scanning, and that option would disable
them. It still runs as uid `10001` with `cap_drop: [ALL]` and a read-only root.

## Published ports

In `docker-compose.yml` every published port is bound to loopback:

- `127.0.0.1:5433:5432` — dev PostgreSQL
- `127.0.0.1:5434:5432` — test PostgreSQL
- `127.0.0.1:6379:6379` — Redis
- `127.0.0.1:8474:8474` and `127.0.0.1:26379:26379` — Toxiproxy

A dev database, cache or fault-injection proxy is never reachable from the network,
only from the machine running the stack.

## Test database credential

`docker-compose.yml` contains no literal database password. The `postgres-test`
service reads `POSTGRES_TEST_PASSWORD` from the environment and refuses to start when
it is unset, rather than falling back to a well-known default that would ship in the
repository. Export it (or put it in your local env file) before
`docker compose --profile test up`. The same rule covers `POSTGRES_PASSWORD` for the
dev database and `REDIS_PASSWORD` for Redis.

## Nmap process supervision

`NMAP_PROCESS_SUPERVISION` defaults to `true`. Every Nmap run is wrapped in
`setpriv --pdeathsig TERM timeout`, so an orphaned scanner cannot outlive the worker
that started it. If the wrapper binaries are missing the run fails closed with
`nmap_supervisor_missing` instead of scanning unsupervised.

macOS has neither `setpriv` nor the expected `timeout` semantics, so a worker running
locally on macOS must opt out explicitly:

```bash
export NMAP_PROCESS_SUPERVISION=false
```

Containers keep the default. Do not disable supervision to make a local test pass in
CI or in an image: the opt-out exists for the macOS development host only.
