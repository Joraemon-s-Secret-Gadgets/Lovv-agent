from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.selection_types import (
    CandidateSelectionResult,
    SelectionCandidate,
)


def selection_result(
    *,
    primary_candidates: tuple[SelectionCandidate, ...],
    reserve_candidates: tuple[SelectionCandidate, ...],
    primary_assignments: Mapping[str, str | None],
    reserve_assignments: Mapping[str, str | None],
    deduplicated_candidates: tuple[SelectionCandidate, ...],
    required_themes: tuple[str, ...],
    searchable_themes: tuple[str, ...],
    external_link_themes: tuple[str, ...],
    theme_min_quota: int,
    theme_max_quota: int,
    min_quota_shortfalls: Mapping[str, int],
    max_quota_relaxed: bool,
    relaxed_slots: int,
    deduplicated_title_count: int,
    primary_budget: int,
    reserve_budget: int,
) -> CandidateSelectionResult:
    primary = tuple(
        candidate.with_role("primary", primary_assignments.get(candidate.place_id))
        for candidate in primary_candidates
    )
    reserve = tuple(
        candidate.with_role("reserve", reserve_assignments.get(candidate.place_id))
        for candidate in reserve_candidates
    )
    unfilled_primary_slots = max(primary_budget - len(primary_candidates), 0)
    coverage_audit = {
        "required_themes": list(required_themes),
        "searchable_place_themes": list(searchable_themes),
        "external_link_themes": list(external_link_themes),
        "primary_theme_counts": _theme_counts(primary, searchable_themes),
        "reserve_theme_counts": _theme_counts(reserve, searchable_themes),
        "planner_capacity": (
            "sufficient" if len(primary_candidates) >= 5 else "insufficient"
        ),
        "theme_min_quota": theme_min_quota,
        "theme_max_quota": theme_max_quota,
        "min_quota_shortfalls": dict(min_quota_shortfalls),
        "max_quota_relaxed": max_quota_relaxed,
        "relaxed_slots": relaxed_slots,
        "deduplicated_title_count": deduplicated_title_count,
        "unfilled_primary_slots": unfilled_primary_slots,
        "primary_budget": primary_budget,
        "reserve_budget": reserve_budget,
    }
    return CandidateSelectionResult(
        primary=primary,
        reserve=reserve,
        coverage_audit=coverage_audit,
        deduplicated_candidates=deduplicated_candidates,
    )


def _theme_counts(
    selected_payloads: Sequence[Mapping[str, Any]],
    searchable_themes: tuple[str, ...],
) -> dict[str, int]:
    counts = {theme: 0 for theme in searchable_themes}
    for payload in selected_payloads:
        assigned_theme = payload.get("assigned_theme")
        if assigned_theme in counts:
            counts[str(assigned_theme)] += 1
    return counts
