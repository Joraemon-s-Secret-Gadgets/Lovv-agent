from __future__ import annotations

from collections.abc import Mapping

from lovv_agent_v2.agents.planner.context import (
    mapping,
    mapping_sequence,
    optional_mapping,
    optional_text,
    text,
)
from lovv_agent_v2.agents.planner.scratch import planner_state_update
from lovv_agent_v2.models.city_identity import load_default_city_identity_map


def should_retry_alternative_city(state: Mapping[str, object]) -> bool:
    planner = optional_mapping(state.get("planner"))
    if planner is None:
        return False
    validation = optional_mapping(planner.get("validation_result"))
    if validation is None or validation.get("planner_status_gate") != "insufficient_candidates":
        return False
    if optional_mapping(planner.get("fallback")) is not None:
        return False
    city_selection = _city_selection(state)
    selected = optional_mapping(city_selection.get("selected_city"))
    return _fallback_city_payload(state, city_selection, selected) is not None


def fallback_to_alternative_city_node(state: Mapping[str, object]) -> dict[str, object]:
    city_select = mapping(state.get("city_select"), "city_select")
    city_selection = dict(_city_selection(state))
    selected = mapping(city_selection.get("selected_city"), "selected_city")
    alternative = mapping(
        _fallback_city_payload(state, city_selection, selected),
        "alternative_city",
    )
    alternative_city_id = text(alternative.get("city_id"), "alternative_city.city_id")
    fallback_scoring_audit = _fallback_scoring_audit(
        city_select,
        alternative_city_id,
    )
    canonical_city_id = _canonical_city_id(alternative_city_id, fallback_scoring_audit)
    selected_city = _alternative_selected_city(selected, alternative, canonical_city_id)
    city_selection["selected_city"] = selected_city
    city_selection["alternative_city"] = {
        "city_id": selected.get("city_id"),
        "city_name_ko": selected.get("city_name_ko"),
        "ddb_pk": selected.get("ddb_pk"),
        "score_delta": alternative.get("score_delta"),
    }
    city_selection["seeds"] = []
    city_selection["headline_seed"] = None
    next_city_select = dict(city_select)
    next_city_select["city_selection_result"] = city_selection
    if fallback_scoring_audit is not None:
        next_city_select["scoring_audit"] = fallback_scoring_audit
    next_city_select["status"] = "retry_alternative_city"
    fallback = {
            "used": True,
            "reason": "primary_city_insufficient_candidates",
            "from_city_id": selected.get("city_id"),
            "to_city_id": selected_city["city_id"],
    }
    return {
        "city_select": next_city_select,
        **planner_state_update(
            state,
            public_updates={"fallback": fallback},
            scratch_updates={"fallback": fallback},
        ),
    }


def _city_selection(state: Mapping[str, object]) -> Mapping[str, object]:
    city_select = mapping(state.get("city_select"), "city_select")
    return mapping(city_select.get("city_selection_result"), "city_select.city_selection_result")


def _fallback_scoring_audit(
    city_select: Mapping[str, object],
    city_id: str,
) -> Mapping[str, object] | None:
    scoring_audit = optional_mapping(city_select.get("scoring_audit"))
    if scoring_audit is None:
        return None
    next_audit = dict(scoring_audit)
    recommended_by_city = optional_mapping(scoring_audit.get("recommended_places_by_city"))
    reserve_by_city = optional_mapping(scoring_audit.get("reserve_places_by_city"))
    recommended = mapping_sequence(recommended_by_city.get(city_id)) if recommended_by_city else ()
    reserve = mapping_sequence(reserve_by_city.get(city_id)) if reserve_by_city else ()
    if recommended:
        next_audit["recommended_places"] = recommended
        next_audit["reserve_places"] = reserve
    return next_audit


def _canonical_city_id(
    fallback_city_id: str,
    scoring_audit: Mapping[str, object] | None,
) -> str:
    if scoring_audit is None:
        return fallback_city_id
    for place in mapping_sequence(scoring_audit.get("recommended_places")):
        city_id = optional_text(place.get("city_id"))
        if city_id is not None and not city_id.startswith("CITY#"):
            return city_id
    return fallback_city_id


def _fallback_city_payload(
    state: Mapping[str, object],
    city_selection: Mapping[str, object],
    selected: Mapping[str, object] | None,
) -> dict[str, object] | None:
    selected_city_id = optional_text(selected.get("city_id")) if selected is not None else None
    explicit = optional_mapping(city_selection.get("alternative_city"))
    if explicit is not None:
        city_id = _alternative_city_id(state, explicit, selected_city_id=selected_city_id)
        if city_id is not None:
            payload = dict(explicit)
            payload["city_id"] = city_id
            for key, value in _city_metadata(state, city_id).items():
                if key not in payload and value is not None:
                    payload[key] = value
            return payload
    return _ranked_alternative_city(state, selected_city_id=selected_city_id)


