from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.selection_normalization import (
    best_assignable_theme,
    coerce_candidate,
    deduplicate_by_title,
    first_theme,
    positive_int,
    required_text,
    string_tuple,
)
from lovv_agent_v2.agents.city_select.scoring.selection_result import (
    selection_result,
)
from lovv_agent_v2.agents.city_select.scoring.selection_types import (
    CandidateSelectionResult,
    SelectionCandidate,
)
from lovv_agent_v2.models.schemas import SchemaValidationError

TOOL_NAME = "CandidateSelectionHelper"

RESPONSIBILITY = "Select primary and reserve candidates from scored evidence."

TRIP_CANDIDATE_BUDGETS: dict[str, int] = {
    "daytrip": 6,
    "2d1n": 10,
    "3d2n": 14,
    "4d3n": 18,
    "5d4n": 18,
}

TRIP_ITINERARY_PLACE_COUNTS: dict[str, int] = {
    # count는 현재 Planner slot template과 맞춘다.
    "daytrip": 3,
    "2d1n": 5,
    "3d2n": 8,
    "4d3n": 11,
    "5d4n": 14,
}


class CandidateSelectionHelper:
    def select_primary_with_theme_quotas(
        self,
        candidates: Sequence[Any],
        searchable_place_themes: Sequence[str],
        *,
        primary_budget: int,
        required_themes: Sequence[str] | None = None,
        no_support_themes: Sequence[str] | None = None,
    ) -> CandidateSelectionResult:
        return select_primary_with_theme_quotas(
            candidates,
            searchable_place_themes,
            primary_budget=primary_budget,
            required_themes=required_themes,
            no_support_themes=no_support_themes,
        )


def candidate_budgets_for_trip(trip_type: str) -> int:
    normalized = required_text(trip_type, "trip_type")
    if normalized not in TRIP_CANDIDATE_BUDGETS:
        raise SchemaValidationError(f"unsupported trip_type: {normalized}")
    return TRIP_CANDIDATE_BUDGETS[normalized]


def itinerary_place_count_for_trip(trip_type: str) -> int:
    """Return the attraction slot count Planner must be able to fill."""

    normalized = required_text(trip_type, "trip_type")
    if normalized not in TRIP_ITINERARY_PLACE_COUNTS:
        raise SchemaValidationError(f"unsupported trip_type: {normalized}")
    return TRIP_ITINERARY_PLACE_COUNTS[normalized]


def select_primary_with_theme_quotas(
    candidates: Sequence[Any],
    searchable_place_themes: Sequence[str],
    *,
    primary_budget: int,
    required_themes: Sequence[str] | None = None,
    no_support_themes: Sequence[str] | None = None,
) -> CandidateSelectionResult:
    primary_limit = positive_int(primary_budget, "primary_budget")
    searchable_themes = string_tuple(
        searchable_place_themes,
        "searchable_place_themes",
    )
    required_theme_list = string_tuple(
        required_themes if required_themes is not None else searchable_themes,
        "required_themes",
    )
    no_support_theme_list = string_tuple(
        no_support_themes if no_support_themes is not None else (),
        "no_support_themes",
    )
    normalized = sorted(
        (coerce_candidate(candidate) for candidate in candidates),
        key=lambda candidate: candidate.place_score,
        reverse=True,
    )
    deduplicated, deduped_title_count = deduplicate_by_title(normalized)
    if not searchable_themes:
        primary_candidates = deduplicated[:primary_limit]
        primary_assignments = {
            candidate.place_id: first_theme(candidate, ())
            for candidate in primary_candidates
        }
        return selection_result(
            primary_candidates=tuple(primary_candidates),
            primary_assignments=primary_assignments,
            deduplicated_candidates=tuple(deduplicated),
            required_themes=required_theme_list,
            searchable_themes=searchable_themes,
            no_support_themes=no_support_theme_list,
            theme_min_quota=0,
            theme_max_quota=0,
            min_quota_shortfalls={},
            max_quota_relaxed=False,
            relaxed_slots=0,
            deduplicated_title_count=deduped_title_count,
            primary_budget=primary_limit,
        )

    theme_min_quota = math.floor(primary_limit / len(searchable_themes) * 0.6)
    theme_max_quota = math.ceil(primary_limit / 2)
    selected: list[SelectionCandidate] = []
    selected_ids: set[str] = set()
    primary_assignments: dict[str, str | None] = {}
    theme_counts: Counter[str] = Counter()
    min_quota_shortfalls: dict[str, int] = {}

    for theme in searchable_themes:
        matching = [
            candidate
            for candidate in deduplicated
            if candidate.place_id not in selected_ids and theme in candidate.theme_tags
        ]
        taken = 0
        for candidate in matching:
            if taken >= theme_min_quota or len(selected) >= primary_limit:
                break
            selected.append(candidate)
            selected_ids.add(candidate.place_id)
            primary_assignments[candidate.place_id] = theme
            theme_counts[theme] += 1
            taken += 1
        shortfall = max(theme_min_quota - taken, 0)
        if shortfall:
            min_quota_shortfalls[theme] = shortfall

    for candidate in deduplicated:
        if len(selected) >= primary_limit:
            break
        if candidate.place_id in selected_ids:
            continue
        assigned_theme = best_assignable_theme(
            candidate,
            searchable_themes,
            theme_counts,
            theme_max_quota,
            enforce_max=True,
        )
        if assigned_theme is None:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.place_id)
        primary_assignments[candidate.place_id] = assigned_theme
        theme_counts[assigned_theme] += 1

    relaxed_slots = 0
    if len(selected) < primary_limit:
        for candidate in deduplicated:
            if len(selected) >= primary_limit:
                break
            if candidate.place_id in selected_ids:
                continue
            assigned_theme = best_assignable_theme(
                candidate,
                searchable_themes,
                theme_counts,
                theme_max_quota,
                enforce_max=False,
            )
            if assigned_theme is None:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.place_id)
            primary_assignments[candidate.place_id] = assigned_theme
            theme_counts[assigned_theme] += 1
            relaxed_slots += 1

    return selection_result(
        primary_candidates=tuple(selected),
        primary_assignments=primary_assignments,
        deduplicated_candidates=tuple(deduplicated),
        required_themes=required_theme_list,
        searchable_themes=searchable_themes,
        no_support_themes=no_support_theme_list,
        theme_min_quota=theme_min_quota,
        theme_max_quota=theme_max_quota,
        min_quota_shortfalls=min_quota_shortfalls,
        max_quota_relaxed=relaxed_slots > 0,
        relaxed_slots=relaxed_slots,
        deduplicated_title_count=deduped_title_count,
        primary_budget=primary_limit,
    )


__all__ = [
    "CandidateSelectionHelper",
    "CandidateSelectionResult",
    "RESPONSIBILITY",
    "SelectionCandidate",
    "TOOL_NAME",
    "TRIP_CANDIDATE_BUDGETS",
    "TRIP_ITINERARY_PLACE_COUNTS",
    "candidate_budgets_for_trip",
    "itinerary_place_count_for_trip",
    "select_primary_with_theme_quotas",
]
