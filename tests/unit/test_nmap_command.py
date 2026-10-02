"""Fixed Nmap profile and argument-injection defenses."""

import pytest

from app.modules.scans.nmap.command import (
    NMAP_PROFILE,
    REQUIRED_SCAN_TYPES,
    build_nmap_command,
)
from app.modules.scans.targets import ScanTarget

EXPECTED_PROFILE = (
    "-sS",
    "-sU",
    "--top-ports",
    "1000",
    "-sV",
    "-O",
    "--script=vuln",
    "-oX",
    "-",
)


@pytest.mark.parametrize(
    "addresses",
    [
        ("8.8.8.8",),
        ("2606:4700:4700::1111",),
        ("8.8.8.0/24",),
        ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"),
    ],
)
def test_exact_argv_and_target_separator(addresses: tuple[str, ...]) -> None:
    target = ScanTarget("ip", addresses[0], addresses)
    argv = build_nmap_command(target)
    assert argv == ["nmap", *EXPECTED_PROFILE, "--", *addresses]
    assert argv.count("--") == 1
    separator = argv.index("--")
    assert argv[separator + 1 :] == list(addresses)
    assert all(argv.index(address) > separator for address in addresses)
    assert not any("exploit" in argument for argument in argv)
    assert [argument for argument in argv if argument.startswith("--script")] == [
        "--script=vuln"
    ]


def test_profile_is_immutable_and_unchanged_after_call() -> None:
    assert isinstance(NMAP_PROFILE, tuple)
    assert NMAP_PROFILE == EXPECTED_PROFILE
    argv = build_nmap_command(ScanTarget("ip", "8.8.8.8", ("8.8.8.8",)))
    argv[1] = "--script=exploit"
    assert NMAP_PROFILE == EXPECTED_PROFILE
    assert REQUIRED_SCAN_TYPES == frozenset({"syn", "udp"})
    assert isinstance(REQUIRED_SCAN_TYPES, frozenset)


def test_custom_binary_path() -> None:
    target = ScanTarget("ip", "8.8.8.8", ("8.8.8.8",))
    assert build_nmap_command(target, nmap_path="/usr/local/bin/nmap") == [
        "/usr/local/bin/nmap",
        *EXPECTED_PROFILE,
        "--",
        "8.8.8.8",
    ]


@pytest.mark.parametrize(
    "addresses",
    [
        (),
        ("-oX",),
        ("8.8.8.8 -p1",),
        ("example.com",),
        ("8.8.8.8\x00",),
        ("8.8.8.8\t",),
        ("8.8.8.8\n",),
        ("",),
        ("8.8.8.0/33",),
        ("8.8.8.8", "example.com"),
    ],
)
def test_invalid_addresses_rejected(addresses: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        build_nmap_command(ScanTarget("ip", "original", addresses))


@pytest.mark.parametrize("nmap_path", ["", "nmap\x00"])
def test_invalid_binary_path_rejected(nmap_path: str) -> None:
    with pytest.raises(ValueError):
        build_nmap_command(
            ScanTarget("ip", "8.8.8.8", ("8.8.8.8",)), nmap_path=nmap_path
        )
