from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.core.state import UnifiedAgentState


def intent_node(state: UnifiedAgentState) -> dict[str, Any]:
    intent = _intent_payload(state)
    next_intent = dict(intent)
    next_intent.setdefault("intent_mode", "generation")
    return {"intent": next_intent}


def _intent_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        return dict(intent)
    return {}
