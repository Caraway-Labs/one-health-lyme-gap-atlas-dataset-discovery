"""Import-safe foundation graph; replaced by reviewed v1 flow in Story #12."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class FoundationState(TypedDict, total=False):
    """Small import/smoke contract, not the v1 DatasetDiscoveryState."""

    fixture_id: str
    status: str


def _fixture_smoke(state: FoundationState) -> FoundationState:
    """Prove the graph can compile and run without external services."""
    return {"status": "FOUNDATION_READY", "fixture_id": state.get("fixture_id", "default")}


builder = StateGraph(FoundationState)
builder.add_node("fixture_smoke", _fixture_smoke)
builder.add_edge(START, "fixture_smoke")
builder.add_edge("fixture_smoke", END)
graph = builder.compile()
