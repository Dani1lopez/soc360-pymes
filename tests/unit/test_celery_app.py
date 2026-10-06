"""Tests for the Celery application factory and broker configuration (F2 slice 6, T1)."""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from pydantic import SecretStr, ValidationError

from app.modules.scans.executor import NMAP_TIMEOUT_SECONDS
from app.worker.celery_app import (
    build_broker_url,
    build_celery_config,
    create_celery_app,
)
from tests.unit.test_config_redis_auth import _REQUIRED

# Built at runtime so no credential-like literal lives in the source.
_SECRET = "-".join(["broker", "test", "value"])


def _stub(
    *, redis_db: int = 0, broker_db: int = 1, material: str = _SECRET
) -> SimpleNamespace:
    return SimpleNamespace(
        REDIS_HOST="redis.internal",
        REDIS_PORT=6380,
        REDIS_DB=redis_db,
        REDIS_PASSWORD=SecretStr(material),
        CELERY_BROKER_REDIS_DB=broker_db,
    )


class TestBrokerUrl:
    def test_url_targets_broker_db_without_credentials(self) -> None:
        parts = urlsplit(build_broker_url(_stub(broker_db=3)))

        assert parts.scheme == "redis"
        assert parts.hostname == "redis.internal"
        assert parts.port == 6380
        assert parts.path == "/3"
        assert parts.username is None
        assert parts.password is None

    def test_broker_db_must_differ_from_app_redis_db(self) -> None:
        with pytest.raises(ValueError, match="CELERY_BROKER_REDIS_DB"):
            build_broker_url(_stub(redis_db=2, broker_db=2))


class TestCeleryConfig:
    def test_secret_is_passed_separately_from_the_url(self) -> None:
        config = build_celery_config(_stub())

        assert config["broker_password"] == _SECRET
        assert _SECRET not in config["broker_url"]

    def test_empty_secret_becomes_none(self) -> None:
        empty = ""
        assert build_celery_config(_stub(material=empty))["broker_password"] is None

    def test_json_only_serialization(self) -> None:
        config = build_celery_config(_stub())

        assert config["task_serializer"] == "json"
        assert config["result_serializer"] == "json"
        assert config["accept_content"] == ["json"]

    def test_at_least_once_delivery_without_result_backend(self) -> None:
        config = build_celery_config(_stub())

        assert config["task_acks_late"] is True
        assert config["task_reject_on_worker_lost"] is True
        assert config["worker_prefetch_multiplier"] == 1
        assert config["task_ignore_result"] is True
        assert config["result_backend"] is None

    def test_time_limits_cover_nmap_and_stay_below_visibility_timeout(self) -> None:
        config = build_celery_config(_stub())
        soft = config["task_soft_time_limit"]
        hard = config["task_time_limit"]
        visibility = config["broker_transport_options"]["visibility_timeout"]

        assert NMAP_TIMEOUT_SECONDS < soft < hard < visibility


def test_reaper_schedule_and_threshold():
    from app.worker.celery_app import STALE_SCAN_SECONDS

    config = build_celery_config(_stub())
    assert config["beat_schedule"]["scans.reap"] == {
        "task": "scans.reap",
        "schedule": 300,
    }
    assert STALE_SCAN_SECONDS > config["task_time_limit"]


@pytest.mark.parametrize(
    ("task_name", "queue"),
    [
        ("scans.pump", "maintenance"),
        ("scans.reap", "maintenance"),
        ("scans.wake", "scans"),
    ],
)
def test_task_routing(task_name, queue):
    app = create_celery_app(_stub())
    assert app.conf.task_default_queue == "scans"
    assert app.amqp.router.route({}, task_name)["queue"].name == queue


def test_broker_socket_timeouts():
    options = build_celery_config(_stub())["broker_transport_options"]
    assert options["socket_timeout"] == 5
    assert options["socket_connect_timeout"] == 5


def test_pump_schedule():
    assert build_celery_config(_stub())["beat_schedule"]["scans.pump"] == {
        "task": "scans.pump",
        "schedule": 60,
    }


class TestCreateCeleryApp:
    def test_configuration_is_lazy(self) -> None:
        app = create_celery_app(_stub(redis_db=1, broker_db=1))

        with pytest.raises(ValueError, match="CELERY_BROKER_REDIS_DB"):
            app.conf.broker_url  # noqa: B018 - first access triggers configuration

    def test_connection_carries_secret_outside_the_uri(self) -> None:
        app = create_celery_app(_stub())
        connection = app.connection_for_write()
        try:
            assert _SECRET == connection.password
            assert _SECRET not in connection.as_uri()
            assert connection.virtual_host in ("1", "/1")
        finally:
            connection.release()

    def test_app_config_reflects_settings(self) -> None:
        app = create_celery_app(_stub())

        assert app.conf.task_acks_late is True
        assert app.conf.worker_prefetch_multiplier == 1
        assert app.conf.accept_content == ["json"]


class TestSettingsFields:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core.config import Settings

        # tests/conftest.py pins the broker DB in the environment for the suite.
        monkeypatch.delenv("CELERY_BROKER_REDIS_DB", raising=False)
        settings = Settings(_env_file=None, **_REQUIRED)

        assert settings.SCAN_EXECUTION_ENABLED is False
        assert settings.CELERY_BROKER_REDIS_DB == 1

    @pytest.mark.parametrize("value", [-1, 16])
    def test_broker_db_out_of_range_is_rejected(self, value: int) -> None:
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="CELERY_BROKER_REDIS_DB"):
            Settings(_env_file=None, CELERY_BROKER_REDIS_DB=value, **_REQUIRED)
