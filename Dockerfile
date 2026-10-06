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

# Copy application source and entrypoint.
COPY app/ ./app/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Writable directory for multiprocess Prometheus metric files.
# Each Gunicorn worker writes its own <metric>_<pid>.db file here.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
RUN mkdir -p "${PROMETHEUS_MULTIPROC_DIR}"

# Gunicorn must be in the venv for the entrypoint.
# The gunicorn_conf.py is created in PR4; PR3 only provides the metrics module
# and the entrypoint so the container is buildable.

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
