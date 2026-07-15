from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver

from lovv_agent_v2.harness import build_v2_harness
from lovv_agent_v2.infra.config import RuntimeConfig


def test_missing_current_itinerary_returns_public_clarification() -> None:
    harness = build_v2_harness(
        config=RuntimeConfig(),
        checkpointer=MemorySaver(),
        runtime={"interrupts_enabled": False},
    )

    result = harness.invoke(
        {
            "request": {
                "entryType": "modify",
                "request_id": "REQ-MISSING-E2E",
                "threadId": "thread-missing-e2e",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 두 번째 장소 바꿔줘.",
            },
            "profile": {},
        },
        request_id="REQ-MISSING-E2E",
        graph_config={
            "configurable": {
                "thread_id": "thread-missing-e2e",
                "actor_id": "thread-missing-e2e",
            },
        },
    )

    response = result["response"]
    clarification = response["response_payload"]["clarification"]
    assert response["response_status"] == "END_WAIT_USER"
    assert clarification["reasonCode"] == "modify_missing_current_itinerary"
    assert clarification["options"]
