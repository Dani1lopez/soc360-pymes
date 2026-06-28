import subprocess
import tomllib
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _package_names(specs: list[str]) -> list[str]:
    names = []
    for spec in specs:
        spec = spec.strip()
        if not spec or spec.startswith("#"):
            continue
        name = spec.split("[")[0].split("==")[0].strip()
        names.append(name)
    return names


def test_pyproject_toml_has_required_project_metadata():
    pyproject_path = ROOT / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml must exist"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    project = data["project"]
    assert project["name"] == "soc360-pymes"
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.12"
    assert project["dependencies"]
    assert project["optional-dependencies"]["dev"]


def test_runtime_dependencies_preserve_extras():
    with (ROOT / "pyproject.toml").open("rb") as f:
        deps = tomllib.load(f)["project"]["dependencies"]

    expected_extras = [
        "uvicorn[standard]==0.32.1",
        "sqlalchemy[asyncio]==2.0.36",
        "redis[hiredis]==5.2.1",
        "celery[redis]==5.4.0",
        "python-jose[cryptography]==3.3.0",
        "passlib[bcrypt]==1.7.4",
    ]
    for expected in expected_extras:
        assert expected in deps, f"{expected} must be preserved in runtime deps"


def test_dev_dependencies_are_deduplicated():
    with (ROOT / "pyproject.toml").open("rb") as f:
        dev = tomllib.load(f)["project"]["optional-dependencies"]["dev"]

    names = _package_names(dev)
    assert len(names) == len(set(names)), "dev dependencies must not contain duplicates"
    assert "pytest" in names
    assert "pytest-asyncio" in names
    assert "ruff" in names
    assert "mypy" in names
    assert "fakeredis" in names
    assert "anyio" in names


def test_python_version_is_exactly_312():
    content = (ROOT / ".python-version").read_text().strip()
    assert content == "3.12", ".python-version must be exactly 3.12"


def test_uv_lock_exists_and_is_tracked():
    lock_path = ROOT / "uv.lock"
    assert lock_path.exists(), "uv.lock must be generated and committed"
    if os.getenv("GITHUB_ACTIONS"):
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(lock_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "uv.lock must be tracked by git in CI"
        return

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(lock_path)],
        cwd=ROOT,
    )
    assert ignored.returncode != 0, "uv.lock must not be ignored locally"


def test_requirements_txt_has_legacy_header_and_unchanged_pins():
    lines = (ROOT / "requirements.txt").read_text().splitlines()
    header = "\n".join(lines[:5]).lower()
    assert "legacy" in header or "pyproject.toml" in header

    original_pins = [
        "fastapi==0.115.6",
        "uvicorn[standard]==0.32.1",
        "sqlalchemy[asyncio]==2.0.36",
        "asyncpg==0.30.0",
        "alembic==1.14.0",
        "redis[hiredis]==5.2.1",
        "celery[redis]==5.4.0",
        "python-jose[cryptography]==3.3.0",
        "passlib[bcrypt]==1.7.4",
        "python-multipart==0.0.12",
        "pydantic==2.10.4",
        "pydantic-settings==2.7.0",
        "httpx==0.27.2",
        "structlog==24.4.0",
        "email-validator==2.3.0",
    ]
    for pin in original_pins:
        assert pin in lines, f"{pin} must remain in requirements.txt"

    # Order of runtime pins must be preserved (ignore comments/blank lines).
    runtime_order = [line for line in lines if line and not line.startswith("#")]
    assert runtime_order == original_pins, "runtime dependency order must not change"


def test_requirements_dev_has_legacy_header():
    lines = (ROOT / "requirements-dev.txt").read_text().splitlines()
    header = "\n".join(lines[:5]).lower()
    assert "legacy" in header or "pyproject.toml" in header

    dev_pins = [
        "pytest==8.3.4",
        "pytest-asyncio==0.24.0",
        "ruff==0.8.4",
        "mypy==1.13.0",
        "anyio==4.12.1",
        "fakeredis==2.34.1",
    ]
    for pin in dev_pins:
        assert pin in lines, f"{pin} must remain in requirements-dev.txt"


def test_ci_workflow_has_uv_job_only():
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text()
    job_ids = []
    in_jobs = False
    for line in ci_text.splitlines():
        if line == "jobs:":
            in_jobs = True
            continue
        if in_jobs and line and not line.startswith(" "):
            break
        if in_jobs and line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
            job_ids.append(line.split(":", 1)[0].strip())

    assert job_ids == ["test"], f"CI must contain only the canonical uv test job, found: {job_ids}"
    assert "pip install -r requirements-dev.txt" not in ci_text, "Legacy pip install step must be removed"
    assert "astral-sh/setup-uv@v4" in ci_text
    assert "uv lock --check" in ci_text, "CI must verify uv.lock is fresh"
    assert "uv sync --frozen --extra dev" in ci_text
    assert "uv run pytest" in ci_text


def test_ci_uv_job_has_import_smoke_step():
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "Smoke test uv import surface" in ci_text
    assert "import uvicorn, sqlalchemy.ext.asyncio, redis.asyncio, celery" in ci_text
    assert "jose, passlib, asyncpg, cryptography, bcrypt, hiredis" in ci_text


def test_ci_uv_job_has_celery_help_step():
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "Smoke test Celery CLI help" in ci_text
    assert "uv run celery --help" in ci_text


def test_uv_run_celery_help_runs():
    if shutil.which("uv") is None:
        pytest.skip("uv CLI is unavailable; this runtime smoke is covered by the test-uv CI job")

    result = subprocess.run(
        ["uv", "run", "celery", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"uv run celery --help failed: {result.stderr}"
    assert "Celery command entrypoint" in result.stdout, "Celery CLI usage must be printed"


def test_readme_has_uv_quickstart_block():
    readme = (ROOT / "README.md").read_text()
    assert "uv sync --extra dev" in readme
    assert "uv run pytest" in readme


def test_readme_es_has_uv_quickstart_block():
    readme_es = (ROOT / "README.es.md").read_text()
    assert "uv sync --extra dev" in readme_es
    assert "uv run pytest" in readme_es


def test_no_dockerfile_and_compose_has_only_infrastructure_services():
    assert not (ROOT / "Dockerfile").exists(), "No Dockerfile should exist in PR-1"
    compose_path = ROOT / "docker-compose.yml"
    assert compose_path.exists()
    compose_text = compose_path.read_text()
    # PR-1 must not introduce any application image or build context.
    assert "build:" not in compose_text, "docker-compose.yml must not contain a build context"
    assert "Dockerfile" not in compose_text, "docker-compose.yml must not reference a Dockerfile"
    services = [
        line.split(":")[0].strip()
        for line in compose_text.splitlines()
        if line.rstrip().endswith(":") and line.startswith("  ") and not line.startswith("    ")
    ]
    assert sorted(services) == ["postgres", "redis"], (
        f"docker-compose.yml should only define postgres and redis services, found: {services}"
    )
