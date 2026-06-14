"""Planner Agent helpers.

Planner converts the internal Candidate Evidence Package into itinerary
internals. It does not search for new places, invent restaurants, or verify
festival dates. The first Planner subtask implements status gates and simple
tripType slot templates; later subtasks add festival overlay, food CTA policy,
validation, and grounded explanation generation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    PlannerOutput,
    SchemaValidationError,
)

NODE_NAME = "planner_agent"

RESPONSIBILITY = "Create safe itinerary internals from grounded evidence."

OUT_OF_SCOPE = (
    "new_place_search",
    "ungrounded_restaurant_generation",
    "festival_date_confirmation",
)

TRIP_SLOT_TEMPLATES: dict[str, tuple[tuple[int, str], ...]] = {
    "daytrip": ((1, "morning"), (1, "afternoon"), (1, "evening")),
    "2d1n": (
        (1, "morning"),
        (1, "afternoon"),
        (1, "evening"),
        (2, "morning"),
        (2, "afternoon"),
    ),
    "3d2n": (
        (1, "morning"),
        (1, "afternoon"),
        (1, "evening"),
        (2, "morning"),
        (2, "afternoon"),
        (2, "evening"),
        (3, "morning"),
        (3, "afternoon"),
    ),
    "4d3n": (
        (1, "morning"),
        (1, "afternoon"),
        (1, "evening"),
        (2, "morning"),
        (2, "afternoon"),
        (2, "evening"),
        (3, "morning"),
        (3, "afternoon"),
        (3, "evening"),
        (4, "morning"),
        (4, "afternoon"),
    ),
    "5d4n": (
        (1, "morning"),
        (1, "afternoon"),
        (1, "evening"),
        (2, "morning"),
        (2, "afternoon"),
        (2, "evening"),
        (3, "morning"),
        (3, "afternoon"),
        (3, "evening"),
        (4, "morning"),
        (4, "afternoon"),
        (4, "evening"),
        (5, "morning"),
        (5, "afternoon"),
    ),
}


@dataclass(frozen=True, slots=True)
class PlannerAgent:
    """Build grounded itinerary internals from Candidate Evidence."""

    def plan(
        self,
        candidate_evidence_package: CandidateEvidencePackage | Mapping[str, Any],
        *,
        trip_type: str,
        include_festivals: bool = False,
        festival_verifications: Sequence[Any] = (),
    ) -> PlannerOutput:
        """Create PlannerOutput using status gates and slot templates."""

        package = _coerce_candidate_package(candidate_evidence_package)
        return build_planner_output(
            package,
            trip_type=trip_type,
            include_festivals=include_festivals,
            festival_verifications=festival_verifications,
        )


def build_planner_output(
    package: CandidateEvidencePackage,
    *,
    trip_type: str,
    include_festivals: bool = False,
    festival_verifications: Sequence[Any] = (),
) -> PlannerOutput:
    """Build safe itinerary internals from one Candidate Evidence package."""

    normalized_trip_type = _trip_type(trip_type)
    if package.status in {"no_candidate", "error"}:
        return _blocked_planner_output(package)
    if package.status == "insufficient_candidates" and (
        package.selected_city is None or not package.recommended_places
    ):
        return _blocked_planner_output(package)
    if package.selected_city is None:
        return _blocked_planner_output(package)

    slots = TRIP_SLOT_TEMPLATES[normalized_trip_type]
    itinerary = _build_attraction_itinerary(
        package,
        slots=slots,
        reduced=package.status == "insufficient_candidates",
    )
    if not itinerary:
        return _blocked_planner_output(package)

    user_notice = []
    if package.status == "insufficient_candidates":
        user_notice.append("조건에 맞는 후보 수가 적어 가능한 범위에서 축소 일정을 구성했습니다.")

    return PlannerOutput(
        itinerary=itinerary,
        recommendation_reasons=(
            f"{package.selected_city.city_name_ko}의 검증된 후보지를 중심으로 일정을 구성했습니다.",
        ),
        itinerary_flow_reason="tripType별 기본 시간대 템플릿에 후보지를 순서대로 배치했습니다.",
        external_links={},
        confidence=0.72 if package.status == "ok" else 0.5,
        user_notice=tuple(user_notice),
        validation_result={
            "status": "not_validated",
            "planner_status_gate": package.status,
            "include_festivals": include_festivals,
            "festival_verification_count": len(tuple(festival_verifications)),
        },
        alternative_itinerary=(),
    )


def _build_attraction_itinerary(
    package: CandidateEvidencePackage,
    *,
    slots: Sequence[tuple[int, str]],
    reduced: bool,
) -> tuple[dict[str, Any], ...]:
    """Place grounded attraction candidates into simple tripType slots."""

    places = list(package.recommended_places)
    if not places and package.reserve_places:
        places.extend(package.reserve_places)
    if reduced:
        slots = slots[: max(min(len(places), len(slots)), 1)]
    itinerary: list[dict[str, Any]] = []
    for slot_index, (day, slot_name) in enumerate(slots):
        if slot_index >= len(places):
            break
        place = places[slot_index]
        itinerary.append(_attraction_slot(day=day, slot_name=slot_name, place=place))
    return tuple(itinerary)


def _attraction_slot(*, day: int, slot_name: str, place: Mapping[str, Any]) -> dict[str, Any]:
    """Build one grounded attraction itinerary slot."""

    place_id = _required_text(place.get("place_id"), "place_id")
    title = _required_text(place.get("title"), "title")
    return {
        "day": day,
        "slot": slot_name,
        "item_type": "attraction",
        "placeId": place_id,
        "title": title,
        "city_id": place.get("city_id"),
        "city_name_ko": place.get("city_name_ko"),
        "source": "candidate_evidence",
        "theme_tags": list(place.get("theme_tags", [])),
        "details": place.get("details"),
    }


def _blocked_planner_output(package: CandidateEvidencePackage) -> PlannerOutput:
    """Return a safe non-itinerary PlannerOutput for blocked evidence."""

    reason = (
        "추천 후보를 충분히 확보하지 못해 정상 일정을 생성하지 않았습니다."
        if package.status == "no_candidate"
        else "추천 생성 중 내부 오류가 있어 정상 일정을 생성하지 않았습니다."
    )
    return PlannerOutput(
        itinerary=(),
        recommendation_reasons=(reason,),
        itinerary_flow_reason=reason,
        external_links={},
        confidence=0.0,
        user_notice=(reason,),
        validation_result={
            "status": "blocked",
            "planner_status_gate": package.status,
            "failure_signals": list(package.failure_signals),
        },
        alternative_itinerary=(),
    )


def _coerce_candidate_package(
    package: CandidateEvidencePackage | Mapping[str, Any],
) -> CandidateEvidencePackage:
    """Accept schema or mapping package payloads at Planner boundary."""

    if isinstance(package, CandidateEvidencePackage):
        return package
    if isinstance(package, Mapping):
        return CandidateEvidencePackage.from_mapping(package)
    raise SchemaValidationError("candidate_evidence_package must be a schema or mapping")


def _trip_type(value: str) -> str:
    """Validate supported tripType."""

    normalized = _required_text(value, "trip_type")
    if normalized not in TRIP_SLOT_TEMPLATES:
        raise SchemaValidationError(f"unsupported trip_type: {normalized}")
    return normalized


def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty string."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


__all__ = [
    "NODE_NAME",
    "OUT_OF_SCOPE",
    "RESPONSIBILITY",
    "TRIP_SLOT_TEMPLATES",
    "PlannerAgent",
    "build_planner_output",
]
