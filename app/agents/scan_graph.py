"""The scan graph: Nmap -> parse -> dedup -> persist (F2 slice 9).

The graph replaces the imperative body of ``execute_scan`` with four named
nodes, without touching the scan state machine: the transitions, the single
commit and the shielded cancellation stay in the executor. A node that sets
``error`` ends the graph early, and ``run_agent_safely`` turns that into the
scan's failure reason.

The enrichment is deliberately *not* a node: ``enrichment.vulnerability`` stays
the single owner of it (see the slice 9 ADR).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import ScanState
from app.core.config import settings
from app.core.database import set_tenant_context
from app.modules.scans.nmap.command import build_nmap_command, split_by_family
from app.modules.scans.nmap.findings import FindingDraft, extract_findings
from app.modules.scans.nmap.parser import (
    NmapParseError,
    parse_nmap_xml,
    verify_scan_types,
)
from app.modules.scans.nmap.runner import NmapRunError, NmapRunResult, run_nmap
from app.modules.scans.targets import (
    Resolver,
    TargetRejectedError,
    resolve_scan_target,
)
from app.modules.vulnerabilities.service import finding_identity, upsert_findings

logger = logging.getLogger(__name__)

NMAP_TIMEOUT_SECONDS = 3600.0
NMAP_MAX_OUTPUT_BYTES = 10 * 1024 * 1024

RunNmap = Callable[..., Awaitable[NmapRunResult]]


async def scan_node(
    state: ScanState,
    *,
    resolver: Resolver | None = None,
    nmap_path: str = "nmap",
    timeout: float = NMAP_TIMEOUT_SECONDS,
    max_output_bytes: int = NMAP_MAX_OUTPUT_BYTES,
    run: RunNmap = run_nmap,
) -> ScanState:
    """Run Nmap once per address family, collecting one document per run.

    A rejected target or a runner failure becomes ``error`` with the same reason
    codes the executor used to pass as ``failure_reason``.
    """
    asset = state["asset"]
    try:
        target = await resolve_scan_target(
            asset["asset_type"], asset["value"], resolver=resolver
        )
    except TargetRejectedError as exc:
        return {"error": exc.reason}

    documents: list[str] = []
    for family in split_by_family(target):
        argv = build_nmap_command(family, nmap_path=nmap_path)
        try:
            result = await run(
                argv,
                timeout=timeout,
                max_output_bytes=max_output_bytes,
                supervise_seconds=(
                    int(timeout) if settings.NMAP_PROCESS_SUPERVISION else None
                ),
            )
        except NmapRunError as exc:
            logger.warning(
                "Nmap scan_id=%s reason=%s detail=%s",
                state.get("scan_id"),
                exc.reason,
                exc.detail,
            )
            return {"error": exc.reason}
        documents.append(result.stdout.decode("utf-8", errors="replace"))
    return {"nmap_documents": documents, "nmap_raw_xml": "\n".join(documents)}


def parse_node(state: ScanState) -> ScanState:
    """Turn the raw documents into findings. Nmap output stays untrusted data."""
    drafts: list[FindingDraft] = []
    for document in state.get("nmap_documents", []):
        try:
            report = parse_nmap_xml(document)
            verify_scan_types(report)
        except NmapParseError as exc:
            return {"error": exc.reason}
        drafts.extend(extract_findings(report))
    return {"raw_findings": [asdict(draft) for draft in drafts]}


def dedup_node(state: ScanState) -> ScanState:
    """Drop the findings that repeat inside this scan, keeping the first one.

    The database check needs the session, so it lives in ``upsert_findings``;
    this node only removes repeats that one run produced.
    """
    seen: set[str] = set()
    kept: list[dict] = []
    skipped = 0
    for finding in state.get("raw_findings", []):
        key = finding_identity(
            metadata=finding.get("metadata"),
            cve_id=finding.get("cve_id"),
            title=finding.get("title", ""),
        )
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        kept.append(finding)
    return {"raw_findings": kept, "dedup_skipped": skipped}


async def persist_node(
    state: ScanState, *, session: AsyncSession, tenant_id: uuid.UUID
) -> ScanState:
    """Store the surviving findings. The executor still owns the commit.

    The node re-applies the RLS context instead of trusting the caller's: a
    commit anywhere in the run (the cancellation path can commit) expires the
    transaction-local setting, and without the context the insert is rejected
    by the row-level policy.
    """
    await set_tenant_context(session, tenant_id, False)
    result = await upsert_findings(
        session,
        scan_id=uuid.UUID(state["scan_id"]),
        tenant_id=tenant_id,
        drafts=[FindingDraft(**finding) for finding in state.get("raw_findings", [])],
    )
    logger.info(
        "scan_id=%s findings created=%d skipped=%d",
        state.get("scan_id"),
        result.created,
        result.skipped,
    )
    return {"completed": True}


def build_scan_graph(
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    resolver: Resolver | None = None,
    nmap_path: str = "nmap",
    timeout: float = NMAP_TIMEOUT_SECONDS,
    max_output_bytes: int = NMAP_MAX_OUTPUT_BYTES,
    run: RunNmap = run_nmap,
) -> CompiledStateGraph:
    """Wire the four nodes around the surviving findings.

    The dependencies are captured per scan: the graph is built for one executor
    call and holds that call's session, so no node ever reaches for global
    state. Without a checkpointer the state lives only for the run.
    """

    async def run_scan(state: ScanState) -> ScanState:
        return await scan_node(
            state,
            resolver=resolver,
            nmap_path=nmap_path,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            run=run,
        )

    def run_parse(state: ScanState) -> ScanState:
        return parse_node(state)

    def run_dedup(state: ScanState) -> ScanState:
        return dedup_node(state)

    async def run_persist(state: ScanState) -> ScanState:
        return await persist_node(state, session=session, tenant_id=tenant_id)

    def next_step(state: ScanState) -> str:
        return "stop" if state.get("error") else "continue"

    builder = StateGraph(ScanState)
    builder.add_node("scan", run_scan)
    builder.add_node("parse", run_parse)
    builder.add_node("dedup", run_dedup)
    builder.add_node("persist", run_persist)
    builder.add_edge(START, "scan")
    for source, following in (
        ("scan", "parse"),
        ("parse", "dedup"),
        ("dedup", "persist"),
    ):
        builder.add_conditional_edges(
            source, next_step, {"continue": following, "stop": END}
        )
    builder.add_edge("persist", END)
    return builder.compile()
