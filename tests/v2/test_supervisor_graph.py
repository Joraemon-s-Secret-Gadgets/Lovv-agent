from __future__ import annotations

from lovv_agent_v2.agents.supervisor.router import supervisor_node


def test_supervisor_starts_non_intent_flow_at_profile() -> None:
    result = supervisor_node({"intent": {"intent_output": {"country": "KR"}}})

    assert result["routing"]["next_node"] == "profile"
    assert result["routing"]["completed_groups"] == []


def test_supervisor_routes_profile_to_festival_gate() -> None:
    result = supervisor_node(
        {
            "intent": {"city_select_input": {"country": "KR"}},
            "profile": {"audit": {"profile_active": False}},
        },
    )

    assert result["routing"]["next_node"] == "festival_verifier"
    assert result["routing"]["completed_groups"] == ["profile"]


def test_supervisor_routes_itinerary_confirmation_to_profile_before_end() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REC-1",
            },
        },
    )

    assert result["routing"]["next_node"] == "profile"
    assert result["routing"]["completed_groups"] == []


def test_supervisor_ends_after_itinerary_confirmation_profile_update() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REC-1",
            },
            "profile": {
                "profile_update": {"reason": "itinerary_confirmed"},
                "audit": {"profile_update_requested": True},
            },
        },
    )

    assert result["routing"]["next_node"] == "end"
    assert result["routing"]["completed_groups"] == ["profile"]


def test_supervisor_skips_festival_gate_when_festivals_excluded() -> None:
    result = supervisor_node(
        {
            "request": {"include_festivals": False},
            "intent": {"city_select_input": {"country": "KR", "include_festivals": False}},
            "profile": {"audit": {"profile_active": False}},
        },
    )

    assert result["routing"]["next_node"] == "city_select"
    assert result["routing"]["completed_groups"] == ["profile", "festival_gate"]


def test_supervisor_routes_single_anchor_without_festival_to_planner() -> None:
    result = supervisor_node(
        {
            "request": {"include_festivals": False},
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "include_festivals": False,
                    "destination_id": "KR-47-130",
                },
            },
            "profile": {"audit": {"profile_active": False}},
        },
    )

    assert result["routing"]["next_node"] == "planner"
    assert result["routing"]["completed_groups"] == ["profile", "festival_gate"]


def test_supervisor_routes_confirmed_festival_anchor_to_planner() -> None:
    result = supervisor_node(
        {
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "include_festivals": True,
                    "destination_id": "KR-47-130",
                },
            },
            "profile": {"audit": {"profile_active": False}},
            "festival_gate": {
                "result": {
                    "status": "ok",
                    "allowed_city_ids": ["KR-47-130"],
                },
            },
        },
    )

    assert result["routing"]["next_node"] == "planner"
    assert result["routing"]["completed_groups"] == ["profile", "festival_gate"]


def test_supervisor_routes_clarification_to_response_packager() -> None:
    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {
                "result": {"status": "needs_clarification"},
                "clarification": {"reason_code": "festival_tentative"},
            },
        },
    )

    assert result["routing"]["next_node"] == "response_packager"
    assert result["routing"]["needs_clarification"] is True
    assert result["routing"]["clarification_reason_code"] == "festival_tentative"


def test_supervisor_routes_city_selection_to_planner() -> None:
    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {"result": None, "audit": {"skipped": True}},
            "city_select": {"city_selection_result": {"selected_city": {"city_id": "KR-A"}}},
        },
    )

    assert result["routing"]["next_node"] == "planner"
    assert result["routing"]["completed_groups"] == [
        "profile",
        "festival_gate",
        "city_select",
    ]


def test_supervisor_finishes_after_response_payload() -> None:
    result = supervisor_node(
        {
            "response": {
                "response_status": "modification_pending",
                "response_payload": {"recommendationId": "REQ-1"},
            },
        },
    )

    assert result["routing"]["next_node"] == "end"
    assert result["routing"]["completed_groups"] == ["response"]
