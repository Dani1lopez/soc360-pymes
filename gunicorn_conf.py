"""PR4 #260 — Gunicorn configuration.

Located at repo root so ``entrypoint.sh --config gunicorn_conf.py`` resolves
unmodified (no path manipulation). The only behaviour added in PR4 is the
``child_exit`` hook that marks a worker PID dead in the multiprocess
Prometheus registry, so its per-worker series drop from the next merged
scrape (spec scenario #10).

This file is intentionally tiny — any future Gunicorn tweaks (workers,
bind, log paths) belong here rather than being scattered across shell.
"""
from __future__ import annotations

from prometheus_client import multiprocess


def child_exit(server, worker) -> None:
    """Gunicorn ``child_exit`` hook — run when a worker process exits.

    Calls ``mark_process_dead(worker.pid)`` so the worker's per-process
    gauge series (the ``liveall`` / ``livemin`` / ``livemax`` modes that
    emit ``pid="..."`` labels) drop out of subsequent merged scrapes.

    The call is idempotent — ``mark_process_dead`` uses ``os.remove`` over
    ``glob.glob`` and silently swallows ``FileNotFoundError`` if the file
    was already removed (e.g. by an earlier exit of the same PID).
    """
    multiprocess.mark_process_dead(worker.pid)
