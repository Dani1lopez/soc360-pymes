"""Guards for the production server configuration.

Both defects these tests cover were invisible until the API image was actually
started: Gunicorn was missing from the dependencies, so ``entrypoint.sh`` died
with ``exec: gunicorn: not found`` and the container restart-looped, and
``gunicorn_conf.py`` declared no worker class, so Gunicorn would have used its
synchronous worker, which cannot serve an ASGI application.

Continuous integration never caught either, because it never starts the server.
These checks are static and cheap, so they run with the unit suite.
"""

from __future__ import annotations

import importlib
import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load_gunicorn_config() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gunicorn_conf", ROOT / "gunicorn_conf.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gunicorn_is_a_declared_dependency() -> None:
    """The entrypoint execs it, so the image needs it installed."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = " ".join(project["project"]["dependencies"])

    assert "gunicorn" in declared


def test_configured_worker_class_is_importable() -> None:
    """An unimportable worker class only fails once a request arrives."""
    worker_class = _load_gunicorn_config().worker_class

    assert isinstance(worker_class, str) and "." in worker_class

    module_name, _, attribute = worker_class.rpartition(".")
    module = importlib.import_module(module_name)

    assert getattr(module, attribute) is not None


def test_entrypoint_starts_the_configured_server() -> None:
    """Otherwise the configuration file would be dead code."""
    entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert "gunicorn" in entrypoint
    assert "gunicorn_conf.py" in entrypoint
