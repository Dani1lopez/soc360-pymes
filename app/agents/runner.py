"""Run a compiled graph so a failure never leaves a scan half-done (slice 9)."""

from __future__ import annotations

import asyncio
import logging

from langgraph.errors import NodeCancelledError
from langgraph.graph.state import CompiledStateGraph

from app.agents.state import ScanState

logger = logging.getLogger(__name__)

INTERNAL_ERROR = "internal_error"


async def run_agent_safely(
    graph: CompiledStateGraph, initial_state: ScanState
) -> ScanState:
    """Invoke ``graph`` and turn any ordinary failure into state.

    The executor reads ``error`` and transitions the scan to ``failed`` with
    that reason, so an unexpected exception must not escape: it is logged and
    reported as ``internal_error`` — the code the executor already used for
    unexpected failures — with ``completed`` forced to ``False``.

    ``asyncio.CancelledError`` is deliberately not caught: it is not an
    ``Exception``, and it is exactly how the worker tells the executor to
    cancel the scan and terminate the live Nmap process.
    """
    try:
        return await graph.ainvoke(initial_state)
    except NodeCancelledError as exc:
        # LangGraph converts a node's CancelledError into its own error class.
        # A node that dies of cancellation is a cancellation, not a graph bug:
        # the executor must still run its shielded ``cancelled`` transition.
        raise asyncio.CancelledError from exc
    except Exception:
        logger.exception("Scan graph failed scan_id=%s", initial_state.get("scan_id"))
        return {**initial_state, "error": INTERNAL_ERROR, "completed": False}
