"""Main Graph definition and routing compilation."""

from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.agents.city_select.subgraph import compile_city_select_subgraph


def compile_v2_graph(checkpointer: Any | None = None) -> Any:
    """Build and compile the main LangGraph for V2."""

    workflow = StateGraph(UnifiedAgentState)

    # Register city_select subgraph as a node
    city_select_subgraph = compile_city_select_subgraph(checkpointer=checkpointer)
    workflow.add_node("city_select", city_select_subgraph)

    # Baseline: single city_select node flow
    workflow.set_entry_point("city_select")
    workflow.set_finish_point("city_select")

    return workflow.compile(checkpointer=checkpointer)

