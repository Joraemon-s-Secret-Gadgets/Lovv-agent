from __future__ import annotations

from typing import Any

from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.core.runtime_state import invocation_runtime
from lovv_agent_v2.core.state import UnifiedAgentState


def test_intent_node_uses_prompt_runtime_for_modify_intent() -> None:
    runtime = RecordingIntentRuntime(
        {
            "status": "ok",
            "kind": "slot_replace",
            "edit_ops": [
                {
                    "op_id": "op-1",
                    "op": "REPLACE",
                    "target": {
                        "item_id": "item-2",
                        "content_id": "attraction#127691",
                        "item_type": "attraction",
                        "day": 1,
                        "order": 2,
                        "target_text": "이이 유적",
                        "resolution": "exact",
                    },
                    "condition": {
                        "replacement_query": "실내 전시 공간",
                        "theme": "예술·감성",
                        "mood": "quiet",
                        "place_type": "museum",
                        "location": None,
                        "avoid_content_ids": ["attraction#127691"],
                    },
                    "seed_policy": {
                        "target_is_seed": False,
                        "policy": "not_seed",
                    },
                },
            ],
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
    )
    state: UnifiedAgentState = {
        "request": {
            "entryType": "modify",
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 오후 이이 유적 말고 실내 전시 공간으로 바꿔줘.",
            "currentOrder": [
                {
                    "itemId": "item-2",
                    "contentId": "attraction#127691",
                    "itemType": "attraction",
                    "day": 1,
                    "order": 2,
                    "title": "이이 유적",
                    "isSeed": False,
                },
            ],
        },
    }

    with invocation_runtime(
        {"intent_prompt_runtime": {"runtime": runtime, "schema_retry_limit": 0}},
    ):
        output = intent_node(state)

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["intent_type"] == "modification"
    assert modify_intent["raw_modify_query"] == state["request"]["rawModifyQuery"]
    assert modify_intent["edit_ops"][0]["condition"]["replacement_query"] == "실내 전시 공간"
    assert modify_intent["edit_ops"][0]["condition"]["theme"] == "예술·감성"
    assert modify_intent["audit"] == {"parser": "llm"}
    assert "Lovv V2 Modify Intent Agent" in runtime.requests[0]["system"][0]["text"]


class RecordingIntentRuntime:
    def __init__(self, structured_output: dict[str, Any]) -> None:
        self.structured_output = structured_output
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        return {"structured_output": self.structured_output}
