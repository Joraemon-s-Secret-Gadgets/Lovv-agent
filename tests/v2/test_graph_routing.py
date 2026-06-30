from __future__ import annotations

from lovv_agent_v2.agents.supervisor.router import supervisor_node


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
