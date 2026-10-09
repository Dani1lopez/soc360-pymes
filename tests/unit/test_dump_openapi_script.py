"""OpenAPI snapshot guard (FT0-T1).

The frontend generates its TypeScript types from a snapshot of the FastAPI
schema (``frontend/openapi.json``) produced by ``scripts/dump_openapi.py``.
The snapshot is only useful while it matches the application, so this test
pins both directions: the renderer is deterministic, and the committed
snapshot is exactly what the current app renders.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "dump_openapi.py"
SNAPSHOT_PATH = REPO_ROOT / "frontend" / "openapi.json"

# The alpha API exposes 24 paths; a factory regression that drops routers
# would silently shrink the snapshot the frontend types are generated from.
MINIMUM_PATHS = 20


def _load_script():
    """Import ``scripts/dump_openapi.py``, which is not an importable package."""
    spec = importlib.util.spec_from_file_location("dump_openapi", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    if not SCRIPT_PATH.exists():
        pytest.fail(f"{SCRIPT_PATH.relative_to(REPO_ROOT)} does not exist yet")
    return _load_script()


def test_render_is_deterministic_valid_json(script) -> None:
    first = json.loads(script.render_openapi())
    second = json.loads(script.render_openapi())

    assert first == second
    assert first["info"]["title"]


def test_render_keeps_the_alpha_api_surface(script) -> None:
    schema = json.loads(script.render_openapi())
    paths = schema["paths"]

    assert len(paths) >= MINIMUM_PATHS
    assert "/api/v1/assets/" in paths


def test_committed_snapshot_matches_the_app(script) -> None:
    assert SNAPSHOT_PATH.exists(), (
        f"{SNAPSHOT_PATH.relative_to(REPO_ROOT)} is missing; "
        "run `python scripts/dump_openapi.py`"
    )

    assert SNAPSHOT_PATH.read_text(encoding="utf-8") == script.render_openapi(), (
        "frontend/openapi.json is stale; run `python scripts/dump_openapi.py`"
    )
