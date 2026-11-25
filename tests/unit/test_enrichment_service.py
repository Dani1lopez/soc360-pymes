"""Cache eligibility and tenant-level scope without database access."""
from __future__ import annotations

import pytest
from app.modules.enrichment.service import due_functions

from app.modules.enrichment.prompts import PROMPT_VERSIONS, functions_for_level
from app.modules.vulnerabilities.enrichment_models import VulnerabilityEnrichment


def _row(**changes) -> VulnerabilityEnrichment:
    values = {"function": "executive_summary", "status": "ok", "input_hash": "snapshot",
              "model": "test-model", "prompt_version": PROMPT_VERSIONS["executive_summary"]}
    values.update(changes)
    return VulnerabilityEnrichment(**values)


def test_matching_success_is_skipped():
    assert due_functions("basic", {"executive_summary": _row()},
                         input_hash="snapshot", model="test-model") == (
        "contextual_severity", "remediation",
    )


@pytest.mark.parametrize("changes", [
    {"input_hash": "old"}, {"model": "old"}, {"prompt_version": "old"},
    {"status": "failed"}, {"status": "pending"},
])
def test_changed_identity_or_unsuccessful_row_is_due(changes):
    assert due_functions("basic", {"executive_summary": _row(**changes)},
                         input_hash="snapshot", model="test-model") == functions_for_level("basic")


@pytest.mark.parametrize("level", ["basic", "standard", "full"])
def test_level_scopes_missing_functions(level):
    assert due_functions(level, {}, input_hash="snapshot", model="test-model") == functions_for_level(level)


def test_only_functions_intersects_scope_in_level_order():
    assert due_functions("basic", {}, input_hash="snapshot", model="test-model",
                         only_functions=("remediation", "references", "executive_summary")) == (
        "executive_summary", "remediation",
    )
    assert due_functions("full", {}, input_hash="snapshot", model="test-model",
                         only_functions=()) == ()
