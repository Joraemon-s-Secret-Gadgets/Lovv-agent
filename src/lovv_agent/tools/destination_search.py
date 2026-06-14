"""DestinationSearchTool retrieval helpers.

The tool builds runtime retrieval requests and normalizes raw retrieval records.
It does not score cities, generate itineraries, or create public responses.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from lovv_agent.config import SearchBudgetSettings
from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.repositories.s3_vectors import (
    S3VectorRepository,
    extract_vector_records,
)

TOOL_NAME = "DestinationSearchTool"

RESPONSIBILITY = "Search and normalize S3 Vector attraction evidence."

ATTRACTION_ENTITY_TYPE = "attraction"
DEFAULT_RETURN_DISTANCE = True
DEFAULT_RETURN_METADATA = True
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
_CHUNK_SUFFIX_PATTERN = re.compile(
    r"(?i)(?:::|#|/|_|-)?chunk(?:[-_:#/])?\d+$",
)


@dataclass(frozen=True, slots=True)
class AttractionCandidate:
    """Normalized attraction candidate produced from an S3 Vector record."""

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
        """Return a serializable candidate payload."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class PrunedCityGroups:
    """City groups that survived searchable theme coverage checks."""

    survived_groups: dict[str, tuple[AttractionCandidate, ...]]
    eliminated_cities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable city pruning payload."""

        return {
            "survived_groups": {
                city_id: [candidate.to_dict() for candidate in candidates]
                for city_id, candidates in self.survived_groups.items()
            },
            "eliminated_cities": list(self.eliminated_cities),
        }


@dataclass(frozen=True, slots=True)
class DestinationSearchTool:
    """S3 Vector destination retrieval facade over an injected repository."""

    s3_vectors: S3VectorRepository
    search_budget: SearchBudgetSettings

    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        city_id: str | None = None,
        theme: str | None = None,
        theme_tags: Sequence[str] | None = None,
        top_k: int | None = None,
    ) -> tuple[AttractionCandidate, ...]:
        """Search attraction candidates and normalize the raw vector response."""

        search_theme = _resolve_place_search_theme(theme, theme_tags)
        if search_theme is not None and _is_excluded_place_search_theme(search_theme):
            return ()

        request = build_attraction_search_request(
            query_vector=query_vector,
            city_id=city_id,
            theme=search_theme,
            top_k=top_k,
            search_budget=self.search_budget,
        )
        response = self.s3_vectors.query_vectors(request)
        return tuple(
            normalize_attraction_candidate(record)
            for record in extract_vector_records(response)
        )

    def prune_cities(
        self,
        candidates: Sequence[AttractionCandidate],
        searchable_place_themes: Sequence[str],
        *,
        allowed_city_ids: Sequence[str] | None = None,
    ) -> PrunedCityGroups:
        """Group candidates by city and apply searchable place theme coverage."""

        return prune_cities(
            candidates,
            searchable_place_themes,
            allowed_city_ids=allowed_city_ids,
        )


def build_attraction_search_request(
    *,
    query_vector: Sequence[float],
    city_id: str | None = None,
    theme: str | None = None,
    theme_tags: Sequence[str] | None = None,
    top_k: int | None = None,
    search_budget: SearchBudgetSettings,
) -> dict[str, Any]:
    """Build an attraction-only S3 Vector search request."""

    request = {
        "queryVector": {"float32": _normalize_query_vector(query_vector)},
        "topK": _resolve_top_k(top_k, search_budget),
        "returnMetadata": DEFAULT_RETURN_METADATA,
        "returnDistance": DEFAULT_RETURN_DISTANCE,
    }
    metadata_filter = build_attraction_filter(
        city_id=city_id,
        theme=theme,
        theme_tags=theme_tags,
    )
    if metadata_filter is not None:
        request["filter"] = metadata_filter
    return request


def build_attraction_filter(
    *,
    city_id: str | None = None,
    theme: str | None = None,
    theme_tags: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """Build the metadata filter for general attraction place search."""

    conditions: list[dict[str, Any]] = [
        {
            "entity_type": {"$eq": ATTRACTION_ENTITY_TYPE},
        },
    ]
    normalized_city_id = _optional_text(city_id, "city_id")
    if normalized_city_id is not None:
        conditions.append(
            {
                "city_id": {"$eq": normalized_city_id},
            },
        )

    normalized_theme = _resolve_place_search_theme(theme, theme_tags)
    if normalized_theme is not None:
        if _is_excluded_place_search_theme(normalized_theme):
            raise SchemaValidationError(
                "theme is not searchable through S3 Vector place search",
            )
        conditions.append(
            {
                "theme_tags": {"$eq": normalized_theme},
            },
        )

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def prune_cities(
    candidates: Sequence[AttractionCandidate],
    searchable_place_themes: Sequence[str],
    *,
    allowed_city_ids: Sequence[str] | None = None,
) -> PrunedCityGroups:
    """Apply city pool restriction and searchable theme AND gate."""

    required_themes = tuple(
        theme
        for theme in _normalize_string_sequence(
            searchable_place_themes,
            "searchable_place_themes",
        )
        if not _is_excluded_place_search_theme(theme)
    )
    allowed = (
        set(_normalize_string_sequence(allowed_city_ids, "allowed_city_ids"))
        if allowed_city_ids is not None
        else None
    )
    grouped: dict[str, list[AttractionCandidate]] = {}
    for candidate in candidates:
        city_key = _candidate_city_key(candidate)
        if city_key is None:
            continue
        if allowed is not None and candidate.city_id not in allowed:
            continue
        grouped.setdefault(city_key, []).append(candidate)

    survived: dict[str, tuple[AttractionCandidate, ...]] = {}
    eliminated: list[str] = []
    for city_id, city_candidates in grouped.items():
        available_themes = {
            theme
            for candidate in city_candidates
            for theme in candidate.theme_tags
        }
        if all(theme in available_themes for theme in required_themes):
            survived[city_id] = tuple(city_candidates)
        else:
            eliminated.append(city_id)
    return PrunedCityGroups(
        survived_groups=survived,
        eliminated_cities=tuple(eliminated),
    )


def normalize_attraction_candidate(record: Mapping[str, Any]) -> AttractionCandidate:
    """Normalize one raw S3 Vector attraction record."""

    if not isinstance(record, Mapping):
        raise SchemaValidationError("attraction candidate record must be a mapping")
    key = _required_text(_first_present(record, "key", "id"), "key")
    metadata = _metadata(record)
    entity_type = _required_text(metadata.get("entity_type"), "metadata.entity_type")
    if entity_type != ATTRACTION_ENTITY_TYPE:
        raise SchemaValidationError("metadata.entity_type must be attraction")

    return AttractionCandidate(
        key=key,
        place_id=_normalize_place_id(key=key, metadata=metadata),
        distance=_numeric(_first_present(record, "distance", "score"), "distance"),
        entity_type=entity_type,
        city_id=_required_text(metadata.get("city_id"), "metadata.city_id"),
        city_name_ko=_optional_text(
            metadata.get("city_name_ko"),
            "metadata.city_name_ko",
        ),
        title=_required_text(metadata.get("title"), "metadata.title"),
        theme_tags=_normalize_string_sequence(
            metadata.get("theme_tags"),
            "metadata.theme_tags",
        ),
        latitude=_optional_numeric(metadata.get("latitude"), "metadata.latitude"),
        longitude=_optional_numeric(metadata.get("longitude"), "metadata.longitude"),
        ddb_pk=_optional_text(metadata.get("ddb_pk"), "metadata.ddb_pk"),
        ddb_sk=_optional_text(metadata.get("ddb_sk"), "metadata.ddb_sk"),
        metadata=dict(metadata),
    )


def _normalize_place_id(*, key: str, metadata: Mapping[str, Any]) -> str:
    """Return metadata place id, or strip a chunk suffix from the vector key."""

    metadata_place_id = _optional_text(metadata.get("place_id"), "metadata.place_id")
    if metadata_place_id is not None:
        return metadata_place_id
    hash_parts = key.split("#")
    if len(hash_parts) >= 3 and hash_parts[-1].isdigit():
        return "#".join(hash_parts[:-1])
    normalized = _CHUNK_SUFFIX_PATTERN.sub("", key).strip()
    if not normalized:
        raise SchemaValidationError("place_id could not be normalized from key")
    return normalized


def _candidate_city_key(candidate: AttractionCandidate) -> str | None:
    """Return the grouping city key according to the destination search contract."""

    if candidate.city_id:
        return candidate.city_id
    return candidate.city_name_ko


def _metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return copied vector metadata."""

    value = record.get("metadata", {})
    if not isinstance(value, Mapping):
        raise SchemaValidationError("attraction candidate metadata must be a mapping")
    return dict(value)


