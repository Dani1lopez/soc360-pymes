# ---------------------------------------------------------------------------
# PR3 #260 — Multiprocess Prometheus metrics Dockerfile.
#
# Stages: builder -> base -> worker; runtime (API) stays the default last stage.
# Never use Docker --privileged; Nmap's --privileged flag is unrelated.
# PROMETHEUS_MULTIPROC_DIR is a known writable path for per-worker .db files.
# ---------------------------------------------------------------------------

# ---- stage 1: dependencies ------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS builder

WORKDIR /app

# Copy lockfile and project metadata so uv sync can resolve offline.
COPY uv.lock pyproject.toml ./
COPY .python-version ./

# Install production deps into a virtualenv.
RUN uv sync --frozen --no-dev --no-install-project

# ---- shared virtualenv (no application code) ------------------------------
FROM python:3.12-slim-bookworm AS base

WORKDIR /app

# Copy the venv from the builder stage.
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# ---- non-root scanner -----------------------------------------------------
FROM base AS worker

ENV NMAP_PROCESS_SUPERVISION=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends nmap libcap2-bin \
    && rm -rf /var/lib/apt/lists/* \
    && setcap cap_net_raw+eip /usr/bin/nmap \
    && useradd --system --no-create-home --shell /usr/sbin/nologin scanner \
    && find / -xdev -perm /6000 -type f -exec chmod a-s {} +

COPY app/ ./app/
USER scanner
ENTRYPOINT ["celery", "-A", "app.worker.celery_app:celery_app", "worker"]
CMD ["--loglevel=INFO", "--concurrency=1", "--queues=scans"]

# ---- API runtime: keep last for plain docker build ------------------------
FROM base AS runtime

# Non-root runtime identity (SEC S7). The uid/gid are fixed so that every
# Compose service can pin them with `user: "10001:10001"`; a host-mounted
# volume or a bind mount then has a predictable owner instead of root.
# No home directory: the root filesystem is mounted read-only at runtime.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --no-create-home \
        --shell /usr/sbin/nologin app \
    && mkdir -p /tmp/prometheus_multiproc \
    && chown -R 10001:10001 /tmp/prometheus_multiproc

# Copy application source and entrypoint.
COPY --chown=10001:10001 app/ ./app/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Migration assets. The one-shot `migrate` service runs `alembic upgrade head`
# inside this image, so it needs the migration scripts, the Alembic
# configuration (whose script_location is `migrations` and whose
# prepend_sys_path is `.`) and the Gunicorn configuration referenced by
# entrypoint.sh.
COPY --chown=10001:10001 migrations/ ./migrations/
COPY --chown=10001:10001 alembic.ini ./
COPY --chown=10001:10001 gunicorn_conf.py ./

# Only the seed script travels with the image: it is the one file the runtime
# ever executes from scripts/, and it refuses to run outside development. The
# rest of scripts/ (bootstrap helpers, OpenAPI dump) is host tooling and stays
# out of the image and out of the build context.
COPY --chown=10001:10001 scripts/seed_db.py ./scripts/seed_db.py

# Run as the unprivileged user. `base` set WORKDIR /app, so this only changes
# identity, and /app stays readable because the copies above are owned by it.
USER 10001:10001

# Writable directory for multiprocess Prometheus metric files. Each Gunicorn
# worker writes its own <metric>_<pid>.db file here. It lives on /tmp so a
# read-only root filesystem can still back it with a tmpfs mount.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
# A read-only root filesystem cannot take __pycache__ writes; skip them instead
# of paying for failed opens on every import.
ENV PYTHONDONTWRITEBYTECODE=1
# Some libraries fall back to $HOME for caches; point it at the writable tmpfs
# so a read-only root filesystem never turns that into an error.
ENV HOME=/tmp

# Gunicorn must be in the venv for the entrypoint.

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