def _alternative_selected_city(
    selected: Mapping[str, object],
    alternative: Mapping[str, object],
    city_id: str,
) -> dict[str, object]:
    reason_codes = (*_string_tuple(selected.get("selection_reason_code")), "planner_auto_alternative_fallback")
    return {
        "city_id": city_id,
        "city_name_ko": text(
            alternative.get("city_name_ko", alternative.get("city_name")),
            "alternative_city.city_name_ko",
        ),
        "country": text(selected.get("country"), "selected_city.country"),
        "selection_reason_code": tuple(dict.fromkeys(reason_codes)),
        "ddb_pk": alternative.get("ddb_pk"),
        "province": alternative.get("province", selected.get("province")),
    }


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _alternative_city_id(
    state: Mapping[str, object],
    alternative: Mapping[str, object],
    *,
    selected_city_id: str | None,
) -> str | None:
    explicit_id = optional_text(alternative.get("city_id"))
    if explicit_id is not None:
        return explicit_id
    alternative_ddb_pk = optional_text(alternative.get("ddb_pk"))
    alternative_name = optional_text(alternative.get("city_name_ko"))
    for ranking in _city_rankings(state):
        ranking_city_id = optional_text(ranking.get("city_id"))
        if ranking_city_id == selected_city_id:
            continue
        if alternative_ddb_pk is not None and optional_text(ranking.get("ddb_pk")) == alternative_ddb_pk:
            return ranking_city_id
        if alternative_name is not None and optional_text(ranking.get("city_name_ko")) == alternative_name:
            return ranking_city_id
    return None


def _ranked_alternative_city(
    state: Mapping[str, object],
    *,
    selected_city_id: str | None,
) -> dict[str, object] | None:
    rankings = _city_rankings(state)
    if not rankings:
        return None
    selected_score = None
    for ranking in rankings:
        if optional_text(ranking.get("city_id")) == selected_city_id:
            selected_score = _optional_float(ranking.get("city_score"))
            break
    for ranking in rankings:
        city_id = optional_text(ranking.get("city_id"))
        if city_id is None or city_id == selected_city_id:
            continue
        payload: dict[str, object] = {
            "city_id": city_id,
            "city_name_ko": ranking.get("city_name_ko"),
            "ddb_pk": ranking.get("ddb_pk"),
            "province": ranking.get("province"),
        }
        for key, value in _city_metadata(state, city_id).items():
            if payload.get(key) is None and value is not None:
                payload[key] = value
        ranking_score = _optional_float(ranking.get("city_score"))
        if selected_score is not None and ranking_score is not None:
            payload["score_delta"] = round(selected_score - ranking_score, 4)
        return payload
    return None


def _city_rankings(state: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    city_select = mapping(state.get("city_select"), "city_select")
    scoring_audit = optional_mapping(city_select.get("scoring_audit"))
    if scoring_audit is None:
        return ()
    rankings = scoring_audit.get("city_rankings")
    if not isinstance(rankings, (list, tuple)):
        return ()
    return tuple(ranking for ranking in rankings if isinstance(ranking, Mapping))


def _city_metadata(state: Mapping[str, object], city_id: str) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for ranking in _city_rankings(state):
        if optional_text(ranking.get("city_id")) == city_id:
            metadata.update({
                "city_name_ko": ranking.get("city_name_ko"),
                "ddb_pk": ranking.get("ddb_pk"),
                "province": ranking.get("province"),
            })
            break
    city_select = mapping(state.get("city_select"), "city_select")
    scoring_audit = optional_mapping(city_select.get("scoring_audit"))
    if scoring_audit is None:
        return metadata
    for collection_name in ("recommended_places_by_city", "reserve_places_by_city"):
        places_by_city = optional_mapping(scoring_audit.get(collection_name))
        if places_by_city is None:
            continue
        places = mapping_sequence(places_by_city.get(city_id))
        if places:
            first_place = places[0]
            for key, value in {
                "city_name_ko": first_place.get("city_name_ko"),
                "ddb_pk": first_place.get("ddb_pk"),
                "province": first_place.get("province"),
            }.items():
                if metadata.get(key) is None and value is not None:
                    metadata[key] = value
            break
    identity = load_default_city_identity_map().get(
        metadata.get("city_id") or metadata.get("ddb_pk") or city_id,
    )
    if identity is not None:
        for key, value in identity.to_dict().items():
            if metadata.get(key) is None and value is not None:
                metadata[key] = value
    return metadata


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
