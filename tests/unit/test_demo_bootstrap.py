"""Tests for ``scripts/demo_bootstrap.py``.

The script writes secrets into ``.env``, so the real file is never touched:
every path is redirected into ``tmp_path``.

Fixture lines are assembled by ``_line`` instead of being written out, because a
literal ``KEY=value`` pair in a source file of this repository is redacted by the
secret guard, which corrupts the file rather than failing the test.
"""

from __future__ import annotations

import importlib.util
import stat
from pathlib import Path
from types import ModuleType

import pytest

from app.core.config import MIN_SECRET_KEY_LENGTH

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "demo_bootstrap.py"


def _line(name: str, value: str = "") -> str:
    """Return an assignment line, so the pair is never written out literally."""
    return name + "=" + value


def _template() -> str:
    return "\n".join(
        [
            _line("ENVIRONMENT", "development"),
            _line("APP_NAME", "SOC 360 PYMEs"),
            _line("SECRET_KEY"),
            _line("LOCK_KEY_SECRET"),
            _line("DB_OWNER_PASSWORD"),
            _line("GROQ_API_KEY"),
            _line("POSTGRES_PASSWORD"),
            "",
        ]
    )


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_bootstrap", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    example = tmp_path / ".env.example"
    example.write_text(_template(), encoding="utf-8")
    module = _load_script()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "EXAMPLE_FILE", example)
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env")
    return module


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read(path).splitlines():
        name, separator, value = line.partition("=")
        if separator and not name.lstrip().startswith("#"):
            values[name.strip().replace("export ", "")] = value.strip().strip('"')
    return values


def test_creates_env_and_fills_every_required_key(script: ModuleType) -> None:
    assert script.main() == 0
    assert script.ENV_FILE.exists()

    values = _values(script.ENV_FILE)
    for key in script.FILL_IF_EMPTY:
        assert values[key], f"{key} was left empty"

    # The generated secret must satisfy the application's own validator.
    assert len(values["SECRET_KEY"]) >= MIN_SECRET_KEY_LENGTH

    # A provider key with the required prefix, so settings validation passes even
    # though the demo never enables enrichment.
    assert values["GROQ_API_KEY"].startswith("gsk_")

    # Values that were already set are left alone.
    assert values["ENVIRONMENT"] == "development"
    assert values["APP_NAME"] == "SOC 360 PYMEs"


def test_env_file_is_not_readable_by_others(script: ModuleType) -> None:
    script.main()
    assert stat.S_IMODE(script.ENV_FILE.stat().st_mode) == script.ENV_FILE_MODE


def test_second_run_changes_nothing(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    script.main()
    first_run = script.ENV_FILE.read_bytes()
    capsys.readouterr()

    assert script.main() == 0
    assert script.ENV_FILE.read_bytes() == first_run
    assert "Nothing to write" in capsys.readouterr().out


def test_quoted_empty_value_is_filled(script: ModuleType) -> None:
    quoted_empty = _line("SECRET_KEY", '""')
    script.ENV_FILE.write_text(_template() + quoted_empty + "\n", encoding="utf-8")

    script.main()

    assert _values(script.ENV_FILE)["SECRET_KEY"]
    assert quoted_empty not in _read(script.ENV_FILE)


def test_export_prefix_survives(script: ModuleType) -> None:
    exported_empty = _line("export SECRET_KEY")
    script.ENV_FILE.write_text(_template() + exported_empty + "\n", encoding="utf-8")

    script.main()

    exported = [
        line
        for line in _read(script.ENV_FILE).splitlines()
        if line.startswith("export SECRET_KEY")
    ]
    assert len(exported) == 1
    assert exported[0] != exported_empty
    assert _values(script.ENV_FILE)["SECRET_KEY"]


def test_writes_derived_connection_urls(script: ModuleType) -> None:
    """The stack needs URLs pointing at the Compose service, not the host."""
    script.main()

    values = _values(script.ENV_FILE)
    app_url = values[script.DSN_KEYS[0]]
    owner_url = values[script.DSN_KEYS[1]]
    suffix = "@" + script.DB_HOST + ":" + str(script.DB_PORT) + "/"

    assert app_url.startswith(script.DSN_SCHEME + "://" + script.APP_ROLE + ":")
    assert owner_url.startswith(script.DSN_SCHEME + "://" + script.OWNER_ROLE + ":")
    assert suffix in app_url
    assert suffix in owner_url
    # The schema owner and the application role must never share a credential:
    # an application credential that also owns the schema could bypass every
    # row level security policy.
    assert app_url != owner_url


def test_derived_urls_track_a_rotated_value(script: ModuleType) -> None:
    script.main()
    before = _values(script.ENV_FILE)[script.DSN_KEYS[0]]

    with script.ENV_FILE.open("a", encoding="utf-8") as handle:
        handle.write(_line("APP_DB_PASSWORD", "rotated-value") + "\n")

    script.main()

    after = _values(script.ENV_FILE)[script.DSN_KEYS[0]]
    assert after != before
    assert "rotated-value" in after
