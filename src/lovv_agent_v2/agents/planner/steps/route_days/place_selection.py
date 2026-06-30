from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.place_model import (
    PlannerPlace,
    coerce_place,
    merge_by_place_id,
    positive_int,
    seed_ids,
    selection_sort_key,
    theme_tuple,
    with_seed_flag,
)
from lovv_agent_v2.agents.planner.steps.route_days.day_profile import bounded_min_place_target
from lovv_agent_v2.agents.planner.steps.route_days.selection_policy import (
    ThemeSelectionInput,
    facet_theme_for_subtype,
    matches_any_theme,
    primary_theme,
    select_by_theme_quota,
    selected_theme_counts,
    theme_quota,
)
from lovv_agent_v2.agents.planner.steps.route_days.subtype_diversity import (
    SubtypeCapInput,
    apply_theme_subtype_cap,
    subtype_counts,
)
DEFAULT_RELEVANCE_RATIO = 0.6
TRIP_RELEVANCE_RATIOS: Mapping[str, float] = {
    "daytrip": 0.7,
    "2d1n": 0.6,
    "3d2n": 0.5,
}


@dataclass(frozen=True, slots=True)
class PlannerSelectionInput:
    raw_places: Sequence[Mapping[str, object]]
    soft_places: Sequence[Mapping[str, object]]
    seeds: Sequence[Mapping[str, object]]
    active_themes: Sequence[str]
    theme_weights: Mapping[str, float] | None
    trip_type: str
    target_count: int
    min_count: int | None = None


@dataclass(frozen=True, slots=True)
class PlannerSelectionResult:
    places: tuple[PlannerPlace, ...]
    reserve: tuple[PlannerPlace, ...]
    audit: dict[str, object]


def build_working_set(selection_input: PlannerSelectionInput) -> PlannerSelectionResult:
    raw_places = tuple(coerce_place(place) for place in selection_input.raw_places)
    soft_places = tuple(coerce_place(place) for place in selection_input.soft_places)
    selected_seed_ids = seed_ids(selection_input.seeds)
    themes = theme_tuple(selection_input.active_themes)
    target_count = positive_int(selection_input.target_count, "target_count")
    min_count_override = (
        None
        if selection_input.min_count is None
        else positive_int(selection_input.min_count, "min_count")
    )
    min_count = bounded_min_place_target(
        selection_input.trip_type,
        target_count,
        min_count_override,
    )
    ratio = TRIP_RELEVANCE_RATIOS.get(selection_input.trip_type, DEFAULT_RELEVANCE_RATIO)

    best_raw = max((place.similarity for place in raw_places), default=0.0)
    raw_threshold = round(best_raw * ratio, 4)
    raw_relevant = tuple(
        with_seed_flag(place, selected_seed_ids)
        for place in raw_places
        if place.similarity >= raw_threshold or place.place_id in selected_seed_ids
    )
    raw_kept = tuple(place for place in raw_relevant if _scope_theme(place, themes) is not None or place.is_seed)
    raw_ids = {place.place_id for place in raw_kept}

    best_soft = max((place.soft_similarity for place in soft_places), default=0.0)
    soft_threshold = round(best_soft * DEFAULT_RELEVANCE_RATIO, 4)
    soft_candidates = tuple(
        with_seed_flag(place, selected_seed_ids)
        for place in soft_places
        if place.place_id not in raw_ids and place.soft_similarity >= soft_threshold
    )
    soft_on_theme = tuple(place for place in soft_candidates if _scope_theme(place, themes) is not None)
    soft_off_theme = tuple(place for place in soft_candidates if _scope_theme(place, themes) is None)
    merged = merge_by_place_id((*raw_kept, *soft_on_theme))
    quotas = theme_quota(themes, selection_input.theme_weights, target_count)
    selected = select_by_theme_quota(
        ThemeSelectionInput(
            places=merged,
            themes=themes,
            weights=selection_input.theme_weights,
            target_count=target_count,
            sort_key=selection_sort_key,
            theme_key=lambda place: _scope_theme(place, themes),
        ),
    )
    facet_expansion = tuple(
        place for place in merged if not matches_any_theme(place, themes) and _scope_theme(place, themes) is not None
    )
    off_theme_excluded_count = sum(1 for place in raw_relevant if _scope_theme(place, themes) is None)
    subtype_cap = apply_theme_subtype_cap(
        SubtypeCapInput(
            selected=selected,
            pool=merged,
            themes=themes,
            quotas=quotas,
            target_count=target_count,
            min_count=min_count,
            sort_key=selection_sort_key,
            theme_key=lambda place: _scope_theme(place, themes),
        ),
    )
    selected = subtype_cap.places
    selected_ids = {place.place_id for place in selected}
    reserve = tuple(place for place in merged if place.place_id not in selected_ids)
    audit: dict[str, object] = {
        "relevance_ratio": ratio,
        "relative_threshold": raw_threshold,
        "raw_kept_count": len(raw_kept),
        "seed_preserved_count": sum(
            1 for place in selected if place.is_seed and place.similarity < raw_threshold
        ),
        "soft_threshold": soft_threshold,
        "soft_on_theme_added_count": len(soft_on_theme),
        "soft_off_theme_excluded_count": len(soft_off_theme),
        "no_theme_gate_added_count": 0,
        "no_theme_gate_policy": "disabled_by_v2_26_theme_scope",
        "facet_expansion_added_count": len(facet_expansion),
        "off_theme_excluded_count": off_theme_excluded_count + len(soft_off_theme),
        "theme_scope_policy": "single_theme_facet_or_active_theme_only",
        "theme_quota": quotas,
        "theme_counts": selected_theme_counts(
            selected,
            themes,
            lambda place: _scope_theme(place, themes),
        ),
        "subtype_counts": subtype_counts(selected),
        "subtype_cap_policy": "per_theme_quota_distinct_subtype_cap",
        "subtype_cap_limit": subtype_cap.limit,
        "subtype_cap_limits": subtype_cap.limits,
        "subtype_cap_relaxed": subtype_cap.relaxed,
        "availability_policy": "unknown_availability_kept_with_audit",
        "profile_cap_policy": "profile_cap_not_applied_without_profile_payload",
    }
    return PlannerSelectionResult(places=selected, reserve=reserve, audit=audit)


def _scope_theme(place: PlannerPlace, themes: tuple[str, ...]) -> str | None:
    if not themes:
        return primary_theme(place, themes)
    active_theme = next((theme for theme in themes if theme in place.theme_tags), None)
    if active_theme is not None:
        return active_theme
    return facet_theme_for_subtype(place.payload, themes)
