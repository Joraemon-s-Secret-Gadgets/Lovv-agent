from __future__ import annotations

from lovv_agent_v2.agents.intent.parser import IntentPreferenceResult, parse_initial_query


def parse_modify_query(raw_query: str) -> IntentPreferenceResult:
    return parse_initial_query(raw_query)
