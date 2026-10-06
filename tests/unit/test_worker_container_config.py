"""Least-privilege container configuration regression checks."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_worker_and_beat_security():
    compose = yaml.safe_load((ROOT / "docker-compose.worker.yml").read_text())
    services = compose["services"]
    for service in services.values():
        assert service["env_file"] == [
            {"path": ".env"},
            {"path": ".env.worker", "required": True},
        ]
        assert "DATABASE_URL" not in service.get("environment", {})
    worker = services["worker"]
    assert worker["cap_drop"] == ["ALL"]
    assert worker["cap_add"] == ["NET_RAW"]
    assert worker["read_only"] is True
    assert worker["init"] is True
    assert "privileged" not in worker
    assert not any("no-new-privileges" in opt for opt in worker.get("security_opt", []))
    assert "pids_limit" in worker and "mem_limit" in worker
    assert worker["build"]["target"] == "worker"
    assert worker["profiles"] == ["worker"]

    beat = services["beat"]
    assert beat["cap_drop"] == ["ALL"]
    assert "cap_add" not in beat
    assert "no-new-privileges:true" in beat["security_opt"]
    assert beat["read_only"] is True
    assert beat["user"].split(":")[0] not in {"0", "root"}
    assert beat["build"]["target"] == "runtime"
    base_services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())[
        "services"
    ]
    assert all(
        service.get("privileged") is not True
        for service in [*services.values(), *base_services.values()]
    )


def test_worker_stage_and_default_api_target():
    dockerfile = (ROOT / "Dockerfile").read_text()
    stages = list(re.finditer(r"^FROM .+ AS (\w+)\s*$", dockerfile, re.MULTILINE))
    assert stages[-1].group(1) == "runtime"
    worker_index = next(
        i for i, stage in enumerate(stages) if stage.group(1) == "worker"
    )
    worker = dockerfile[stages[worker_index].end() : stages[worker_index + 1].start()]
    assert "setcap cap_net_raw+eip" in worker
    user = re.search(r"^USER (\S+)", worker, re.MULTILINE)
    assert user and user.group(1) not in {"root", "0", "0:0"}
    assert "-perm /6000" in worker
    assert "entrypoint.sh" not in worker
    assert "NET_ADMIN" not in worker
