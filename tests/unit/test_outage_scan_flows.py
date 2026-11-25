from __future__ import annotations

import pytest

from app.core.outage import ALL_FLOW_IDS, FlowPolicy
from app.core.outage import (
    _FLOW_ID_SCAN_CANCEL_LOCK,
    _FLOW_ID_SCAN_COMPLETE_LOCK,
    _FLOW_ID_SCAN_START_LOCK,
    _FLOW_ID_SCAN_UPDATE_LOCK,
)
from tests.unit.test_outage_primitives import FLOW_ID_EVIDENCE

SCAN_FLOWS = (
    (_FLOW_ID_SCAN_START_LOCK, "scan_start_lock"),
    (_FLOW_ID_SCAN_UPDATE_LOCK, "scan_update_lock"),
    (_FLOW_ID_SCAN_COMPLETE_LOCK, "scan_complete_lock"),
    (_FLOW_ID_SCAN_CANCEL_LOCK, "scan_cancel_lock"),
)
EVIDENCE_BY_FLOW_ID = {row[0]: row for row in FLOW_ID_EVIDENCE}
SCAN_FLOW_EVIDENCE = EVIDENCE_BY_FLOW_ID


@pytest.mark.parametrize(("flow_id", "expected"), SCAN_FLOWS)
def test_scan_lock_flow_ids_are_named_catalogued_and_fail_closed(flow_id, expected):
    assert flow_id == expected
    assert flow_id in ALL_FLOW_IDS
    assert FlowPolicy[flow_id] == "fail_closed"


@pytest.mark.parametrize("flow_id", [flow_id for flow_id, _ in SCAN_FLOWS])
def test_scan_lock_evidence_is_primitive_only(flow_id: str) -> None:
    """Scan rows MUST document primitive coverage, not endpoint reachability."""
    row = SCAN_FLOW_EVIDENCE[flow_id]

    assert row[1] == "app.core.dist_lock.acquire_dist_lock"
    assert row[3] == FlowPolicy[flow_id]
    assert row[4] == "primitive-only"
    assert "no app scan path" in row[5]
