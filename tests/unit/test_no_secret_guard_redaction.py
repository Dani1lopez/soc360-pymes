"""Guards for the infrastructure files that never carry a credential.

The repository's secret guard rewrites a file while it is being written,
replacing credential-shaped text with a marker. The result is silent in review:
the file still looks like configuration, but it no longer parses, and a commit
carrying it was already merged into the branch once. It happened three times
while this stack was written, twice committed without validation.

These checks are cheap, need no Docker, and fail immediately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# The marker the guard leaves behind.
REDACTION_MARKER = "redacted" + "-by-secret-guard"

# Every Compose file is included automatically, so a new one cannot be added
# without inheriting the check.
INFRASTRUCTURE_FILES = (
    ".dockerignore",
    "Dockerfile",
    "frontend/.dockerignore",
    "frontend/Dockerfile",
    "frontend/nginx.conf",
    "gunicorn_conf.py",
) + tuple(sorted(path.name for path in ROOT.glob("docker-compose*.yml")))


@pytest.mark.parametrize("relative", INFRASTRUCTURE_FILES)
def test_infrastructure_file_has_no_redaction_marker(relative: str) -> None:
    path = ROOT / relative
    assert path.exists(), f"{relative} is missing"

    assert REDACTION_MARKER not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", INFRASTRUCTURE_FILES)
def test_infrastructure_file_has_bounded_size(relative: str) -> None:
    """A truncated write is the other shape this corruption takes."""
    content = (ROOT / relative).read_text(encoding="utf-8")

    assert content.strip(), f"{relative} is empty"
    assert content.count("\n") > 3, f"{relative} looks truncated"
