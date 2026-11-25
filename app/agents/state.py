"""State carried through the scan graph (F2 slice 9).

LangGraph updates a state channel per key a node returns, so ``total=False``
lets every node publish only what it changes. ``run_agent_safely()``
(``app/agents/runner.py``) reads the final state and turns ``error`` into the
scan's failure reason.

The scan pipeline is wired as ``scan -> parse -> dedup -> persist``:

* ``scan`` runs Nmap per address family and stores one document per run.
* ``parse`` turns those documents into raw findings (untrusted data).
* ``dedup`` drops findings already seen in the same scan.
* ``persist`` writes the survivors and sets ``completed``.

``nmap_raw_xml`` is the joined document set, the same text the scan row keeps in
``raw_output``. ``enriched_findings``/``llm_failed`` remain declared for the
enrichment contract, but the enrichment itself stays owned by the
``enrichment.vulnerability`` Celery task, not by this graph.
"""

from __future__ import annotations

from typing import TypedDict


class ScanState(TypedDict, total=False):
    """Graph state. Values read from Nmap output are untrusted data."""

    scan_id: str
    tenant_id: str
    asset: dict
    nmap_documents: list[str]
    nmap_raw_xml: str
    raw_findings: list[dict]
    dedup_skipped: int
    enriched_findings: list[dict]
    llm_failed: bool
    error: str | None
    completed: bool
