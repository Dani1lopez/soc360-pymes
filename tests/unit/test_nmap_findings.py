import pytest

from app.modules.scans.nmap.findings import extract_findings, severity_from_cvss
from app.modules.scans.nmap.parser import NmapHost, NmapPort, NmapReport, ScriptFinding


@pytest.mark.parametrize(
    "score,severity",
    [
        (9.0, "critical"),
        (8.9, "high"),
        (7.0, "high"),
        (4.0, "medium"),
        (3.9, "low"),
        (0.0, "info"),
        (None, "medium"),
    ],
)
def test_severity(score, severity):
    assert severity_from_cvss(score) == severity


def report(output, *, host_script=False, script_id="test"):
    script = ScriptFinding(script_id, output)
    return NmapReport(
        frozenset({"syn", "udp"}),
        (
            NmapHost(
                ("93.184.216.34",),
                (),
                "up",
                (),
                () if host_script else (NmapPort("tcp", 443, "open", None, (script,)),),
                (script,) if host_script else (),
            ),
        ),
    )


@pytest.mark.parametrize(
    "output,count",
    [
        ("VULNERABLE", 1),
        ("not vulnerable", 0),
        ("LIKELY vulnerable", 1),
        ("invulnerable", 0),
        ("NOT VULNERABLE\nVULNERABLE", 1),
        ("", 0),
    ],
)
def test_vulnerability_marker(output, count):
    assert len(extract_findings(report(output))) == count


@pytest.mark.parametrize(
    "text,score",
    [
        ("CVSS: 7.5", 7.5),
        ("cvss score 7.5", 7.5),
        ("CVSSv3 base score 9.8", 9.8),
        ("CVSS: 12", 10.0),
        ("CVSS: -2", 0.0),
    ],
)
def test_extract_scores(text, score):
    finding = extract_findings(report(f"VULNERABLE CVE-2024-12345 {text}"))[0]
    assert finding.cve_id == "CVE-2024-12345"
    assert finding.cvss_score == score
    assert finding.metadata["severity_source"] == "cvss"


def test_host_truncation_and_untrusted_data():
    finding = extract_findings(
        report(
            "VULNERABLE <script>" + "x" * 9000, host_script=True, script_id="x" * 300
        )
    )[0]
    assert len(finding.title) == 255
    assert len(finding.description) == 8000
    assert "<script>" in finding.description
    assert finding.metadata["port"] is None
    assert finding.metadata["protocol"] is None
    assert finding.severity == "medium"
    assert finding.metadata["severity_source"] == "default"


def test_multiple_hosts_ports_and_empty():
    host = report("VULNERABLE").hosts[0]
    host = NmapHost(host.addresses, (), "up", (), host.ports * 2, ())
    assert len(extract_findings(NmapReport(frozenset(), (host, host)))) == 4
    assert extract_findings(NmapReport(frozenset(), ())) == []
    assert extract_findings(report("open service")) == []
