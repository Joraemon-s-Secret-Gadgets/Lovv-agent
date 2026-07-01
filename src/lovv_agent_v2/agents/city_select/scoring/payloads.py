from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.models.schemas import SchemaValidationError, SelectedCity
from lovv_agent_v2.agents.city_select.scoring.service import PlaceScoreResult
from lovv_agent_v2.agents.city_select.domain.contracts import CitySelectContext
from lovv_agent_v2.agents.city_select.scoring.ranking import _candidate_attr, _city_name_from_group
def _lightweight_selected_places(
    selected_payloads: Sequence[Mapping[str, Any]],
    scored_places: Sequence[PlaceScoreResult],
) -> tuple[dict[str, Any], ...]:
    """Return selected candidates without raw retrieval payloads or details."""

    scored_by_id = {place.place_id: place for place in scored_places}
    result: list[dict[str, Any]] = []
    for payload in selected_payloads:
        place_id = _mapping_text(payload, "place_id")
        scored = scored_by_id[place_id]
        result.append(
            {
                "place_id": scored.place_id,
                "title": scored.title,
                "city_id": scored.city_id,
                "city_name_ko": _candidate_attr(scored.place, "city_name_ko"),
                "theme_tags": list(scored.theme_tags),
                "latitude": scored.latitude,
                "longitude": scored.longitude,
                "ddb_pk": _candidate_attr(scored.place, "ddb_pk"),
                "ddb_sk": _candidate_attr(scored.place, "ddb_sk"),
                "attraction_subtype_code": _candidate_attr(scored.place, "attraction_subtype_code"),
                "slot_role": payload.get("slot_role"),
                "assigned_theme": payload.get("assigned_theme"),
                "score_audit": {
                    "place_score": scored.place_score,
                    "score_components": dict(scored.score_components),
                },
            },
        )
    return tuple(result)



def _select_city_rank_index(
    city_rankings: Sequence[Mapping[str, Any]],
    *,
    selection_by_city: Mapping[str, Any],
    required_place_count: int,
    fixed_city_id: str | None,
) -> int:
    """Select the highest-ranked city. In V2, capacity-based demotion is removed, so it always returns 0."""

    return 0


def _mapping_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _ddb_pk_from_group(city_id: str, scored_places: Sequence[PlaceScoreResult]) -> str:
    for place in scored_places:
        ddb_pk = _candidate_attr(place.place, "ddb_pk")
        if ddb_pk is not None:
            return str(ddb_pk).strip().upper()
    return city_id.strip().upper()


def _representative_seed_payload(place: PlaceScoreResult) -> dict[str, Any]:
    theme = place.theme_tags[0] if place.theme_tags else None
    return {
        "place_id": place.place_id,
        "ddb_sk": _candidate_attr(place.place, "ddb_sk"),
        "title": place.title,
        "theme": theme,
        "sim": place.score_components.get("raw_similarity", 0.0),
        "lat": place.latitude,
        "lon": place.longitude,
        "attraction_subtype_code": _candidate_attr(place.place, "attraction_subtype_code"),
    }

def _seed_payload(place: PlaceScoreResult, theme: str) -> dict[str, Any]:
    return {
        "theme": theme,
        "place_id": place.place_id,
        "ddb_sk": _candidate_attr(place.place, "ddb_sk"),
        "title": place.title,
        "sim": place.score_components.get("raw_similarity", 0.0),
        "lat": place.latitude,
        "lon": place.longitude,
        "attraction_subtype_code": _candidate_attr(place.place, "attraction_subtype_code"),
        "must_include": True,
    }


