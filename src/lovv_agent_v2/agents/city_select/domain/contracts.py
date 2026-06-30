from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from collections.abc import Mapping, Sequence

from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError

CITY_DISCOVERY_MODE = "city_discovery"
ANCHORED_PLACE_SEARCH_MODE = "anchored_place_search"
FESTIVAL_SEEDED_CITY_DISCOVERY_MODE = "festival_seeded_city_discovery"
GOURMET_EXTERNAL_THEME_LABELS = frozenset(
    {
        "food_local",
        "미식",
        "미식·노포",
        "미식/노포",
    },
)
FESTIVAL_EXCLUDED_THEME_LABELS = frozenset(
    {
        "festival",
        "festival_event",
        "event",
        "축제",
        "축제·이벤트",
        "축제/이벤트",
    },
)
PLACE_SEARCH_EXCLUDED_THEME_LABELS = (
    GOURMET_EXTERNAL_THEME_LABELS | FESTIVAL_EXCLUDED_THEME_LABELS
)
EXTERNAL_LINK_THEME_LABELS = GOURMET_EXTERNAL_THEME_LABELS
FESTIVAL_THEME_MARKERS = FESTIVAL_EXCLUDED_THEME_LABELS


@dataclass(frozen=True, slots=True)
class AttractionCandidate:
    key: str
    place_id: str
    distance: float
    entity_type: str
    city_id: str
    city_name_ko: str | None
    title: str
    theme_tags: tuple[str, ...]
    latitude: float | None
    longitude: float | None
    ddb_pk: str | None
    ddb_sk: str | None
    metadata: dict[str, Any]
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PrunedCityGroups:
    survived_groups: dict[str, tuple[AttractionCandidate, ...]]
    eliminated_cities: tuple[str, ...]
    available_themes_by_city: dict[str, tuple[str, ...]] | None = None
    missing_themes_by_city: dict[str, tuple[str, ...]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "survived_groups": {
                city_id: [candidate.to_dict() for candidate in candidates]
                for city_id, candidates in self.survived_groups.items()
            },
            "eliminated_cities": list(self.eliminated_cities),
            "available_themes_by_city": self.available_themes_by_city or {},
            "missing_themes_by_city": self.missing_themes_by_city or {},
        }


@dataclass(frozen=True, slots=True)
class CandidateThemeSplit:
    active_required_themes: tuple[str, ...]
    searchable_place_themes: tuple[str, ...]
    external_link_themes: tuple[str, ...]
    ignored_theme_markers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CitySelectContext:
    candidate_input: CitySelectInput
    mode: str
    theme_split: CandidateThemeSplit
    include_festivals: bool


def prepare_city_select_context(
    candidate_input: CitySelectInput | Mapping[str, Any],
) -> CitySelectContext:
    normalized_input = ensure_city_select_input(candidate_input)
    return CitySelectContext(
        candidate_input=normalized_input,
        mode=resolve_city_select_mode(normalized_input),
        theme_split=split_candidate_themes(normalized_input.active_required_themes),
        include_festivals=normalized_input.include_festivals,
    )


def ensure_city_select_input(
    candidate_input: CitySelectInput | Mapping[str, Any],
) -> CitySelectInput:
    if isinstance(candidate_input, CitySelectInput):
        return candidate_input
    if isinstance(candidate_input, Mapping):
        return CitySelectInput.from_mapping(candidate_input)
    raise SchemaValidationError("city_select_input must be a schema or mapping")


def resolve_city_select_mode(candidate_input: CitySelectInput) -> str:
    if candidate_input.destination_id is not None:
        return ANCHORED_PLACE_SEARCH_MODE
    if candidate_input.include_festivals:
        return FESTIVAL_SEEDED_CITY_DISCOVERY_MODE
    return CITY_DISCOVERY_MODE


def split_candidate_themes(themes: Sequence[str]) -> CandidateThemeSplit:
    active_required_themes: list[str] = []
    searchable_place_themes: list[str] = []
    external_link_themes: list[str] = []
    ignored_theme_markers: list[str] = []

    for theme in unique_theme_labels(themes):
        if theme in FESTIVAL_THEME_MARKERS:
            ignored_theme_markers.append(theme)
            continue
        active_required_themes.append(theme)
        if theme in EXTERNAL_LINK_THEME_LABELS:
            external_link_themes.append(theme)
        else:
            searchable_place_themes.append(theme)

    return CandidateThemeSplit(
        active_required_themes=tuple(active_required_themes),
        searchable_place_themes=tuple(searchable_place_themes),
        external_link_themes=tuple(external_link_themes),
        ignored_theme_markers=tuple(ignored_theme_markers),
    )


def unique_theme_labels(themes: Sequence[str]) -> tuple[str, ...]:
    if isinstance(themes, str) or not isinstance(themes, Sequence):
        raise SchemaValidationError("active_required_themes must be a sequence")

    unique_themes: list[str] = []
    for raw_theme in themes:
        if not isinstance(raw_theme, str):
            raise SchemaValidationError("active_required_themes must contain strings")
        theme = raw_theme.strip()
        if not theme:
            raise SchemaValidationError("active_required_themes cannot contain blanks")
        if theme not in unique_themes:
            unique_themes.append(theme)
    return tuple(unique_themes)


__all__ = [
    "ANCHORED_PLACE_SEARCH_MODE",
    "CITY_DISCOVERY_MODE",
    "EXTERNAL_LINK_THEME_LABELS",
    "FESTIVAL_EXCLUDED_THEME_LABELS",
    "FESTIVAL_SEEDED_CITY_DISCOVERY_MODE",
    "FESTIVAL_THEME_MARKERS",
    "GOURMET_EXTERNAL_THEME_LABELS",
    "PLACE_SEARCH_EXCLUDED_THEME_LABELS",
    "AttractionCandidate",
    "CandidateThemeSplit",
    "CitySelectContext",
    "PrunedCityGroups",
    "ensure_city_select_input",
    "prepare_city_select_context",
    "resolve_city_select_mode",
    "split_candidate_themes",
    "unique_theme_labels",
]
