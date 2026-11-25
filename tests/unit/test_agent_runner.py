"""Slice 9 T4: ``run_agent_safely`` is the one place a graph may fail.

The executor maps ``error`` onto the scan's ``failed`` transition, so an
ordinary failure must come back as state, never as an exception. Cancellation
is the exception: it is how the worker asks the executor to cancel the scan and
kill the live Nmap process.
"""

from __future__ import annotations

import asyncio

import pytest
from langgraph.graph import END, START, StateGraph

from app.agents.runner import run_agent_safely
from app.agents.state import ScanState


def _graph(node) -> object:
    builder = StateGraph(ScanState)
    builder.add_node("only", node)
    builder.add_edge(START, "only")
    builder.add_edge("only", END)
    return builder.compile()


async def test_it_returns_the_final_state() -> None:
    async def node(state: ScanState) -> ScanState:
        return {"completed": True}

    final = await run_agent_safely(_graph(node), {"scan_id": "scan-1", "error": None})
    assert final["completed"] is True
    assert final["scan_id"] == "scan-1"


async def test_a_raising_node_becomes_internal_error(caplog) -> None:
    async def node(state: ScanState) -> ScanState:
        raise ValueError("boom")

    final = await run_agent_safely(_graph(node), {"scan_id": "scan-1"})
    assert final["error"] == "internal_error"
    assert final["completed"] is False
    assert final["scan_id"] == "scan-1"
    assert "Scan graph failed scan_id=scan-1" in caplog.text


async def test_cancellation_propagates() -> None:
    async def node(state: ScanState) -> ScanState:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_agent_safely(_graph(node), {"scan_id": "scan-1"})