def _seed_payloads(
    scored_places: Sequence[PlaceScoreResult],
    themes: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    seeds: list[dict[str, Any]] = []
    for theme in themes:
        matching = [place for place in scored_places if theme in place.theme_tags]
        if not matching:
            continue
        best = max(
            matching,
            key=lambda place: place.score_components.get("raw_similarity", 0.0),
        )
        seeds.append(_seed_payload(best, theme))
    return tuple(seeds)


def _headline_seed(seeds: Sequence[Mapping[str, Any]]) -> str | None:
    if not seeds:
        return None
    seed = max(seeds, key=lambda item: float(item.get("sim", 0.0)))
    place_id = seed.get("place_id")
    return place_id if isinstance(place_id, str) else None


def _theme_evidence_payload(
    scored_places: Sequence[PlaceScoreResult],
    themes: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    evidence: list[dict[str, Any]] = []
    for theme in themes:
        matching = [place for place in scored_places if theme in place.theme_tags]
        if not matching:
            continue
        best = max(
            matching,
            key=lambda place: place.score_components.get("raw_similarity", 0.0),
        )
        similarity = best.score_components.get("raw_similarity", 0.0)
        evidence.append(
            {
                "theme": theme,
                "best_place": {
                    "place_id": best.place_id,
                    "title": best.title,
                    "sim": similarity,
                },
                "coverage_strength": similarity,
            },
        )
    return tuple(evidence)


def _alternative_city_payload(
    city_rankings: Sequence[Mapping[str, Any]],
    scored_groups: Mapping[str, Sequence[PlaceScoreResult]],
    *,
    selected_city_id: str,
) -> dict[str, Any] | None:
    if len(city_rankings) < 2:
        return None
    selected_score = float(city_rankings[0]["city_score"])
    for ranking in city_rankings:
        city_id = str(ranking["city_id"])
        if city_id == selected_city_id:
            continue
        scored_places = scored_groups[city_id]
        return {
            "city_id": city_id,
            "ddb_pk": _ddb_pk_from_group(city_id, scored_places),
            "city_name_ko": ranking.get("city_name_ko"),
            "score_delta": round(selected_score - float(ranking["city_score"]), 4),
        }
    return None


def _passthrough_payload(context: CitySelectContext) -> dict[str, Any]:
    location = context.candidate_input.user_location
    user_location = None
    if location is not None:
        user_location = {
            "latitude": location.latitude,
            "longitude": location.longitude,
        }
    return {
        "active_themes": list(context.theme_split.active_required_themes),
        "theme_weights": dict(context.candidate_input.theme_weights or {}),
        "trip_duration": context.candidate_input.trip_type,
        "congestion_pref": context.candidate_input.congestion_pref,
        "transport_pref": context.candidate_input.transport_pref,
        "soft_query": context.candidate_input.soft_preference_query,
        "user_location": user_location,
        "session_avoid": [],
    }


def _selection_reason_codes(
    *,
    context: CitySelectContext,
    score_breakdown: Mapping[str, float],
    alternative_city: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    codes: list[str] = []
    if context.candidate_input.destination_id is not None:
        codes.append("anchored")
    if score_breakdown.get("weighted_theme_coverage", 0.0) > 0.0:
        codes.append("theme_match")
    if score_breakdown.get("distance_penalty", 0.0) > 0.0:
        codes.append("proximity")
    if context.candidate_input.congestion_pref in {"quiet", "neutral"}:
        codes.append("small_city_lean")
    if alternative_city is None:
        codes.append("no_alternative")
    return tuple(dict.fromkeys(codes))



def _annotate_city_rankings(
    city_rankings: Sequence[Mapping[str, Any]],
    *,
    selection_by_city: Mapping[str, Any],
    required_place_count: int,
    selected_city_id: str,
) -> tuple[dict[str, Any], ...]:
    """Attach itinerary-capacity audit fields to each city ranking."""

    annotated: list[dict[str, Any]] = []
    for ranking in city_rankings:
        city_id = str(ranking["city_id"])
        selected = selection_by_city[city_id]
        available_place_count = len(selected.primary)
        payload = dict(ranking)
        payload.update(
            {
                "available_place_count": available_place_count,
                "required_place_count": required_place_count,
                "itinerary_sufficient": available_place_count >= required_place_count,
                "selected": city_id == selected_city_id,
            },
        )
        annotated.append(payload)
    return tuple(annotated)



def _itinerary_coverage_audit(
    coverage_audit: Mapping[str, Any],
    *,
    required_place_count: int,
    available_place_count: int,
) -> dict[str, Any]:
    """Extend quota audit with primary-only Planner capacity."""

    result = dict(coverage_audit)
    result.update(
        {
            "itinerary_required_place_count": required_place_count,
            "available_place_count": available_place_count,
            "itinerary_sufficiency": (
                "sufficient"
                if available_place_count >= required_place_count
                else "insufficient"
            ),
        },
    )
    return result



def _status_from_selection(
    *,
    required_place_count: int,
    available_place_count: int,
) -> str:
    """Return package status from Planner-facing itinerary capacity."""

    if available_place_count < required_place_count:
        return "insufficient_candidates"
    return "ok"
