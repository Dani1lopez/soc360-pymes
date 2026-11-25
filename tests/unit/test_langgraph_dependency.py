"""Slice 9 T2: LangGraph is pinned and accepts the scan state schema.

The slice adds one dependency, pinned exactly like the rest of
``pyproject.toml``, and no more: the graph runs inside the existing Celery scan
task, with no checkpointer and no new queue.
"""

from __future__ import annotations

import importlib.metadata

from langgraph.graph import END, START, StateGraph

from app.agents.state import ScanState

PINNED_VERSION = "1.2.14"


def test_langgraph_is_installed_at_the_pinned_version() -> None:
    assert importlib.metadata.version("langgraph") == PINNED_VERSION


async def test_langgraph_compiles_and_runs_over_scan_state() -> None:
    builder = StateGraph(ScanState)

    def mark(state: ScanState) -> dict[str, bool]:
        return {"completed": True}

    builder.add_node("mark", mark)
    builder.add_edge(START, "mark")
    builder.add_edge("mark", END)
    graph = builder.compile()

    final = await graph.ainvoke({"scan_id": "scan-1", "error": None})
    assert final["completed"] is True
    assert final["scan_id"] == "scan-1"