def _first_present(record: Mapping[str, Any], *field_names: str) -> Any:
    """Return the first present field value from a raw record."""

    for field_name in field_names:
        if field_name in record:
            return record[field_name]
    joined = " or ".join(field_names)
    raise SchemaValidationError(f"missing required field: {joined}")


def _resolve_top_k(top_k: int | None, search_budget: SearchBudgetSettings) -> int:
    """Use call-level top K or fall back to injected runtime budget."""

    selected = (
        search_budget.per_theme_attraction_top_k
        if top_k is None
        else top_k
    )
    if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
        raise SchemaValidationError("top_k must be a positive integer")
    return selected


def _normalize_query_vector(query_vector: Sequence[float]) -> list[float]:
    """Validate and copy the embedding vector used for search."""

    if isinstance(query_vector, (str, bytes)) or not isinstance(query_vector, Sequence):
        raise SchemaValidationError("query_vector must be a numeric sequence")
    if not query_vector:
        raise SchemaValidationError("query_vector must not be empty")
    normalized: list[float] = []
    for value in query_vector:
        normalized.append(_numeric(value, "query_vector"))
    return normalized


def _resolve_place_search_theme(
    theme: str | None,
    theme_tags: Sequence[str] | None,
) -> str | None:
    """Resolve the single active theme used by one S3 Vector search call."""

    merged: list[str] = []
    normalized_theme = _optional_text(theme, "theme")
    if normalized_theme is not None:
        merged.append(normalized_theme)
    if theme_tags is not None:
        merged.extend(_normalize_string_sequence(theme_tags, "theme_tags"))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in merged:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    if len(deduped) > 1:
        raise SchemaValidationError(
            "search_candidates accepts one active theme per S3 Vector query",
        )
    return deduped[0] if deduped else None


