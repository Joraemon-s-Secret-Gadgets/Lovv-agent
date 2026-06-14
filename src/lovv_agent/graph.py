"""Graph skeleton for the Lovv recommendation agent.

Task 1.1 only defines the planned node order and safe placeholder helpers.
Actual LangGraph compilation, edge functions, and runtime invocation belong to
later graph integration tasks.
"""

from __future__ import annotations

GRAPH_NODE_ORDER: tuple[str, ...] = (
    "intent_agent",
    "supervisor_router",
    "candidate_evidence_agent",
    "supervisor_router",
    "festival_verifier_agent_or_skip",
    "supervisor_router",
    "planner_agent",
    "supervisor_router",
    "response_packager",
)

CLARIFICATION_TERMINAL = "END_WAIT_USER"


def get_graph_skeleton() -> tuple[str, ...]:
    """Return the planned graph node order without compiling a graph.

    The helper exists so smoke tests can verify the package layout without
    importing LangGraph or touching provider-specific dependencies.
    """

    return GRAPH_NODE_ORDER


__all__ = ["CLARIFICATION_TERMINAL", "GRAPH_NODE_ORDER", "get_graph_skeleton"]
