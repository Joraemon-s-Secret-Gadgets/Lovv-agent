from __future__ import annotations

from lovv_agent_v2.agents.city_select.retrieval_node import (
    _city_select_failure_state,
    _package_failure,
    prepare_city_select_context,
    retrieval_node,
)
from lovv_agent_v2.agents.profile.node import profile_node
from lovv_agent_v2.core.state import UnifiedAgentState


def _city_input() -> dict[str, object]:
    return {
        "country": "KR",
        "travel_month": 10,
        "travel_year": 2026,
        "trip_type": "2d1n",
        "active_required_themes": ["바다·해안"],
        "include_festivals": False,
        "cleaned_raw_query": "바다 여행",
        "soft_preference_query": "",
        "unsupported_conditions": [],
        "destination_id": None,
        "user_location": None,
        "execution_mode": "city_discovery",
        "congestion_pref": "neutral",
        "transport_pref": "unknown",
    }


def test_unified_agent_state_exposes_v2_23_top_level_groups() -> None:
    assert {
        "request",
        "intent",
        "profile",
        "festival_gate",
        "city_select",
        "planner",
        "response",
        "routing",
        "memory",
        "trace",
    }.issubset(UnifiedAgentState.__optional_keys__)
    assert "evidence" not in UnifiedAgentState.__optional_keys__


def test_profile_node_writes_city_select_input_and_profile_state() -> None:
    result = profile_node(
        {
            "intent": {"city_select_input": _city_input()},
            "profile": {
                "profile_record": {
                    "profile_id": "P-sea",
                    "lovv_user_profile": {
                        "saved_trip_count": 3,
                        "saved_theme_counts": {"sea_coast": 3},
                    },
                },
            },
        },
    )

    assert "city_select_input" in result["intent"]
    assert result["profile"]["applied_persona_id"] == "P-sea"
    assert result["profile"]["effective_theme_weights"] == {"바다·해안": 1.3}
    assert "profile_result" not in result["profile"]


def test_city_select_failure_uses_city_select_state_contract() -> None:
    context = prepare_city_select_context(_city_input())
    result = _package_failure(
        context,
        status="no_candidate",
        failure_signal="no_searchable_place_theme",
        needs_clarification=True,
        clarifying_question="조건을 조정해 주세요.",
    )

    state = _city_select_failure_state(result)

    assert state["city_selection_result"] is None
    assert state["status"] == "no_candidate"
    assert state["failure_signals"] == ("no_searchable_place_theme",)
    assert state["clarifying_question"] == "조건을 조정해 주세요."


def test_city_select_does_not_run_festival_lookup_without_gate_result() -> None:
    city_input = _city_input()
    city_input["include_festivals"] = True

    result = retrieval_node({"intent": {"city_select_input": city_input}})

    city_select = result["city_select"]
    assert city_select["status"] == "error"
    assert city_select["failure_signals"] == ("missing_festival_gate_allowed_city_ids",)
    assert city_select["retrieval_audit"]["festival_gate_required"] is True
