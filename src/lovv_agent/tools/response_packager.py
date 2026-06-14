"""Deterministic public response packager.

Response Packager converts Planner internals into the MVP
``/recommendations`` response shape. It does not call an LLM, change selected
evidence, or expose internal audits such as Candidate Evidence packages,
reason-claim candidates, retrieval payloads, or explanation audit refs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    FestivalVerification,
    PlannerOutput,
    SchemaValidationError,
    SelectedCity,
)
from lovv_agent.state import RequestState, UnifiedAgentState

NODE_NAME = "response_packager"

RESPONSIBILITY = "Package safe user-facing recommendation responses."

OUT_OF_SCOPE = (
    "recommendation_reasoning_changes",
    "internal_payload_exposure",
)

DEFAULT_TTL_MINUTES = 30


def package_state_response(state: UnifiedAgentState) -> dict[str, Any]:
    """Package the current graph state into a public response payload."""

    if not isinstance(state, UnifiedAgentState):
        raise SchemaValidationError("state must be a UnifiedAgentState")

    package = state.evidence.candidate_evidence_package
    selected_city = package.selected_city if package is not None else None
    return package_recommendation_response(
        planner_output=state.planning.planner_output,
        request=state.request,
        selected_city=selected_city,
        festival_verifications=state.festival.festival_verifications,
        unsupported_conditions=state.intent.unsupported_conditions,
        recommendation_id=state.request.request_id,
    )


def package_recommendation_response(
    *,
    planner_output: PlannerOutput | Mapping[str, Any] | None,
    request: RequestState | Mapping[str, Any],
    selected_city: SelectedCity | Mapping[str, Any] | None,
    festival_verifications: Sequence[Any] = (),
    unsupported_conditions: Sequence[str] = (),
    recommendation_id: str | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Build the safe MVP recommendation response shape."""

    request_payload = _request_payload(request)
    planner = _coerce_planner_output(planner_output)
    city = _coerce_selected_city(selected_city)
    return {
        "recommendationId": recommendation_id or request_payload["request_id"],
        "expiresAt": expires_at or _default_expires_at(),
        "destination": _destination_payload(city, request_payload),
        "itinerary": _itinerary_payload(planner, request_payload),
        "explainability": _explainability_payload(
            planner,
            request_payload,
            unsupported_conditions=unsupported_conditions,
        ),
        "festivalDateVerifications": _festival_date_verification_payloads(
            festival_verifications,
        ),
        "links": _links_payload(planner),
    }


