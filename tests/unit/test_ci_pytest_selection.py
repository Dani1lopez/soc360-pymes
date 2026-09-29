"""CI pytest selection guard (XD-05).

The CI test job splits the direct suite into a parallel step (``-n 2``) and a
``serial_only`` step. The split is only exhaustive and non-overlapping while
the ``-m`` expressions in ``.github/workflows/ci.yml`` stay in sync, so this
test pins them. The workflow is read with a minimal text parser (PyYAML is
only a transitive dependency) that tolerates plain, folded (``>``) and
literal (``|``) ``run`` scalars.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

CI_FILE = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

_STEP_START = re.compile(r"^(\s*)- name:\s*(.+?)\s*$")
_RUN_KEY = re.compile(r"^(\s*)run:\s*(.*?)\s*$")

BASE_EXPRESSION = "not toxiproxy and not redis_pressure"
# The serial step must not swallow tests owned by the dedicated Toxiproxy /
# Redis-pressure gates, which run after their own readiness checks.
SERIAL_EXPRESSION = f"serial_only and {BASE_EXPRESSION}"


def _steps() -> list[tuple[str, str]]:
    """Return ``(step name, normalized run command)`` for every run step."""
    lines = CI_FILE.read_text(encoding="utf-8").splitlines()
    steps: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        start = _STEP_START.match(lines[i])
        if not start:
            i += 1
            continue
        step_indent = len(start.group(1))
        name = start.group(2).strip("\"'")
        i += 1
        body: list[str] = []
        while i < len(lines):
            stripped = lines[i].strip()
            indent = len(lines[i]) - len(lines[i].lstrip())
            if stripped and indent <= step_indent:
                break
            body.append(lines[i])
            i += 1
        run = _run_command(body)
        if run is not None:
            steps.append((name, run))
    return steps


def _run_command(body: list[str]) -> str | None:
    for idx, line in enumerate(body):
        match = _RUN_KEY.match(line)
        if not match:
            continue
        key_indent = len(match.group(1))
        value = match.group(2)
        if value and value[0] not in "|>":
            return " ".join(value.split())
        parts: list[str] = []
        for cont in body[idx + 1 :]:
            if cont.strip() and len(cont) - len(cont.lstrip()) <= key_indent:
                break
            parts.append(cont.strip())
        return " ".join(" ".join(parts).split())
    return None


def _pytest_steps() -> dict[str, list[str]]:
    """Map step name -> shlex tokens, for run commands invoking pytest."""
    found: dict[str, list[str]] = {}
    for name, run in _steps():
        if "uv run pytest" in run and "\n" not in run:
            tokens = shlex.split(run)
            found[name] = tokens[tokens.index("pytest") :]
    return found


def _marker_expressions(tokens: list[str]) -> list[str]:
    return [tokens[i + 1] for i, tok in enumerate(tokens) if tok == "-m"]


def _has_xdist_flag(tokens: list[str]) -> bool:
    return any(
        tok in ("-n", "--numprocesses", "--dist")
        or tok.startswith(("--numprocesses=", "--dist="))
        or re.fullmatch(r"-n\S+", tok) is not None
        for tok in tokens
    )


def _parallel_step() -> list[str]:
    matches = [
        t for t in _pytest_steps().values() if "-n" in t or "--numprocesses" in t
    ]
    assert len(matches) == 1, "expected exactly one parallel pytest step in ci.yml"
    return matches[0]


def _serial_only_step() -> list[str]:
    matches = [
        t
        for t in _pytest_steps().values()
        if _marker_expressions(t) == [SERIAL_EXPRESSION]
    ]
    assert len(matches) == 1, "expected exactly one serial_only pytest step in ci.yml"
    return matches[0]


def _step_condition(step_name: str) -> str | None:
    """Return the ``if:`` expression of the named step, if it has one."""
    lines = CI_FILE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        start = _STEP_START.match(line)
        if not start or start.group(2).strip("\"'") != step_name:
            continue
        step_indent = len(start.group(1))
        for body_line in lines[i + 1 :]:
            if body_line.strip() and len(body_line) - len(body_line.lstrip()) <= step_indent:
                break
            match = re.match(r"^\s*if:\s*(.+?)\s*$", body_line)
            if match:
                return match.group(1)
    return None


def test_parser_reads_folded_and_plain_run_scalars() -> None:
    steps = dict(_steps())
    assert "uv lock --check" in steps.values()
    assert any(run.startswith("uv run pytest") for run in steps.values())


def test_parallel_step_pins_two_workers_not_auto() -> None:
    tokens = _parallel_step()
    workers = tokens[tokens.index("-n") + 1] if "-n" in tokens else None
    assert workers == "2", f"parallel step must pin -n 2 (auto breaks at gw13+): {tokens}"


def test_parallel_expression_is_direct_tests_plus_not_serial_only() -> None:
    expressions = _marker_expressions(_parallel_step())
    assert expressions == [f"{BASE_EXPRESSION} and not serial_only"]


def test_serial_step_selects_serial_only_minus_dedicated_gates_without_xdist() -> None:
    tokens = _serial_only_step()
    assert _marker_expressions(tokens) == [SERIAL_EXPRESSION]
    assert not _has_xdist_flag(tokens)


def test_serial_step_still_runs_when_the_parallel_step_fails() -> None:
    """A failing parallel step must not hide serial_only failures in the same run."""
    (serial_name,) = [
        name for name, tokens in _pytest_steps().items() if tokens == _serial_only_step()
    ]
    condition = _step_condition(serial_name)
    assert condition is not None, f"{serial_name} has no `if:` condition"
    assert "!cancelled()" in condition or "always()" in condition, condition


@pytest.mark.parametrize("selector", ["toxiproxy", "redis_pressure"])
def test_toxiproxy_and_redis_pressure_steps_stay_serial(selector: str) -> None:
    gated = [
        (name, tokens)
        for name, tokens in _pytest_steps().items()
        if selector in " ".join(tokens) and BASE_EXPRESSION not in " ".join(tokens)
    ]
    assert gated, f"no CI step selects {selector}"
    for name, tokens in gated:
        assert not _has_xdist_flag(tokens), f"{name} must stay serial: {tokens}"


def test_every_pytest_step_that_parallelizes_is_the_direct_step() -> None:
    for name, tokens in _pytest_steps().items():
        if _has_xdist_flag(tokens):
            assert _marker_expressions(tokens) == [
                f"{BASE_EXPRESSION} and not serial_only"
            ], f"{name} runs under xdist with an unexpected selection"
