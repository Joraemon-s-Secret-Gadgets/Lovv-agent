from __future__ import annotations

from lovv_agent_v2.agents.intent.node import intent_node


def test_intent_node_passes_generation_mode_intent_to_supervisor() -> None:
    state = {
        "intent": {
            "intent_output": {"country": "KR"},
            "raw": "preserved",
        },
        "request": {"request_id": "REQ-1"},
    }

    result = intent_node(state)

    assert result["intent"]["intent_output"] == {"country": "KR"}
    assert result["intent"]["raw"] == "preserved"
    assert result["intent"]["intent_mode"] == "generation"
    assert "city_select_input" not in result["intent"]
