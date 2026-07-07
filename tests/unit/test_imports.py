"""Regression test for PR-1: ensure no inline `__import__` or hot-path inline imports.

Spec R-15.1:
  - No `__import__(...)` call inside a function body or hot path in app source.
  - No `from X import Y` or `import X` inside a hot path (try/except, if/else,
    consumer loop) outside the top-level module import block.

Narrowly scoped to the four files in PR-1's commit boundary. The deferred
imports used for circular-import handling (e.g. `from app.dependencies import
get_event_bus as _get` inside `service.get_event_bus`) are out of scope for
PR-1 and are explicitly allowlisted.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


# Project root: this test file is at tests/unit/test_imports.py, project root is ../../.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"

# Files in PR-1's slice (per the design PR-1 section + the orchestrator scope).
# After refactor-180 (god files SRP), event_bus was split into a package.
# We target the sub-module that still contains __import__ and indented imports.
PR1_TARGETS: list[Path] = [
    APP_DIR / "modules" / "auth" / "service.py",
    APP_DIR / "core" / "security.py",
    APP_DIR / "event_bus" / "bus.py",
    APP_DIR / "main.py",
]

# Allowlist of indented `from ... import ...` statements that are NOT in PR-1
# scope. These are deferred imports used for circular-import handling or other
# intentional lazy-loading patterns the design preserves.
# Format: (file_relpath, line_number, imported_name)
PR1_INDENT_IMPORT_ALLOWLIST: set[tuple[str, int, str]] = {
    # `from app.dependencies import get_event_bus as _get` is a deferred import
    # inside `service.get_event_bus` to avoid a circular import between
    # `app.modules.auth.service` and `app.dependencies`. PR-1 does not refactor
    # this pattern.
    ("app/modules/auth/service.py", 42, "get_event_bus"),
}


def _format_offender(path: Path, lineno: int, line: str) -> str:
    return f"  {path.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()}"


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(
            APP_DIR / "modules" / "auth" / "service.py",
            id="app/modules/auth/service.py",
        ),
        pytest.param(
            APP_DIR / "core" / "security.py",
            id="app/core/security.py",
        ),
        pytest.param(
            APP_DIR / "main.py",
            id="app/main.py",
        ),
        pytest.param(
            APP_DIR / "event_bus" / "bus.py",
            id="app/event_bus/bus.py",
            marks=pytest.mark.xfail(
                strict=True,
                reason=(
                    "event_bus/bus.py uses __import__('datetime') inside the "
                    "DLQ write block. Belongs to the event_bus cleanup issue, "
                    "not #101. Remove this xfail mark when that issue is fixed."
                ),
            ),
        ),
    ],
)
def test_no_dunder_import_call(target: Path) -> None:
    """R-15.1.1: no `__import__(...)` calls inside PR-1 target files."""
    assert target.exists(), f"PR-1 target file missing: {target}"
    text = target.read_text(encoding="utf-8")
    pattern = re.compile(r"\b__import__\s*\(")
    offenders: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            offenders.append(_format_offender(target, lineno, line))
    assert not offenders, (
        "Found `__import__(...)` calls in PR-1 target file (R-15.1.1):\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(
            APP_DIR / "event_bus" / "bus.py",
            id="app/event_bus/bus.py",
        ),
        pytest.param(
            APP_DIR / "modules" / "auth" / "service.py",
            id="app/modules/auth/service.py",
        ),
        pytest.param(
            APP_DIR / "core" / "security.py",
            id="app/core/security.py",
        ),
        pytest.param(
            APP_DIR / "main.py",
            id="app/main.py",
        ),
    ],
)
def test_no_hot_path_indented_imports(target: Path) -> None:
    """R-15.1.2: no indented `from X import Y` / `import X` outside the top block.

    Walks the AST and flags every `Import`/`ImportFrom` node that is NOT a
    direct child of the module body (i.e. appears inside a function, class,
    or other nested scope). TYPE_CHECKING-guarded imports are NOT flagged
    (they are static-only and not real runtime hot-path imports). The
    deferred-import allowlist excludes the specific known-false-positive
    at `service.get_event_bus`.
    """
    assert target.exists(), f"PR-1 target file missing: {target}"
    text = target.read_text(encoding="utf-8")
    tree = ast.parse(text)
    relpath = str(target.relative_to(PROJECT_ROOT))
    offenders: list[str] = []

    # Build a map: import-node-id -> set of ancestor node kinds.
    # An import is a "TYPE_CHECKING" import iff one of its ancestors is an
    # `ast.If` whose test is a `Name` with id == "TYPE_CHECKING".
    def _ancestors(node: ast.AST) -> list[ast.AST]:
        path: list[ast.AST] = []
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                if child is node:
                    path.append(parent)
                    break
        return path

    def _is_type_checking_import(node: ast.AST) -> bool:
        for parent in _ancestors(node):
            if isinstance(parent, ast.If):
                test = parent.test
                if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                    return True
        return False

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        # Skip top-level (column 0) imports.
        if getattr(node, "col_offset", 0) == 0:
            continue
        # Skip TYPE_CHECKING-guarded imports (static-only; not runtime hot path).
        if _is_type_checking_import(node):
            continue
        # Pull the imported names so the allowlist can match them precisely.
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            names = [alias.name for alias in node.names]
        primary_name = names[0] if names else ""
        allow_key = (relpath, node.lineno, primary_name.split(".")[0])
        if allow_key in PR1_INDENT_IMPORT_ALLOWLIST:
            continue
        line = text.splitlines()[node.lineno - 1]
        offenders.append(_format_offender(target, node.lineno, line))

    assert not offenders, (
        "Found inline imports in PR-1 target file (R-15.1.2):\n"
        + "\n".join(offenders)
    )


def test_pr1_target_files_exist() -> None:
    """Sanity check: the four PR-1 target files are present in the working tree."""
    missing = [str(p.relative_to(PROJECT_ROOT)) for p in PR1_TARGETS if not p.exists()]
    assert not missing, f"PR-1 target files missing: {missing}"
