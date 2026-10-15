"""Local demo scan profile: the fast Nmap profile, and nothing else.

H2 decision D2=A moved the network policy out of this switch. The tests that used
to assert a demo-only target policy now assert the opposite property: turning
``SCAN_DEMO_MODE`` on must not widen what a scan can reach. The policy itself is
covered in ``test_target_policy.py``.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.modules.scans.nmap.command import NMAP_PROFILE, build_nmap_command
from app.modules.scans.targets import (
    ScanTarget,
    TargetRejectedError,
    resolve_scan_target,
)


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SCAN_DEMO_MODE", True)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_demo_mode_does_not_change_the_target_policy(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    monkeypatch.setattr(settings, "SCAN_DEMO_MODE", enabled)
    assert (await resolve_scan_target("ip", "172.18.0.7")).addresses == ("172.18.0.7",)
    with pytest.raises(TargetRejectedError, match="^target_not_allowed$"):
        await resolve_scan_target("ip", "8.8.8.8")


@pytest.mark.asyncio
async def test_demo_mode_does_not_widen_subnets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCAN_DEMO_MODE", False)
    assert (await resolve_scan_target("subnet", "172.18.0.0/24")).addresses == (
        "172.18.0.0/24",
    )


def test_demo_profile() -> None:
    target = ScanTarget("ip", "172.18.0.7", ("172.18.0.7",))
    assert build_nmap_command(target) == [
        "nmap",
        "--privileged",
        "--host-timeout",
        "5m",
        "--script-timeout",
        "60s",
        "-sS",
        "-sU",
        "-p",
        "T:21,22,80,3306,U:53,161",
        "-sV",
        "-O",
        "--script=vuln",
        "-oX",
        "-",
        "--",
        "172.18.0.7",
    ]


async def test_disabled_mode_uses_the_standard_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCAN_DEMO_MODE", False)
    target = ScanTarget("ip", "10.0.0.7", ("10.0.0.7",))
    assert build_nmap_command(target) == ["nmap", *NMAP_PROFILE, "--", "10.0.0.7"]


@pytest.mark.parametrize("environment", ["production", "staging", "development"])
def test_demo_mode_environment_validation(environment: str) -> None:
    values = settings.model_dump()
    values.update(
        ENVIRONMENT=environment,
        SCAN_DEMO_MODE=True,
        REDIS_PASSWORD="test-password",
        METRICS_TOKEN="test-metrics-token",
        LOCK_KEY_SECRET=None,
    )
    if environment == "development":
        assert Settings(_env_file=None, **values).SCAN_DEMO_MODE is True
    else:
        with pytest.raises(ValidationError, match="SCAN_DEMO_MODE.*local.*development"):
            Settings(_env_file=None, **values)


def test_demo_mode_defaults_off() -> None:
    assert Settings.model_fields["SCAN_DEMO_MODE"].default is False
