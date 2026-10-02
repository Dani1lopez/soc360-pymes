"""Safe, immutable Nmap XML reports without process execution."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.modules.scans.nmap.parser import (
    NmapParseError,
    NmapService,
    ScriptFinding,
    parse_nmap_xml,
    verify_scan_types,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nmap"


@pytest.mark.parametrize("as_bytes", [True, False])
def test_normal_report(as_bytes: bool) -> None:
    data = (FIXTURES / "normal.xml").read_bytes()
    report = parse_nmap_xml(data if as_bytes else data.decode())
    verify_scan_types(report)
    assert report.scan_types == frozenset({"syn", "udp"})
    assert len(report.hosts) == 1
    host = report.hosts[0]
    assert host.addresses == ("203.0.113.10",)
    assert host.hostnames == ("dns.example",)
    assert host.status == "up"
    assert host.os_matches == ("Linux 5.x",)
    tcp, udp = host.ports
    assert (tcp.protocol, tcp.port_id, tcp.state) == ("tcp", 80, "open")
    assert tcp.service == NmapService("http", "Example", "1.0", "test")
    assert tcp.scripts == (ScriptFinding("http-vuln", "unsafe <script> & data"),)
    assert (udp.protocol, udp.port_id, udp.state) == ("udp", 53, "open")
    assert udp.service == NmapService("domain", None, None, None)
    assert udp.scripts == ()
    assert host.host_scripts == (ScriptFinding("host-vuln", "No findings"),)
    with pytest.raises(FrozenInstanceError):
        setattr(host, "status", "down")
    assert not hasattr(report, "__dict__")


def test_connect_fallback() -> None:
    report = parse_nmap_xml((FIXTURES / "connect_fallback.xml").read_bytes())
    with pytest.raises(NmapParseError) as caught:
        verify_scan_types(report)
    assert caught.value.reason == "scan_type_mismatch"
    verify_scan_types(report, required=frozenset({"connect"}))


@pytest.mark.parametrize(
    "fixture,reason",
    [
        ("malformed.xml", "malformed_xml"),
        ("entity_bomb.xml", "forbidden_xml_construct"),
    ],
)
def test_bad_fixtures(fixture: str, reason: str) -> None:
    with pytest.raises(NmapParseError) as caught:
        parse_nmap_xml((FIXTURES / fixture).read_bytes())
    assert caught.value.reason == reason
    assert len(caught.value.reason) <= 64


@pytest.mark.parametrize(
    "data,reason",
    [
        (
            '<!DOCTYPE nmaprun SYSTEM "file:///nonexistent"><nmaprun/>',
            "forbidden_xml_construct",
        ),
        (
            '<!DOCTYPE nmaprun [<!ENTITY x SYSTEM "file:///nonexistent">]>'
            "<nmaprun>&x;</nmaprun>",
            "forbidden_xml_construct",
        ),
        ("<!DOCTYPE other><nmaprun/>", "forbidden_xml_construct"),
        ("<other/>", "unexpected_root"),
        ("<nmaprun/>", "missing_scaninfo"),
        *[
            (
                '<nmaprun><scaninfo type="syn"/><host><ports>'
                f'<port portid="{port}"/></ports></host></nmaprun>',
                "invalid_port",
            )
            for port in ("70000", "-1")
        ],
        (
            '<nmaprun><scaninfo type="syn"/><host><ports>'
            '<port portid="bad"/></ports></host></nmaprun>',
            "invalid_port",
        ),
    ],
)
def test_rejected_xml(data: str, reason: str) -> None:
    with pytest.raises(NmapParseError) as caught:
        parse_nmap_xml(data)
    assert caught.value.reason == reason


def test_missing_optional_attributes() -> None:
    report = parse_nmap_xml(
        '<nmaprun><scaninfo type="syn"/><host><ports>'
        '<port protocol="tcp" portid="80"/><port protocol="udp" portid="53">'
        "<service/><script/></port></ports><hostscript><script/></hostscript>"
        "</host></nmaprun>"
    )
    host = report.hosts[0]
    assert (host.addresses, host.hostnames, host.os_matches) == ((), (), ())
    assert host.status is None
    assert host.ports[0].state is None
    assert host.ports[0].service is None
    assert host.ports[1].service == NmapService(None, None, None, None)
    assert host.ports[1].scripts == (ScriptFinding(None, None),)
    assert host.host_scripts == (ScriptFinding(None, None),)
