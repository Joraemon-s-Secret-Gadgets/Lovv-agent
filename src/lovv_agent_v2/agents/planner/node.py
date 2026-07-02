from __future__ import annotations

from lovv_agent_v2.agents.planner.state_adapter import run_planner_agent
from lovv_agent_v2.core.state import UnifiedAgentState


def planner_node(state: UnifiedAgentState) -> dict[str, object]:
    return run_planner_agent(state)