def _is_excluded_place_search_theme(theme: str) -> bool:
    """Return whether a theme must not trigger attraction vector search."""

    return theme in PLACE_SEARCH_EXCLUDED_THEME_LABELS


def _normalize_string_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    """Validate a string sequence."""

    if value is None:
        return ()
    if isinstance(value, str):
        return (_required_text(value, field_name),)
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    return tuple(_required_text(item, field_name) for item in value)


def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty text value."""

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
    return _required_text(value, field_name)


def _numeric(value: Any, field_name: str) -> float:
    """Validate a numeric value without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be numeric")
    return float(value)


def _optional_numeric(value: Any, field_name: str) -> float | None:
    """Validate optional numeric metadata."""

    if value is None:
        return None
    return _numeric(value, field_name)


__all__ = [
    "ATTRACTION_ENTITY_TYPE",
    "DEFAULT_RETURN_DISTANCE",
    "DEFAULT_RETURN_METADATA",
    "GOURMET_EXTERNAL_THEME_LABELS",
    "PLACE_SEARCH_EXCLUDED_THEME_LABELS",
    "RESPONSIBILITY",
    "TOOL_NAME",
    "AttractionCandidate",
    "DestinationSearchTool",
    "FESTIVAL_EXCLUDED_THEME_LABELS",
    "PrunedCityGroups",
    "build_attraction_filter",
    "build_attraction_search_request",
    "normalize_attraction_candidate",
    "prune_cities",
]
