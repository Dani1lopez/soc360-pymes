"""Slice 9 T3: the four scan-graph nodes, each one in isolation.

The nodes are plain functions with explicit dependencies — no session or runner
captured at import — so the graph builder can wire them and these tests can
drive them without LangGraph.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.agents.scan_graph import dedup_node, parse_node, persist_node, scan_node
from app.modules.scans.nmap.runner import NmapRunError, NmapRunResult

XML = (
    Path("tests/fixtures/nmap/normal.xml")
    .read_bytes()
    .replace(b"unsafe &lt;script&gt; &amp; data", b"VULNERABLE CVSS: 7.5")
)

ASSET = {"asset_type": "hostname", "value": "example.com"}


def _finding(*, port: int = 8080) -> dict:
    return {
        "title": f"http-vuln-cve2017-5638 on 93.184.216.34:{port}/tcp",
        "description": "VULNERABLE CVSS: 7.5",
        "severity": "high",
        "cve_id": "CVE-2017-5638",
        "cvss_score": 7.5,
        "metadata": {
            "source": "nmap",
            "script_id": "http-vuln-cve2017-5638",
            "host": "93.184.216.34",
            "port": port,
            "protocol": "tcp",
        },
    }


async def test_scan_node_collects_one_document_per_address_family() -> None:
    run = AsyncMock(return_value=NmapRunResult(XML, "", 0))

    async def resolver(host: str) -> list[str]:
        return ["93.184.216.34", "2606:4700:4700::1111"]

    state = await scan_node({"asset": ASSET}, resolver=resolver, run=run)
    assert state["nmap_documents"] == [XML.decode(), XML.decode()]
    assert state["nmap_raw_xml"] == XML.decode() + "\n" + XML.decode()


async def test_scan_node_reports_the_nmap_failure_reason(caplog) -> None:
    run = AsyncMock(side_effect=NmapRunError("timeout", "private diagnostics"))

    async def resolver(host: str) -> list[str]:
        return ["93.184.216.34"]

    state = await scan_node(
        {"asset": ASSET, "scan_id": "scan-1"}, resolver=resolver, run=run
    )
    assert state == {"error": "timeout"}
    assert "private diagnostics" in caplog.text


async def test_scan_node_reports_a_rejected_target() -> None:
    async def resolver(host: str) -> list[str]:
        return ["127.0.0.1"]

    run = AsyncMock()
    state = await scan_node({"asset": ASSET}, resolver=resolver, run=run)
    assert state == {"error": "target_not_global"}
    run.assert_not_awaited()


async def test_parse_node_extracts_findings_from_the_documents() -> None:
    state = parse_node({"nmap_documents": [XML.decode()]})
    assert len(state["raw_findings"]) == 1
    finding = state["raw_findings"][0]
    assert finding["severity"] == "high"
    assert finding["metadata"]["source"] == "nmap"


@pytest.mark.parametrize(
    "document,reason",
    [
        ("bad", "malformed_xml"),
        (
            Path("tests/fixtures/nmap/connect_fallback.xml").read_text(),
            "scan_type_mismatch",
        ),
    ],
)
def test_parse_node_reports_the_parse_failure(document, reason) -> None:
    assert parse_node({"nmap_documents": [document]}) == {"error": reason}


def test_dedup_node_drops_repeats_and_keeps_order() -> None:
    first, second = _finding(port=8080), _finding(port=8443)
    state = dedup_node({"raw_findings": [first, first, second]})
    assert state["raw_findings"] == [first, second]
    assert state["dedup_skipped"] == 1


async def test_persist_node_writes_the_survivors_and_completes() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
        add=Mock(),
        flush=AsyncMock(),
    )
    state = await persist_node(
        {"scan_id": str(uuid4()), "raw_findings": [_finding()]},
        session=session,
        tenant_id=uuid4(),
    )
    assert state == {"completed": True}
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
