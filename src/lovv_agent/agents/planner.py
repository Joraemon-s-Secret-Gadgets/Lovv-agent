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

from lovv_agent.adapters.bedrock_converse import RuntimeInvoker
from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    ExplanationReasonRef,
    FestivalVerification,
    PlannerExplanationAudit,
    PlannerOutput,
    SchemaValidationError,
)
from lovv_agent.tools.destination_search import AttractionCandidate
from lovv_agent.tools.links import (
    FOOD_SEARCH_LINK_TYPE,
    GOURMET_THEME_LABEL,
    build_default_city_links,
)
from lovv_agent.tools.explanation_composer import compose_planner_copy_explanation
from lovv_agent.tools.validation import validate_planner_output

NODE_NAME = "planner_agent"

RESPONSIBILITY = "Create safe itinerary internals from grounded evidence."

OUT_OF_SCOPE = (
    "new_place_search",
    "ungrounded_restaurant_generation",
    "festival_date_confirmation",
)

EXPLANATION_INTERNAL_TERMS = (
    "top k",
    "top_k",
    "topk",
    "점수",
    "스코어",
    "랭킹 공식",
    "ranking formula",
)

DEFAULT_PLANNER_SCHEMA_RETRY_LIMIT = 2

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

    dynamo_lookup: Any | None = None
    explanation_runtime: RuntimeInvoker | None = None
    schema_retry_limit: int = DEFAULT_PLANNER_SCHEMA_RETRY_LIMIT

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
            dynamo_lookup=self.dynamo_lookup,
            explanation_runtime=self.explanation_runtime,
            schema_retry_limit=self.schema_retry_limit,
        )


def build_planner_output(
    package: CandidateEvidencePackage,
    *,
    trip_type: str,
    include_festivals: bool = False,
    festival_verifications: Sequence[Any] = (),
    dynamo_lookup: Any | None = None,
    explanation_runtime: RuntimeInvoker | None = None,
    schema_retry_limit: int = DEFAULT_PLANNER_SCHEMA_RETRY_LIMIT,
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

    external_links: dict[str, Any] = build_default_city_links(
        city_name_ko=package.selected_city.city_name_ko,
        country=package.selected_city.country,
    )
    user_notice = []
    if _requires_gourmet_link(package):
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

    detail_warnings: tuple[Mapping[str, Any], ...] = ()
    if dynamo_lookup is not None:
        itinerary, detail_warnings = _enrich_final_itinerary_details(
            itinerary,
            dynamo_lookup=dynamo_lookup,
        )

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
            "detail_enrichment_warning_count": len(detail_warnings),
        },
    )
    if detail_warnings:
        validation_result["detail_enrichment_warnings"] = [dict(warning) for warning in detail_warnings]
    explanation = _build_grounded_explanation(
        package,
        itinerary=itinerary,
        validation_result=validation_result,
    )
    if explanation_runtime is not None:
        composed = compose_planner_copy_explanation(
            package,
            itinerary=itinerary,
            validation_result=validation_result,
            runtime=explanation_runtime,
            retry_limit=schema_retry_limit,
            fallback_recommendation_reasons=explanation["recommendation_reasons"],
            fallback_itinerary_flow_reason=explanation["itinerary_flow_reason"],
            fallback_explanation_audit=explanation["explanation_audit"],
        )
        itinerary = composed.itinerary
        explanation = {
            "recommendation_reasons": composed.recommendation_reasons,
            "itinerary_flow_reason": composed.itinerary_flow_reason,
            "explanation_audit": composed.explanation_audit,
        }
        validation_result["planner_copy_generation_used_llm"] = composed.used_llm

    return PlannerOutput(
        itinerary=itinerary,
        recommendation_reasons=explanation["recommendation_reasons"],
        itinerary_flow_reason=explanation["itinerary_flow_reason"],
        external_links=external_links,
        confidence=0.72 if package.status == "ok" else 0.5,
        user_notice=tuple(user_notice),
        validation_result=validation_result,
        alternative_itinerary=(),
        explanation_audit=explanation["explanation_audit"],
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
        "latitude": place.get("latitude"),
        "longitude": place.get("longitude"),
        "moveMinutes": place.get("moveMinutes") or place.get("move_minutes"),
        "ddb_pk": place.get("ddb_pk"),
        "ddb_sk": place.get("ddb_sk"),
    }


