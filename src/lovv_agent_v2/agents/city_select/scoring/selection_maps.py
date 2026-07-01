from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.agents.city_select.domain.contracts import CitySelectContext
from lovv_agent_v2.agents.city_select.scoring.payloads import _lightweight_selected_places
from lovv_agent_v2.agents.city_select.scoring.selection import (
    CandidateSelectionHelper,
    CandidateSelectionResult,
)


@dataclass(frozen=True, slots=True)
class CitySelectionMapRequest:
    scored_groups: Mapping[str, Sequence[Any]]
    city_rankings: Sequence[Mapping[str, Any]]
    context: CitySelectContext
    primary_budget: int
    selection: CandidateSelectionHelper


@dataclass(frozen=True, slots=True)
class CitySelectionMaps:
    selection_by_city: dict[str, CandidateSelectionResult]
    recommended_places_by_city: dict[str, tuple[dict[str, Any], ...]]


def build_city_selection_maps(request: CitySelectionMapRequest) -> CitySelectionMaps:
    selection_by_city = {
        city_id: request.selection.select_primary_with_theme_quotas(
            request.scored_groups[city_id],
            request.context.theme_split.searchable_place_themes,
            primary_budget=request.primary_budget,
            required_themes=request.context.theme_split.active_required_themes,
            no_support_themes=request.context.theme_split.no_support_themes,
        )
        for city_id in _ranked_city_ids(request.city_rankings)
    }
    return CitySelectionMaps(
        selection_by_city=selection_by_city,
        recommended_places_by_city=_places_by_city(
            selection_by_city,
            request.scored_groups,
        ),
    )


def _ranked_city_ids(city_rankings: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(str(ranking["city_id"]) for ranking in city_rankings)


def _places_by_city(
    selection_by_city: Mapping[str, CandidateSelectionResult],
    scored_groups: Mapping[str, Sequence[Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    return {
        city_id: _lightweight_selected_places(
            selection_by_city[city_id].primary,
            scored_groups[city_id],
        )
        for city_id in selection_by_city
    }
