from __future__ import annotations

from lovv_agent_v2.agents.supervisor.router import supervisor_node
from lovv_agent_v2.core.graph import compile_v2_graph


def test_graph_enters_through_generation_intent_before_supervisor() -> None:
    graph = compile_v2_graph()

    result = graph.invoke(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REC-1",
            },
            "profile": {
                "lovv_user_profile": {
                    "saved_trip_count": 0,
                    "saved_theme_counts": {},
                },
            },
        },
    )

    assert result["intent"]["intent_mode"] == "generation"
    assert result["profile"]["profile_update"]["reason"] == "itinerary_confirmed"
    assert result["routing"]["next_node"] == "end"


def test_graph_routes_city_select_failure_to_response_packager() -> None:
    state = {
        "city_select": {
            "city_selection_result": None,
            "status": "no_candidate",
            "clarifying_question": "조건을 조정해 주세요.",
        },
    }

    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {"result": None, "audit": {"skipped": True}},
            **state,
        },
    )

    assert result["routing"]["next_node"] == "response_packager"


def test_graph_routes_city_select_success_to_planner() -> None:
    state = {
        "city_select": {
            "city_selection_result": {
                "selected_city": {"city_id": "KR-TEST", "country": "KR"},
            },
            "status": "ok",
        },
    }

    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {"result": None, "audit": {"skipped": True}},
            **state,
        },
    )

    assert result["routing"]["next_node"] == "planner"
