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
    FestivalVerification,
    PlannerOutput,
    SchemaValidationError,
)
from lovv_agent.tools.links import (
    FOOD_SEARCH_LINK_TYPE,
    GOURMET_THEME_LABEL,
    build_food_search_link,
)
from lovv_agent.tools.validation import validate_planner_output

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
    festival_items = _festival_overlay_items(
        package,
        festival_verifications=festival_verifications,
        include_festivals=include_festivals,
    )
    if festival_items:
        itinerary = _apply_festival_overlay(itinerary, festival_items)

    external_links: dict[str, Any] = {}
    user_notice = []
    if _requires_gourmet_link(package):
        external_links[FOOD_SEARCH_LINK_TYPE] = build_food_search_link(
            city_name_ko=package.selected_city.city_name_ko,
            country=package.selected_city.country,
        )
        itinerary = (*itinerary, _meal_placeholder_item(package))
        user_notice.append(
            "미식·노포 테마는 식당 후보를 생성하지 않고 선택 도시 음식점 검색 링크로 안내합니다.",
        )
    if package.status == "insufficient_candidates":
        user_notice.append("조건에 맞는 후보 수가 적어 가능한 범위에서 축소 일정을 구성했습니다.")
    skipped_festivals = _skipped_festival_count(
        festival_verifications,
        include_festivals=include_festivals,
    )
    if skipped_festivals:
        user_notice.append("확정되지 않았거나 일정에 맞지 않는 축제 후보는 일정에 배치하지 않았습니다.")

    validation_result = validate_planner_output(
        itinerary,
        package=package,
        festival_verifications=festival_verifications,
    )
    validation_result.update(
        {
            "planner_status_gate": package.status,
            "include_festivals": include_festivals,
            "festival_verification_count": len(tuple(festival_verifications)),
            "festival_placed_count": len(festival_items),
            "festival_skipped_count": skipped_festivals,
            "food_search_link_required": FOOD_SEARCH_LINK_TYPE in external_links,
        },
    )

    return PlannerOutput(
        itinerary=itinerary,
        recommendation_reasons=(
            f"{package.selected_city.city_name_ko}의 검증된 후보지를 중심으로 일정을 구성했습니다.",
        ),
        itinerary_flow_reason="tripType별 기본 시간대 템플릿에 후보지를 순서대로 배치했습니다.",
        external_links=external_links,
        confidence=0.72 if package.status == "ok" else 0.5,
        user_notice=tuple(user_notice),
        validation_result=validation_result,
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


def _festival_overlay_items(
    package: CandidateEvidencePackage,
    *,
    festival_verifications: Sequence[Any],
    include_festivals: bool,
) -> tuple[dict[str, Any], ...]:
    """Return placeable verified festivals from the selected city only."""

    if not include_festivals:
        return ()
    selected_festival_ids = {
        str(candidate["festival_id"])
        for candidate in package.selected_festival_candidates
        if isinstance(candidate.get("festival_id"), str)
    }
    if not selected_festival_ids:
        return ()
    items: list[dict[str, Any]] = []
    for verification in _festival_verification_tuple(festival_verifications):
        if verification.festival_id not in selected_festival_ids:
            continue
        if (
            verification.date_status != "confirmed"
            or not verification.is_applicable_to_trip
            or verification.planner_policy != "placeable"
        ):
            continue
        items.append(
            {
                "day": 1,
                "slot": "afternoon_festival",
                "item_type": "festival",
                "festivalId": verification.festival_id,
                "title": verification.name,
                "source": "festival_verifier",
                "date_status": verification.date_status,
                "start_date": verification.start_date,
                "end_date": verification.end_date,
            },
        )
    return tuple(items)


def _apply_festival_overlay(
    itinerary: Sequence[dict[str, Any]],
    festival_items: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Insert verified festivals after the first attraction baseline item."""

    if not festival_items:
        return tuple(itinerary)
    if not itinerary:
        return tuple(festival_items)
    return tuple((itinerary[0], *festival_items, *itinerary[1:]))


def _requires_gourmet_link(package: CandidateEvidencePackage) -> bool:
    """Return whether Planner must provide the selected-city food CTA."""

    external_themes = package.coverage_audit.get("external_link_themes", ())
    if isinstance(external_themes, str):
        return external_themes == GOURMET_THEME_LABEL
    if not isinstance(external_themes, Sequence):
        return False
    return GOURMET_THEME_LABEL in {str(theme) for theme in external_themes}


def _meal_placeholder_item(package: CandidateEvidencePackage) -> dict[str, Any]:
    """Build a public-safe meal choice placeholder for gourmet requests."""

    if package.selected_city is None:
        raise SchemaValidationError("selected_city is required for meal placeholder")
    return {
        "day": 1,
        "slot": "meal_choice",
        "item_type": "meal_placeholder",
        "placeId": None,
        "title": "선택 도시에서 식사 장소를 자유롭게 선택하세요.",
        "city_id": package.selected_city.city_id,
        "city_name_ko": package.selected_city.city_name_ko,
        "source": "placeholder",
        "linkRef": FOOD_SEARCH_LINK_TYPE,
    }


def _skipped_festival_count(
    festival_verifications: Sequence[Any],
    *,
    include_festivals: bool,
) -> int:
    """Count festival verifications that Planner must not place."""

    if not include_festivals:
        return 0
    verifications = _festival_verification_tuple(festival_verifications)
    return sum(
        1
        for verification in verifications
        if not (
            verification.date_status == "confirmed"
            and verification.is_applicable_to_trip
            and verification.planner_policy == "placeable"
        )
    )


def _festival_verification_tuple(
    festival_verifications: Sequence[Any],
) -> tuple[FestivalVerification, ...]:
    """Normalize Festival Verifier outputs for Planner policy checks."""

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


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Copy a mapping payload."""

    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return dict(value)


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
