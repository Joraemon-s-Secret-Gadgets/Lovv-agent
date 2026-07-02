from __future__ import annotations

from langgraph.graph import END, StateGraph

from lovv_agent_v2.agents.planner.state_adapter import (
    assemble_itinerary_step,
    retrieve_places,
    retry_alternative_city,
    route_days_step,
)
from lovv_agent_v2.agents.planner.steps.retry_alternative_city.node import (
    should_retry_alternative_city,
)
from lovv_agent_v2.core.state import UnifiedAgentState


def compile_planner_subgraph(checkpointer: object | None = None) -> object:
    workflow = StateGraph(UnifiedAgentState)
    workflow.add_node("retrieve_places", retrieve_places)
    workflow.add_node("route_days", route_days_step)
    workflow.add_node("assemble_itinerary", assemble_itinerary_step)
    workflow.add_node("retry_alternative_city", retry_alternative_city)
    workflow.set_entry_point("retrieve_places")
    workflow.add_edge("retrieve_places", "route_days")
    workflow.add_edge("route_days", "assemble_itinerary")
    workflow.add_conditional_edges(
        "assemble_itinerary",
        _route_after_assemble,
        {"retry_alternative_city": "retry_alternative_city", "finish": END},
    )
    workflow.add_edge("retry_alternative_city", "retrieve_places")
    return workflow.compile(checkpointer=checkpointer)


def _route_after_assemble(state: UnifiedAgentState) -> str:
    if should_retry_alternative_city(state):
        return "retry_alternative_city"
    return "finish"
