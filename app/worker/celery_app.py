"""Celery application for asynchronous scan execution (F2 slice 6).

Run scans with ``celery -A app.worker.celery_app:celery_app worker -Q scans``.
Run maintenance separately with
``celery -A app.worker.celery_app:celery_app worker -Q maintenance``.
Configuration is resolved lazily on first access to ``celery_app.conf`` so
importing this module never validates settings or touches the broker.
"""

from __future__ import annotations

from typing import Any, Protocol

from celery import Celery
from pydantic import SecretStr

from app.core.config import settings
from app.modules.scans.executor import NMAP_TIMEOUT_SECONDS

# Margin between Nmap's own timeout and Celery's soft limit, and between the
# soft and hard limits, so cleanup can run before the worker is killed.
TIME_LIMIT_MARGIN_SECONDS = 300
# The broker redelivers unacknowledged messages after this delay; it must exceed
# the hard limit or a running scan would be delivered to a second worker.
VISIBILITY_TIMEOUT_MARGIN_SECONDS = 600
REAP_INTERVAL_SECONDS = 300
PUMP_INTERVAL_SECONDS = 60
PUMP_MAX_BELLS = 10
SCAN_QUEUE = "scans"
MAINTENANCE_QUEUE = "maintenance"
MAINTENANCE_SOFT_LIMIT_SECONDS = 60
MAINTENANCE_HARD_LIMIT_SECONDS = 120
BROKER_SOCKET_TIMEOUT_SECONDS = 5


def hard_time_limit_seconds() -> int:
    return int(NMAP_TIMEOUT_SECONDS) + 2 * TIME_LIMIT_MARGIN_SECONDS


STALE_SCAN_SECONDS = hard_time_limit_seconds() + TIME_LIMIT_MARGIN_SECONDS


class BrokerSettings(Protocol):
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_DB: int
    REDIS_PASSWORD: SecretStr
    CELERY_BROKER_REDIS_DB: int


def build_broker_url(config: BrokerSettings) -> str:
    """Return the broker URL; credentials travel separately, never in the URL."""
    if config.CELERY_BROKER_REDIS_DB == config.REDIS_DB:
        raise ValueError(
            "CELERY_BROKER_REDIS_DB must differ from REDIS_DB to isolate the broker"
        )
    return f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/{config.CELERY_BROKER_REDIS_DB}"


def build_celery_config(config: BrokerSettings) -> dict[str, Any]:
    """Celery settings for at-least-once, JSON-only scan delivery."""
    soft_limit = int(NMAP_TIMEOUT_SECONDS) + TIME_LIMIT_MARGIN_SECONDS
    hard_limit = hard_time_limit_seconds()
    material = config.REDIS_PASSWORD.get_secret_value()
    return {
        "broker_url": build_broker_url(config),
        "broker_password": material or None,
        "broker_connection_retry_on_startup": True,
        "broker_transport_options": {
            "visibility_timeout": hard_limit + VISIBILITY_TIMEOUT_MARGIN_SECONDS,
            "socket_timeout": BROKER_SOCKET_TIMEOUT_SECONDS,
            "socket_connect_timeout": BROKER_SOCKET_TIMEOUT_SECONDS,
        },
        "task_default_queue": SCAN_QUEUE,
        "task_routes": {
            "scans.pump": {"queue": MAINTENANCE_QUEUE},
            "scans.reap": {"queue": MAINTENANCE_QUEUE},
        },
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "task_ignore_result": True,
        "result_backend": None,
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "worker_prefetch_multiplier": 1,
        "task_soft_time_limit": soft_limit,
        "task_time_limit": hard_limit,
        "beat_schedule": {
            "scans.reap": {"task": "scans.reap", "schedule": REAP_INTERVAL_SECONDS},
            "scans.pump": {"task": "scans.pump", "schedule": PUMP_INTERVAL_SECONDS},
        },
        "timezone": "UTC",
        "enable_utc": True,
    }


def create_celery_app(config: BrokerSettings) -> Celery:
    app = Celery("soc360", set_as_current=False, include=["app.worker.tasks"])
    app.add_defaults(lambda: build_celery_config(config))
    return app


celery_app = create_celery_app(settings)
