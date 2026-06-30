from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.core.state import UnifiedAgentState

END_ROUTE = "end"


def supervisor_node(state: UnifiedAgentState) -> dict[str, dict[str, Any]]:
    reason_code = _clarification_reason_code(state)
    next_node = _next_node(state, reason_code=reason_code)
    completed_groups = _completed_groups(state)
    return {
        "routing": {
            "next_node": next_node,
            "completed_groups": completed_groups,
            "needs_clarification": reason_code is not None,
            "clarification_reason_code": reason_code,
        },
    }


def route_next_action(state: UnifiedAgentState) -> str:
    routing = supervisor_node(state)["routing"]
    next_node = routing.get("next_node")
    return next_node if isinstance(next_node, str) else END_ROUTE


def _next_node(state: Mapping[str, Any], *, reason_code: str | None) -> str:
    if _has_response_payload(state):
        return END_ROUTE
    if reason_code is not None:
        return "response_packager"
    if not _has_profile_result(state):
        return "profile"
    if not _has_festival_gate_result(state) and not _festivals_excluded(state):
        return "festival_verifier"
    if _city_select_needs_response(state):
        return "response_packager"
    if not _has_city_selection_result(state):
        return "city_select"
    if not _has_planner_output(state):
        return "planner"
    if not _has_itinerary_explanation(state):
        return "explain_itinerary"
    return "response_packager"


def _completed_groups(state: Mapping[str, Any]) -> list[str]:
    completed: list[str] = []
    if _has_profile_result(state):
        completed.append("profile")
    if _has_festival_gate_result(state) or _festivals_excluded(state):
        completed.append("festival_gate")
    if _has_city_select_result_or_terminal_status(state):
        completed.append("city_select")
    if _has_planner_output(state):
        completed.append("planner")
    if _has_response_payload(state):
        completed.append("response")
    return completed


def _clarification_reason_code(state: Mapping[str, Any]) -> str | None:
    for group_name in ("festival_gate", "city_select", "response"):
        group = state.get(group_name)
        if not isinstance(group, Mapping):
            continue
        clarification = group.get("clarification")
        if not isinstance(clarification, Mapping):
            continue
        value = clarification.get("reason_code")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _has_profile_result(state: Mapping[str, Any]) -> bool:
    profile = state.get("profile")
    return isinstance(profile, Mapping) and "audit" in profile


def _has_festival_gate_result(state: Mapping[str, Any]) -> bool:
    festival_gate = state.get("festival_gate")
    return isinstance(festival_gate, Mapping) and (
        "result" in festival_gate or "audit" in festival_gate
    )


def _festivals_excluded(state: Mapping[str, Any]) -> bool:
    request = state.get("request")
    if isinstance(request, Mapping) and request.get("include_festivals") is False:
        return True
    intent = state.get("intent")
    if not isinstance(intent, Mapping):
        return False
    city_input = intent.get("city_select_input")
    return isinstance(city_input, Mapping) and city_input.get("include_festivals") is False


def _has_city_selection_result(state: Mapping[str, Any]) -> bool:
    city_select = state.get("city_select")
    if not isinstance(city_select, Mapping):
        return False
    return isinstance(city_select.get("city_selection_result"), Mapping)


def _has_city_select_result_or_terminal_status(state: Mapping[str, Any]) -> bool:
    city_select = state.get("city_select")
    if not isinstance(city_select, Mapping):
        return False
    return isinstance(city_select.get("city_selection_result"), Mapping) or isinstance(
        city_select.get("status"),
        str,
    )


def _city_select_needs_response(state: Mapping[str, Any]) -> bool:
    city_select = state.get("city_select")
    if not isinstance(city_select, Mapping):
        return False
    if isinstance(city_select.get("city_selection_result"), Mapping):
        return False
    status = city_select.get("status")
    return isinstance(status, str) and status != "ok"


def _has_planner_output(state: Mapping[str, Any]) -> bool:
    planner = state.get("planner")
    return isinstance(planner, Mapping) and isinstance(planner.get("planner_output"), Mapping)


def _has_itinerary_explanation(state: Mapping[str, Any]) -> bool:
    planner = state.get("planner")
    if not isinstance(planner, Mapping):
        return False
    validation = planner.get("validation_result")
    if not isinstance(validation, Mapping):
        planner_output = planner.get("planner_output")
        if isinstance(planner_output, Mapping):
            validation = planner_output.get("validation_result")
    if not isinstance(validation, Mapping):
        return False
    return (
        "planner_copy_generation_used_llm" in validation
        or "detail_enrichment_warning_count" in validation
        or "itinerary_explanation_item_count" in validation
    )


def _has_response_payload(state: Mapping[str, Any]) -> bool:
    response = state.get("response")
    return isinstance(response, Mapping) and isinstance(response.get("response_payload"), Mapping)


__all__ = ["END_ROUTE", "route_next_action", "supervisor_node"]
