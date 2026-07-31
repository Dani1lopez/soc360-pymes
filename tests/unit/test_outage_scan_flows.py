import pytest

from app.core.outage import ALL_FLOW_IDS, FlowPolicy
from app.core.outage import (
    _FLOW_ID_SCAN_CANCEL_LOCK,
    _FLOW_ID_SCAN_COMPLETE_LOCK,
    _FLOW_ID_SCAN_START_LOCK,
    _FLOW_ID_SCAN_UPDATE_LOCK,
)

SCAN_FLOWS = ((_FLOW_ID_SCAN_START_LOCK, "scan_start_lock"), (_FLOW_ID_SCAN_UPDATE_LOCK, "scan_update_lock"), (_FLOW_ID_SCAN_COMPLETE_LOCK, "scan_complete_lock"), (_FLOW_ID_SCAN_CANCEL_LOCK, "scan_cancel_lock"))  # fmt: skip


@pytest.mark.parametrize(("flow_id", "expected"), SCAN_FLOWS)
def test_scan_lock_flow_ids_are_named_catalogued_and_fail_closed(flow_id, expected):
    assert flow_id == expected
    assert flow_id in ALL_FLOW_IDS
    assert FlowPolicy[flow_id] == "fail_closed"
