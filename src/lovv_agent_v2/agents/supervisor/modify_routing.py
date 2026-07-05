from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def slot_replace_applied(state: Mapping[str, Any]) -> bool:
    context = planner_modify_context(state)
    applied = context.get("applied_edit")
    return isinstance(applied, Mapping) and _belongs_to_current_request(state, applied)


def slot_replace_failed(state: Mapping[str, Any]) -> bool:
    context = planner_modify_context(state)
    failed = context.get("failed_edit")
    return isinstance(failed, Mapping) and _belongs_to_current_request(state, failed)


def has_current_modify_response_payload(
    state: Mapping[str, Any],
    modify_intent: Mapping[str, Any],
) -> bool:
    if modify_intent.get("kind") == "slot_replace":
        return _has_current_slot_replace_response(state)
    city_change = modify_intent.get("city_change")
    if not isinstance(city_change, Mapping):
        return False
    response = state.get("response")
    if not isinstance(response, Mapping):
        return False
    payload = response.get("response_payload")
    if not isinstance(payload, Mapping):
        return False
    destination = payload.get("destination")
    if not isinstance(destination, Mapping):
        return False
    target_id = city_change.get("target_city_id")
    if isinstance(target_id, str) and destination.get("destinationId") == target_id:
        return True
    target_name = city_change.get("target_city_name")
    if not isinstance(target_id, str) and not isinstance(target_name, str):
        return _targetless_city_change_matches_response(city_change, destination)
    return isinstance(target_name, str) and destination.get("name") == target_name


def _targetless_city_change_matches_response(
    city_change: Mapping[str, Any],
    destination: Mapping[str, Any],
) -> bool:
    destination_id = destination.get("destinationId")
    if not isinstance(destination_id, str) or not destination_id.strip():
        return False
    avoid_city_ids = city_change.get("avoid_city_ids")
    if not isinstance(avoid_city_ids, (list, tuple)):
        return True
    return destination_id not in {item for item in avoid_city_ids if isinstance(item, str)}


def _has_current_slot_replace_response(state: Mapping[str, Any]) -> bool:
    response = state.get("response")
    if not isinstance(response, Mapping):
        return False
    payload = response.get("response_payload")
    if not isinstance(payload, Mapping):
        return False
    current_id = _request_id(state)
    recommendation_id = payload.get("recommendationId", payload.get("recommendation_id"))
    if current_id is None:
        return slot_replace_applied(state)
    return isinstance(recommendation_id, str) and recommendation_id == current_id


def planner_modify_context(state: Mapping[str, Any]) -> Mapping[str, Any]:
    planner = state.get("planner")
    if not isinstance(planner, Mapping):
        return {}
    context = planner.get("modify_context")
    return context if isinstance(context, Mapping) else {}


def _belongs_to_current_request(
    state: Mapping[str, Any],
    edit_result: Mapping[str, Any],
) -> bool:
    current_id = _request_id(state)
    result_id = edit_result.get("request_id")
    if current_id is None:
        return True
    return isinstance(result_id, str) and result_id == current_id


def _request_id(state: Mapping[str, Any]) -> str | None:
    request = state.get("request")
    if not isinstance(request, Mapping):
        return None
    for key in ("requestId", "request_id"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