def _destination_payload(
    selected_city: SelectedCity | None,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Map selected city summary into public destination fields."""

    if selected_city is None:
        return {
            "destinationId": request.get("destination_id"),
            "name": None,
            "country": request["country"],
            "region": None,
        }
    return {
        "destinationId": selected_city.city_id,
        "name": selected_city.city_name_ko,
        "country": selected_city.country,
        "region": None,
    }


def _itinerary_payload(
    planner: PlannerOutput | None,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Group Planner items into public itinerary days."""

    if planner is None:
        return {"tripType": request["trip_type"], "days": []}
    days: dict[int, list[dict[str, Any]]] = {}
    for sort_order, item in enumerate(planner.itinerary, start=1):
        day = int(item.get("day", 1) or 1)
        days.setdefault(day, []).append(_itinerary_item_payload(item, sort_order))
    return {
        "tripType": request["trip_type"],
        "days": [
            {"day": day, "items": items}
            for day, items in sorted(days.items(), key=lambda pair: pair[0])
        ],
    }


def _itinerary_item_payload(item: Mapping[str, Any], sort_order: int) -> dict[str, Any]:
    """Map one internal itinerary item to public-safe item fields."""

    content_id = item.get("placeId") or item.get("festivalId")
    return {
        "itemId": f"item-{sort_order}",
        "contentId": content_id,
        "timeOfDay": item.get("slot"),
        "sortOrder": sort_order,
        "title": item.get("title"),
        "body": _item_body(item),
        "reason": _item_reason(item),
        "moveMinutes": _item_number(item, "moveMinutes", "move_minutes"),
        "latitude": _item_number(item, "latitude", "lat"),
        "longitude": _item_number(item, "longitude", "lng", "lon"),
    }


def _item_number(item: Mapping[str, Any], *field_names: str) -> float | int | None:
    """Read a numeric itinerary field from item or enriched details."""

    value = _first_optional_number(item, *field_names)
    if value is not None:
        return value
    details = item.get("details")
    if isinstance(details, Mapping):
        return _first_optional_number(details, *field_names)
    return None


def _first_optional_number(
    item: Mapping[str, Any],
    *field_names: str,
) -> float | int | None:
    """Return the first numeric field value from a mapping."""

    for field_name in field_names:
        value = item.get(field_name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _item_body(item: Mapping[str, Any]) -> str | None:
    """Return a short public body from grounded details when present."""

    details = item.get("details")
    if isinstance(details, Mapping):
        overview = details.get("overview") or details.get("overview_ko")
        if isinstance(overview, str) and overview.strip():
            return overview.strip()
    if item.get("item_type") == "festival":
        start_date = item.get("start_date")
        end_date = item.get("end_date")
        if start_date and end_date:
            return f"{start_date}부터 {end_date}까지 열리는 확정 축제입니다."
    if item.get("item_type") == "meal_placeholder":
        return "선택 도시의 음식점 검색 링크에서 식사 장소를 확인하세요."
    return None


def _item_reason(item: Mapping[str, Any]) -> str | None:
    """Return a safe public reason per itinerary item."""

    item_type = item.get("item_type")
    if item_type == "attraction":
        return "추천 후보로 검증된 관광지입니다."
    if item_type == "festival":
        return "Festival Verifier에서 일정 배치 가능으로 확인한 축제입니다."
    if item_type == "meal_placeholder":
        return "미식 테마는 식당명을 생성하지 않고 검색 링크로 안내합니다."
    return None


def _explainability_payload(
    planner: PlannerOutput | None,
    request: Mapping[str, Any],
    *,
    unsupported_conditions: Sequence[str],
) -> dict[str, Any]:
    """Build public explainability without internal audit refs."""

    if planner is None:
        return {
            "matchedConditions": _matched_conditions(request),
            "unsupportedConditions": _string_list(unsupported_conditions),
            "recommendationReasons": (),
            "itineraryFlowReason": "",
            "confidence": 0.0,
            "userNotice": "",
        }
    return {
        "matchedConditions": _matched_conditions(request),
        "unsupportedConditions": _string_list(unsupported_conditions),
        "recommendationReasons": planner.recommendation_reasons,
        "itineraryFlowReason": planner.itinerary_flow_reason,
        "confidence": planner.confidence,
        "userNotice": " ".join(planner.user_notice),
    }


def _festival_date_verification_payloads(
    festival_verifications: Sequence[Any],
) -> tuple[dict[str, Any], ...]:
    """Expose safe festival verification fields only."""

    return tuple(
        {
            "festivalId": verification.festival_id,
            "dateStatus": verification.date_status,
            "startDate": verification.start_date,
            "endDate": verification.end_date,
            "sourceUrl": None,
            "confidence": verification.confidence,
        }
        for verification in _festival_verification_tuple(festival_verifications)
    )


def _links_payload(planner: PlannerOutput | None) -> dict[str, Any]:
    """Map Planner external links into public response links."""

    if planner is None:
        return {}
    links: dict[str, Any] = {}
    for key, value in planner.external_links.items():
        if isinstance(value, Mapping) and isinstance(value.get("url"), str):
            links[key] = value["url"]
        elif isinstance(value, str):
            links[key] = value
    return links


def _matched_conditions(request: Mapping[str, Any]) -> tuple[str, ...]:
    """Return public matched request conditions."""

    themes = tuple(str(theme) for theme in request.get("themes", ()))
    return (*themes, f"travelMonth:{request['travel_month']}")


def _coerce_planner_output(
    planner_output: PlannerOutput | Mapping[str, Any] | None,
) -> PlannerOutput | None:
    """Normalize Planner output for packaging."""

    if planner_output is None:
        return None
    if isinstance(planner_output, PlannerOutput):
        return planner_output
    if isinstance(planner_output, Mapping):
        return PlannerOutput.from_mapping(planner_output)
    raise SchemaValidationError("planner_output must be PlannerOutput, mapping, or None")


def _coerce_selected_city(
    selected_city: SelectedCity | Mapping[str, Any] | None,
) -> SelectedCity | None:
    """Normalize selected city for packaging."""

    if selected_city is None:
        return None
    if isinstance(selected_city, SelectedCity):
        return selected_city
    if isinstance(selected_city, Mapping):
        return SelectedCity.from_mapping(selected_city)
    raise SchemaValidationError("selected_city must be SelectedCity, mapping, or None")


def _festival_verification_tuple(
    festival_verifications: Sequence[Any],
) -> tuple[FestivalVerification, ...]:
    """Normalize Festival Verifier outputs."""

    if not isinstance(festival_verifications, Sequence) or isinstance(
        festival_verifications,
        (str, bytes),
    ):
        raise SchemaValidationError("festival_verifications must be a sequence")
    return tuple(
        item
        if isinstance(item, FestivalVerification)
        else FestivalVerification.from_mapping(_mapping(item, "festival_verification"))
        for item in festival_verifications
    )


def _request_payload(request: RequestState | Mapping[str, Any]) -> dict[str, Any]:
    """Normalize request fields used in the public response."""

    if isinstance(request, RequestState):
        return {
            "request_id": request.request_id,
            "country": request.country,
            "travel_month": request.travel_month,
            "trip_type": request.trip_type,
            "destination_id": request.destination_id,
            "themes": request.themes,
        }
    if isinstance(request, Mapping):
        return {
            "request_id": _first_present(request, "request_id", "requestId"),
            "country": _first_present(request, "country"),
            "travel_month": _first_present(request, "travel_month", "travelMonth"),
            "trip_type": _first_present(request, "trip_type", "tripType"),
            "destination_id": request.get("destination_id", request.get("destinationId")),
            "themes": tuple(request.get("themes", ())),
        }
    raise SchemaValidationError("request must be RequestState or mapping")


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Return the first present mapping value."""

    for key in keys:
        if key in mapping:
            return mapping[key]
    raise SchemaValidationError(f"missing required request field: {keys[0]}")


def _string_list(values: Sequence[str]) -> tuple[str, ...]:
    """Normalize public string sequences."""

    if isinstance(values, str) or not isinstance(values, Sequence):
        raise SchemaValidationError("values must be a string sequence")
    return tuple(str(value) for value in values)


def _default_expires_at() -> str:
    """Return the default temporary recommendation expiry timestamp."""

    return (
        datetime.now(UTC)
        + timedelta(minutes=DEFAULT_TTL_MINUTES)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Copy one mapping payload."""

    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return dict(value)


__all__ = [
    "DEFAULT_TTL_MINUTES",
    "NODE_NAME",
    "OUT_OF_SCOPE",
    "RESPONSIBILITY",
    "package_recommendation_response",
    "package_state_response",
]
