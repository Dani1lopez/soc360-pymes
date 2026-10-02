"""Pure extraction of vulnerable NSE scripts; output remains untrusted data."""

import re
from dataclasses import dataclass

from app.modules.scans.nmap.parser import NmapReport, ScriptFinding


@dataclass(frozen=True, slots=True)
class FindingDraft:
    title: str
    description: str
    severity: str
    cve_id: str | None
    cvss_score: float | None
    metadata: dict[str, object]


def severity_from_cvss(score: float | None) -> str:
    if score is None:
        return "medium"
    if score >= 9:
        return "critical"
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    return "low" if score > 0 else "info"


def extract_findings(report: NmapReport) -> list[FindingDraft]:
    findings = []
    for host in report.hosts:
        address = host.addresses[0] if host.addresses else "unknown"
        scripts: list[tuple[ScriptFinding, int | None, str | None]] = [
            (script, None, None) for script in host.host_scripts
        ]
        scripts.extend(
            (script, port.port_id, port.protocol)
            for port in host.ports
            for script in port.scripts
        )
        for script, port, protocol in scripts:
            output = script.output or ""
            positive = re.sub(r"\bNOT\s+VULNERABLE\b", "", output, flags=re.I)
            if not re.search(r"\bVULNERABLE\b", positive, re.I):
                continue
            cve = re.search(r"CVE-\d{4}-\d{4,}", output)
            # A vector string ("CVSS:3.1/AV:N/...") carries a version, not a score.
            scored = re.sub(r"\bCVSS:\d(?:\.\d)?/\S*", "", output, flags=re.I)
            cvss = re.search(
                r"\bCVSS(?:v\d(?:\.\d)?)?[^\d\n+-]*([+-]?\d+(?:\.\d+)?)", scored, re.I
            )
            score = round(min(10.0, max(0.0, float(cvss[1]))), 1) if cvss else None
            suffix = f":{port}/{protocol}" if port is not None else ""
            findings.append(
                FindingDraft(
                    title=f"{script.script_id} on {address}{suffix}"[:255],
                    description=output[:8000],
                    severity=severity_from_cvss(score),
                    cve_id=cve[0][:50] if cve else None,
                    cvss_score=score,
                    metadata={
                        "source": "nmap",
                        "script_id": script.script_id,
                        "host": address,
                        "port": port,
                        "protocol": protocol,
                        "severity_source": "cvss" if score is not None else "default",
                    },
                )
            )
    return findings
