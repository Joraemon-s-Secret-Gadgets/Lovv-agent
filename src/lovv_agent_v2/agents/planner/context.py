from __future__ import annotations

from collections.abc import Mapping, Sequence

from lovv_agent_v2.agents.planner.scratch import planner_scratch
from lovv_agent_v2.agents.planner.steps.retrieve_places.festival_seed import festival_seed_refs
from lovv_agent_v2.agents.planner.steps.route_days.day_profile import trip_min_place_target, trip_place_target
from lovv_agent_v2.agents.planner.tools import (
    PlannerRuntimeTools,
    runtime_tools_from_value,
    travel_time_provider_from_value,
)
from lovv_agent_v2.agents.planner.travel_time import TravelTimeProvider
from lovv_agent_v2.models.schemas import SchemaValidationError


def planner_input(state: Mapping[str, object]) -> dict[str, object]:
    city_selection = city_selection_result(state)
    selected_city_payload = mapping(city_selection.get("selected_city"), "selected_city")
    city_input = planner_city_input(state)
    passthrough = optional_mapping(city_selection.get("passthrough"))
    trip_type = text(
        first_present(passthrough, "trip_duration", city_input.get("trip_type", "3d2n")),
        "trip_type",
    )
    return {
        "city_selection_result": city_selection,
        "selected_city": selected_city_payload,
        "city_id": selected_city_payload.get("city_id", selected_city_payload.get("destination_id", "")),
        "ddb_pk": selected_city_payload.get("ddb_pk", city_input.get("ddb_pk", "")),
        "seeds": (
            *mapping_sequence(city_selection.get("seeds")),
            *festival_seed_refs(state, selected_city_payload),
        ),
        "raw_query": city_input.get("cleaned_raw_query", city_input.get("raw_query", "")),
        "soft_query": city_input.get("soft_preference_query", ""),
        "active_themes": string_tuple(
            first_present(passthrough, "active_themes", city_input.get("active_required_themes", ())),
        ),
        "theme_weights": first_present(passthrough, "theme_weights", city_input.get("theme_weights")),
        "trip_type": trip_type,
        "transport_pref": text(
            first_present(passthrough, "transport_pref", city_input.get("transport_pref", "unknown")),
            "transport_pref",
        ),
        "min_count": trip_min_place_target(trip_type),
        "target_count": trip_place_target(trip_type),
    }


def runtime_tools(state: Mapping[str, object]) -> PlannerRuntimeTools | None:
    return runtime_tools_from_value(planner_scratch(state).get("runtime"))


def travel_time_provider(state: Mapping[str, object]) -> TravelTimeProvider:
    return travel_time_provider_from_value(planner_scratch(state).get("travel_time_provider"))


def fallback_places(
    state: Mapping[str, object],
) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    city_select = optional_mapping(state.get("city_select"))
    scoring_audit = optional_mapping(city_select.get("scoring_audit")) if city_select else None
    if scoring_audit is None:
        return (), ()
    return (
        mapping_sequence(scoring_audit.get("recommended_places")),
        mapping_sequence(scoring_audit.get("reserve_places")),
    )


def selected_city(state: Mapping[str, object]) -> Mapping[str, object]:
    return mapping(city_selection_result(state).get("selected_city"), "selected_city")


def city_selection_result(state: Mapping[str, object]) -> Mapping[str, object]:
    city_select = optional_mapping(state.get("city_select"))
    if city_select is None:
        raise SchemaValidationError("city_select must be present before planner")
    return mapping(city_select.get("city_selection_result"), "city_select.city_selection_result")


def planner_city_input(state: Mapping[str, object]) -> Mapping[str, object]:
    intent = optional_mapping(state.get("intent"))
    if intent is None:
        return {}
    city_input = intent.get("city_select_input")
    return city_input if isinstance(city_input, Mapping) else {}


def candidate_payloads(
    candidates: Sequence[object],
    *,
    similarity_key: str,
) -> tuple[Mapping[str, object], ...]:
    payloads: list[Mapping[str, object]] = []
    for candidate in candidates:
        payload = candidate_payload(candidate)
        distance = payload.get("distance")
        if isinstance(distance, (int, float)) and not isinstance(distance, bool):
            similarity = max(0.0, 1.0 - float(distance))
            payload = {
                **payload,
                similarity_key: similarity,
                "score_audit": {"score_components": {similarity_key: similarity}},
            }
        payloads.append(payload)
    return tuple(payloads)


def candidate_payload(candidate: object) -> Mapping[str, object]:
    if isinstance(candidate, Mapping):
        return candidate
    to_dict = getattr(candidate, "to_dict", None)
    if callable(to_dict):
        return mapping(to_dict(), "candidate.to_dict")
    raise SchemaValidationError("candidate must be a mapping or expose to_dict")


def mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(mapping(item, "mapping sequence item") for item in value)


def mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return value


def optional_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (text(value, "theme"),)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text(item, "theme") for item in value)


def theme_weights(value: object) -> Mapping[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        str(key): float(weight)
        for key, weight in value.items()
        if isinstance(weight, (int, float)) and not isinstance(weight, bool)
    }


def first_present(mapping_value: Mapping[str, object] | None, key: str, default: object) -> object:
    if mapping_value is not None and key in mapping_value:
        return mapping_value[key]
    return default


def top_k(target_count: object) -> int:
    return max(int_value(target_count, "target_count") * 3, 12)


def text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def int_value(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    return value


def place_id(place: Mapping[str, object]) -> str:
    value = place.get("place_id", place.get("placeId"))
    return text(value, "place_id")


def float_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)
