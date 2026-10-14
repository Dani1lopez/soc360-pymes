"""Local demo target policy and fast scan profile, without network access."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.modules.scans.nmap.command import NMAP_PROFILE, build_nmap_command
from app.modules.scans.targets import ScanTarget, TargetRejectedError, resolve_scan_target


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SCAN_DEMO_MODE", True)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["10.0.0.5", "172.18.0.7", "192.168.1.10"])
async def test_private_ip_and_hostname(address: str) -> None:
    async def resolver(host: str) -> list[str]:
        assert host == "demo-target"
        return [address]

    assert (await resolve_scan_target("ip", address)).addresses == (address,)
    target = await resolve_scan_target("hostname", "demo-target", resolver=resolver)
    assert target.addresses == (address,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "::1", "169.254.169.254", "224.0.0.1", "0.0.0.0",
        "fe80::1", "240.0.0.1", "::", "ff02::1", "100.64.0.1",
    ],
)
async def test_unsafe_addresses_remain_rejected(address: str) -> None:
    with pytest.raises(TargetRejectedError, match="^target_not_global$"):
        await resolve_scan_target("ip", address)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_private_subnet_policy(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    monkeypatch.setattr(settings, "SCAN_DEMO_MODE", enabled)
    if enabled:
        target = await resolve_scan_target("subnet", "172.18.0.0/24")
        assert target.addresses == ("172.18.0.0/24",)
    else:
        with pytest.raises(TargetRejectedError, match="^target_not_global$"):
            await resolve_scan_target("subnet", "172.18.0.0/24")


@pytest.mark.asyncio
async def test_disabled_mode_preserves_policy_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCAN_DEMO_MODE", False)
    with pytest.raises(TargetRejectedError, match="^target_not_global$"):
        await resolve_scan_target("ip", "10.0.0.5")
    target = ScanTarget("ip", "8.8.8.8", ("8.8.8.8",))
    assert build_nmap_command(target) == ["nmap", *NMAP_PROFILE, "--", "8.8.8.8"]


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    ["127.0.0.0/24", "169.254.169.0/24", "224.0.0.0/24", "240.0.0.0/24", "::/120"],
)
async def test_unsafe_subnets_remain_rejected(value: str) -> None:
    with pytest.raises(TargetRejectedError, match="^target_not_global$"):
        await resolve_scan_target("subnet", value)


@pytest.mark.asyncio
async def test_mixed_dns_answers_reject_unsafe_address() -> None:
    async def resolver(host: str) -> list[str]:
        return ["172.18.0.7", "169.254.169.254"]

    with pytest.raises(TargetRejectedError, match="^target_not_global$"):
        await resolve_scan_target("hostname", "demo-target", resolver=resolver)


@pytest.mark.asyncio
async def test_private_url_literal_is_accepted_without_dns() -> None:
    async def resolver(host: str) -> list[str]:
        pytest.fail("IP literals must not use DNS")

    target = await resolve_scan_target(
        "web_app", "http://172.18.0.7/path", resolver=resolver
    )
    assert target.addresses == ("172.18.0.7",)
