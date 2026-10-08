"""Slice 9 T0: the scan-pipeline contracts have one home each.

``app/core/contracts.py`` was dead code: nothing imported it, it duplicated the
canonical severity/status literals of ``app/event_schemas`` (with the status set
in drift) and it declared an ``EnrichedFinding`` nobody consumed. The graph
state moves to ``app/agents/state.py`` and the upsert result to its producer.
"""

from __future__ import annotations

import importlib.util

from app.agents.state import ScanState
from app.event_schemas import VulnerabilityStatus


def test_contracts_module_no_longer_exists() -> None:
    assert importlib.util.find_spec("app.core.contracts") is None


def test_scan_state_declares_the_pipeline_keys() -> None:
    keys = set(ScanState.__annotations__)
    assert {
        "scan_id",
        "tenant_id",
        "asset",
        "nmap_raw_xml",
        "raw_findings",
        "error",
        "completed",
    } <= keys


def test_vulnerability_statuses_keep_a_single_canonical_source() -> None:
    assert set(VulnerabilityStatus.__args__) == {
        "open",
        "fixed",
        "accepted_risk",
        "false_positive",
    }


def test_upsert_result_lives_with_its_producer() -> None:
    from app.modules.vulnerabilities.service import UpsertVulnerabilitiesResult

    result = UpsertVulnerabilitiesResult(created=2, updated=1, skipped=0)
    assert result.total == 3
    assert result.has_new_findings