def _enrich_final_itinerary_details(
    itinerary: Sequence[Mapping[str, Any]],
    *,
    dynamo_lookup: Any,
) -> tuple[tuple[dict[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    """Attach DynamoDB details to final placed attraction items only."""

    attraction_indexes: list[int] = []
    candidates: list[AttractionCandidate] = []
    for index, item in enumerate(itinerary):
        if item.get("item_type") != "attraction":
            continue
        attraction_indexes.append(index)
        candidates.append(_itinerary_item_to_attraction_candidate(item))

    if not candidates:
        return tuple(dict(item) for item in itinerary), ()

    enrichment = dynamo_lookup.enrich_final_places(tuple(candidates))
    enriched_places = tuple(enrichment.places)
    updated = [dict(item) for item in itinerary]
    for index, enriched_place in zip(attraction_indexes, enriched_places, strict=False):
        updated[index] = _apply_enriched_place(updated[index], enriched_place)

    warnings = tuple(
        warning.to_dict() if hasattr(warning, "to_dict") else dict(warning)
        for warning in getattr(enrichment, "warnings", ())
    )
    return tuple(updated), warnings


def _itinerary_item_to_attraction_candidate(item: Mapping[str, Any]) -> AttractionCandidate:
    """Convert a final attraction item into the Dynamo enrichment candidate shape."""

    place_id = _required_text(item.get("placeId"), "placeId")
    title = _required_text(item.get("title"), "title")
    city_id = _required_text(item.get("city_id"), "city_id")
    return AttractionCandidate(
        key=_optional_text(item.get("key"), "key") or place_id,
        place_id=place_id,
        distance=0.0,
        entity_type="attraction",
        city_id=city_id,
        city_name_ko=_optional_text(item.get("city_name_ko"), "city_name_ko"),
        title=title,
        theme_tags=tuple(str(theme) for theme in item.get("theme_tags", ())),
        latitude=_optional_number(item.get("latitude")),
        longitude=_optional_number(item.get("longitude")),
        ddb_pk=_optional_text(item.get("ddb_pk"), "ddb_pk"),
        ddb_sk=_optional_text(item.get("ddb_sk"), "ddb_sk"),
        metadata={
            "source": item.get("source"),
            "slot": item.get("slot"),
            "day": item.get("day"),
        },
        details=item.get("details") if isinstance(item.get("details"), dict) else None,
    )


def _apply_enriched_place(
    item: Mapping[str, Any],
    enriched_place: AttractionCandidate,
) -> dict[str, Any]:
    """Copy Dynamo-enriched detail fields back to a final itinerary item."""

    updated = dict(item)
    updated["details"] = enriched_place.details
    if enriched_place.latitude is not None:
        updated["latitude"] = enriched_place.latitude
    elif isinstance(enriched_place.details, Mapping):
        updated["latitude"] = _optional_number(
            enriched_place.details.get("latitude")
            or enriched_place.details.get("lat"),
        )
    if enriched_place.longitude is not None:
        updated["longitude"] = enriched_place.longitude
    elif isinstance(enriched_place.details, Mapping):
        updated["longitude"] = _optional_number(
            enriched_place.details.get("longitude")
            or enriched_place.details.get("lng")
            or enriched_place.details.get("lon"),
        )
    return updated


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


def _build_grounded_explanation(
    package: CandidateEvidencePackage,
    *,
    itinerary: Sequence[Mapping[str, Any]],
    validation_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Select public reasons from verified claim candidates and placed items."""

    if package.selected_city is None:
        raise SchemaValidationError("selected_city is required for explanation")
    placed_ids = _placed_place_ids(itinerary)
    reasons: list[str] = []
    reason_refs: list[ExplanationReasonRef] = []
    hidden_notes: list[str] = []
    for claim in package.candidate_reason_claims:
        if len(reasons) >= 3:
            break
        if not claim.public_eligible:
            hidden_notes.append(f"skipped_non_public_claim:{claim.claim_id}")
            continue
        if not set(claim.required_place_ids).issubset(placed_ids):
            hidden_notes.append(f"skipped_missing_place_ids:{claim.claim_id}")
            continue
        if _contains_internal_explanation_term(claim.text_ko):
            hidden_notes.append(f"skipped_internal_term:{claim.claim_id}")
            continue

        reason_text = _claim_reason_text(claim.text_ko, claim.required_place_ids, itinerary)
        reason_id = f"recommendationReasons[{len(reasons)}]"
        reasons.append(reason_text)
        reason_refs.append(
            ExplanationReasonRef(
                reason_id=reason_id,
                reason_text=reason_text,
                evidence_refs=claim.evidence_refs,
                reason_codes=(claim.scope,),
            ),
        )

    if not reasons:
        hidden_notes.append("fallback_reason_used:no_public_claims")
        fallback_reason = (
            f"{package.selected_city.city_name_ko}의 최종 배치 후보를 중심으로 "
            "확인 가능한 정보만 사용해 추천했습니다."
        )
        reasons.append(fallback_reason)
        reason_refs.append(
            ExplanationReasonRef(
                reason_id="recommendationReasons[0]",
                reason_text=fallback_reason,
                evidence_refs=("selected_city", "itinerary"),
                reason_codes=("conservative_fallback",),
            ),
        )

    if not _has_overview(itinerary):
        hidden_notes.append("conservative_wording:no_item_overview")

    flow_reason = _itinerary_flow_reason(itinerary, validation_result)
    audit = PlannerExplanationAudit(
        reason_refs=tuple(reason_refs),
        itinerary_flow_refs=_itinerary_flow_refs(itinerary),
        hidden_internal_notes=tuple(hidden_notes),
    )
    return {
        "recommendation_reasons": tuple(reasons),
        "itinerary_flow_reason": flow_reason,
        "explanation_audit": audit,
    }


def _claim_reason_text(
    claim_text: str,
    required_place_ids: Sequence[str],
    itinerary: Sequence[Mapping[str, Any]],
) -> str:
    """Attach one grounded overview snippet when available."""

    overview = _first_required_place_overview(required_place_ids, itinerary)
    if overview is None:
        return claim_text
    return f"{claim_text} 배치된 대표 장소 설명도 '{overview}'로 확인됩니다."


def _first_required_place_overview(
    required_place_ids: Sequence[str],
    itinerary: Sequence[Mapping[str, Any]],
) -> str | None:
    """Return a short overview for a placed required place when present."""

    required = set(required_place_ids)
    if not required:
        return None
    for item in itinerary:
        if item.get("placeId") not in required:
            continue
        details = item.get("details")
        if not isinstance(details, Mapping):
            continue
        overview = details.get("overview") or details.get("overview_ko")
        if isinstance(overview, str) and overview.strip():
            return overview.strip()[:80]
    return None


def _itinerary_flow_reason(
    itinerary: Sequence[Mapping[str, Any]],
    validation_result: Mapping[str, Any],
) -> str:
    """Build a concise public flow reason without exposing internal scoring."""

    attraction_count = sum(1 for item in itinerary if item.get("item_type") == "attraction")
    festival_count = int(validation_result.get("festival_placed_count", 0) or 0)
    if festival_count:
        return (
            f"관광지 {attraction_count}곳을 기본 시간대에 먼저 배치하고, "
            "확정된 축제만 중간 일정으로 더했습니다."
        )
    return f"관광지 {attraction_count}곳을 tripType 기본 시간대에 맞춰 간결하게 배치했습니다."


def _itinerary_flow_refs(itinerary: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return internal refs for items that shaped itinerary flow."""

    refs: list[str] = []
    for item in itinerary:
        if item.get("item_type") == "attraction" and isinstance(item.get("placeId"), str):
            refs.append(f"place:{item['placeId']}")
        elif item.get("item_type") == "festival" and isinstance(item.get("festivalId"), str):
            refs.append(f"festival:{item['festivalId']}")
    return tuple(refs)


def _placed_place_ids(itinerary: Sequence[Mapping[str, Any]]) -> set[str]:
    """Collect placed attraction ids."""

    return {
        str(item["placeId"])
        for item in itinerary
        if item.get("item_type") == "attraction" and isinstance(item.get("placeId"), str)
    }


def _has_overview(itinerary: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether any placed item has an overview detail."""

    return any(
        isinstance(item.get("details"), Mapping)
        and isinstance(item["details"].get("overview"), str)
        and item["details"].get("overview", "").strip()
        for item in itinerary
    )


def _contains_internal_explanation_term(text: str) -> bool:
    """Block raw scoring or retrieval mechanics from public explanation text."""

    normalized = text.lower()
    return any(term in normalized for term in EXPLANATION_INTERNAL_TERMS)


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


def _optional_text(value: Any, field_name: str) -> str | None:
    """Validate optional text and normalize blanks to ``None``."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    return normalized or None


def _optional_number(value: Any) -> float | int | None:
    """Return a numeric value from optional item/detail fields."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


__all__ = [
    "NODE_NAME",
    "OUT_OF_SCOPE",
    "RESPONSIBILITY",
    "TRIP_SLOT_TEMPLATES",
    "PlannerAgent",
    "build_planner_output",
]
