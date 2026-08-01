"""End-to-end tests for the globally installed manifest ACK stub."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_SKILL_HOME = "~/.config/opencode/skills/parallel-agents-coordination"
SKILL_HOME = Path(
    os.environ.get("PARALLEL_SKILL_HOME", DEFAULT_SKILL_HOME)
).expanduser()
ACK_SCRIPT = SKILL_HOME / "scripts" / "ack-manifest.py"


def build_manifest(**overrides: object) -> dict[str, object]:
    """Build a valid manifest and recompute its hash after overrides."""
    manifest: dict[str, object] = {
        "manifest_version": 1,
        "agent_id": "11111111-1111-4111-8111-111111111111",
        "launch_id": "22222222-2222-4222-8222-222222222222",
        "repository_root": "/repo",
        "worktree_root": "/repo/worktree",
        "branch": "parallel/agent-a",
        "base_sha": "a" * 40,
        "owner": "agent-a",
        "allowed_writes": ["src/**/*.py"],
        "forbidden_paths": ["secrets/**"],
        "shared_files": {},
        "action_gates": {
            "commit": False,
            "push": False,
            "merge": False,
            "rebase": False,
            "human_delivery_required": True,
        },
        "human_gate_id": None,
    }
    manifest.update(overrides)
    unsigned = dict(manifest)
    digest = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
    manifest["manifest_hash"] = digest
    return manifest


def refresh_hash(manifest: dict[str, object]) -> dict[str, object]:
    """Recompute a manifest hash after removing or changing a field."""
    manifest.pop("manifest_hash", None)
    manifest["manifest_hash"] = hashlib.sha256(
        canonical_json(manifest).encode("utf-8")
    ).hexdigest()
    return manifest


def canonical_json(value: dict[str, object]) -> str:
    """Serialize a manifest using the contract's compact sorted-key form."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(content, encoding="utf-8")
    return path


def run_ack(
    path: Path, *, use_environment: bool = False
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(ACK_SCRIPT)]
    environment = os.environ.copy()
    environment.pop("PARALLEL_MANIFEST_PATH", None)
    if use_environment:
        environment["PARALLEL_MANIFEST_PATH"] = str(path)
    else:
        args.extend(["--manifest", str(path)])
    return subprocess.run(
        args,
        capture_output=True,
        cwd=path.parent,
        env=environment,
        text=True,
        check=False,
    )


def test_parse_valid(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, canonical_json(build_manifest()))

    result = run_ack(path)

    assert result.returncode == 0
    assert re.fullmatch(
        r"ACK 11111111-1111-4111-8111-111111111111 "
        r"22222222-2222-4222-8222-222222222222 [0-9a-f]{64} "
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\n",
        result.stdout,
    )


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    manifest = build_manifest()
    del manifest["allowed_writes"]
    path = write_manifest(tmp_path, canonical_json(refresh_hash(manifest)))

    result = run_ack(path)

    assert result.returncode != 0
    assert "allowed_writes" in result.stderr


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    result = run_ack(write_manifest(tmp_path, "{not-json"))

    assert result.returncode != 0
    assert "malformed JSON" in result.stderr


def test_bad_uuid_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        canonical_json(build_manifest(agent_id="not-a-uuid")),
    )

    result = run_ack(path)

    assert result.returncode != 0
    assert "agent_id" in result.stderr


def test_bad_hex_sha_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, canonical_json(build_manifest(base_sha="z" * 40)))

    result = run_ack(path)

    assert result.returncode != 0
    assert "base_sha" in result.stderr


def test_tampered_manifest_hash_is_rejected(tmp_path: Path) -> None:
    manifest = build_manifest()
    manifest["manifest_hash"] = "0" * 64
    path = write_manifest(tmp_path, canonical_json(manifest))

    result = run_ack(path)

    assert result.returncode != 0
    assert "manifest_hash" in result.stderr


def test_noncanonical_key_order_is_rejected(tmp_path: Path) -> None:
    manifest = build_manifest()
    path = write_manifest(tmp_path, json.dumps(manifest, separators=(",", ":")))

    result = run_ack(path)

    assert result.returncode != 0
    assert "canonical" in result.stderr


def test_manifest_path_environment_fallback_is_supported(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, canonical_json(build_manifest()))

    result = run_ack(path, use_environment=True)

    assert result.returncode == 0
    assert result.stdout.startswith("ACK 11111111-1111-4111-8111-111111111111 ")
