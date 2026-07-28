#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PR3 #260 — Multiprocess Prometheus entrypoint for Gunicorn.
#
# Prepares PROMETHEUS_MULTIPROC_DIR before launching Gunicorn and cleans it
# on graceful shutdown so that stale .db files from previous deployments
# do not pollute the aggregated metrics.
# ---------------------------------------------------------------------------
set -euo pipefail

PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus_multiproc}"

# 1. Ensure a clean multiprocess directory for this deployment.
rm -rf "${PROMETHEUS_MULTIPROC_DIR}"
mkdir -p "${PROMETHEUS_MULTIPROC_DIR}"
export PROMETHEUS_MULTIPROC_DIR

# 2. Launch Gunicorn with the project's configuration.
#    --forward-allowed-ips is needed when running behind a reverse proxy.
exec gunicorn app.main:app \
    --config gunicorn_conf.py \
    "$@"
