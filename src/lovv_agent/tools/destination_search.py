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

RESPONSIBILITY = "Retrieve and normalize destination/place/festival evidence."

ATTRACTION_ENTITY_TYPE = "attraction"
DEFAULT_RETURN_DISTANCE = True
DEFAULT_RETURN_METADATA = True
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

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable candidate payload."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class DestinationSearchTool:
    """Destination retrieval facade over injected repositories."""

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

        request = build_attraction_search_request(
            query_vector=query_vector,
            city_id=city_id,
            theme=theme,
            theme_tags=theme_tags,
            top_k=top_k,
            search_budget=self.search_budget,
        )
        response = self.s3_vectors.query_vectors(request)
        return tuple(
            normalize_attraction_candidate(record)
            for record in extract_vector_records(response)
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

    return {
        "query_vector": _normalize_query_vector(query_vector),
        "top_k": _resolve_top_k(top_k, search_budget),
        "return_metadata": DEFAULT_RETURN_METADATA,
        "return_distance": DEFAULT_RETURN_DISTANCE,
        "filter": build_attraction_filter(
            city_id=city_id,
            theme=theme,
            theme_tags=theme_tags,
        ),
    }


def build_attraction_filter(
    *,
    city_id: str | None = None,
    theme: str | None = None,
    theme_tags: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the metadata filter for general attraction place search."""

    conditions: list[dict[str, Any]] = [
        {
            "field": "entity_type",
            "operator": "eq",
            "value": ATTRACTION_ENTITY_TYPE,
        },
    ]
    normalized_city_id = _optional_text(city_id, "city_id")
    if normalized_city_id is not None:
        conditions.append(
            {
                "field": "city_id",
                "operator": "eq",
                "value": normalized_city_id,
            },
        )

    normalized_theme_tags = _normalize_theme_tags(theme, theme_tags)
    if normalized_theme_tags:
        conditions.append(
            {
                "field": "theme_tags",
                "operator": "contains_any",
                "values": list(normalized_theme_tags),
            },
        )

    return {"and": conditions}


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
    normalized = _CHUNK_SUFFIX_PATTERN.sub("", key).strip()
    if not normalized:
        raise SchemaValidationError("place_id could not be normalized from key")
    return normalized


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


def _normalize_theme_tags(
    theme: str | None,
    theme_tags: Sequence[str] | None,
) -> tuple[str, ...]:
    """Merge the singular theme parameter and theme tag list."""

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
    return tuple(deduped)


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
    "RESPONSIBILITY",
    "TOOL_NAME",
    "AttractionCandidate",
    "DestinationSearchTool",
    "build_attraction_filter",
    "build_attraction_search_request",
    "normalize_attraction_candidate",
]
