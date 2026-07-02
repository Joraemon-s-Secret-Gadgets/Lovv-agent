from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.selection_types import SelectionCandidate
from lovv_agent_v2.agents.city_select.scoring.service import PlaceScoreResult
from lovv_agent_v2.models.schemas import SchemaValidationError


def deduplicate_by_title(
    candidates: Sequence[SelectionCandidate],
) -> tuple[list[SelectionCandidate], int]:
    seen_titles: set[str] = set()
    deduplicated: list[SelectionCandidate] = []
    deduped = 0
    for candidate in candidates:
        key = _title_key(candidate.title)
        if key is None:
            deduplicated.append(candidate)
            continue
        if key in seen_titles:
            deduped += 1
            continue
        seen_titles.add(key)
        deduplicated.append(candidate)
    return deduplicated, deduped


def coerce_candidate(candidate: Any) -> SelectionCandidate:
    if isinstance(candidate, SelectionCandidate):
        return candidate
    if isinstance(candidate, PlaceScoreResult):
        return SelectionCandidate(
            payload=candidate,
            place_id=candidate.place_id,
            title=candidate.title,
            theme_tags=candidate.theme_tags,
            place_score=candidate.place_score,
        )
    if isinstance(candidate, Mapping):
        return SelectionCandidate(
            payload=candidate,
            place_id=required_text(
                _mapping_get(candidate, "place_id", "placeId"),
                "place_id",
            ),
            title=optional_text(_mapping_get(candidate, "title", "name", default=None)),
            theme_tags=string_tuple(
                _mapping_get(candidate, "theme_tags", "themeTags", default=()),
                "theme_tags",
            ),
            place_score=numeric(
                _mapping_get(candidate, "place_score", "score"),
                "place_score",
            ),
        )
    return SelectionCandidate(
        payload=candidate,
        place_id=required_text(
            _object_get(candidate, "place_id", "placeId", "id"),
            "place_id",
        ),
        title=optional_text(_object_get(candidate, "title", "name")),
        theme_tags=string_tuple(
            _object_get(candidate, "theme_tags", "themeTags"),
            "theme_tags",
        ),
        place_score=numeric(_object_get(candidate, "place_score", "score"), "place_score"),
    )


def best_assignable_theme(
    candidate: SelectionCandidate,
    searchable_themes: tuple[str, ...],
    theme_counts: Counter[str],
    theme_max_quota: int,
    *,
    enforce_max: bool,
) -> str | None:
    matching = tuple(theme for theme in searchable_themes if theme in candidate.theme_tags)
    if not matching:
        return None
    allowed = (
        tuple(theme for theme in matching if theme_counts[theme] < theme_max_quota)
        if enforce_max
        else matching
    )
    if not allowed:
        return None
    return min(allowed, key=lambda theme: (theme_counts[theme], searchable_themes.index(theme)))


def first_theme(
    candidate: SelectionCandidate,
    searchable_themes: tuple[str, ...],
) -> str | None:
    for theme in searchable_themes:
        if theme in candidate.theme_tags:
            return theme
    return candidate.theme_tags[0] if candidate.theme_tags else None


def string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (required_text(value, field_name),)
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    return tuple(required_text(item, field_name) for item in value)


def required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError("optional text must be a string")
    normalized = value.strip()
    return normalized or None


def positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return value


def numeric(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be numeric")
    return float(value)


def _title_key(title: str | None) -> str | None:
    if title is None:
        return None
    normalized = title.strip().casefold()
    return normalized or None


def _mapping_get(
    payload: Mapping[str, Any],
    *field_names: str,
    default: Any = None,
) -> Any:
    for field_name in field_names:
        if field_name in payload:
            return payload[field_name]
    return default


def _object_get(value: Any, *field_names: str) -> Any:
    for field_name in field_names:
        if hasattr(value, field_name):
            return getattr(value, field_name)
    return None
