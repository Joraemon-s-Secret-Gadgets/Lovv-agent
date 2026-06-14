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
from lovv_agent.repositories.dynamodb import DynamoDbRepository
from lovv_agent.repositories.s3_vectors import (
    S3VectorRepository,
    extract_vector_records,
)

TOOL_NAME = "DestinationSearchTool"

RESPONSIBILITY = "Retrieve and normalize destination/place/festival evidence."

ATTRACTION_ENTITY_TYPE = "attraction"
DEFAULT_RETURN_DISTANCE = True
DEFAULT_RETURN_METADATA = True
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
class FestivalCandidate:
    """Normalized festival seed candidate from DynamoDB."""

    festival_id: str
    name: str
    country: str
    city_id: str
    city_name: str | None
    month: int
    theme_tags: tuple[str, ...]
    assigned_theme: str | None
    event_start_date: str | None
    event_end_date: str | None
    source: str | None
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable festival candidate payload."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class FestivalSeedResult:
    """Result of the festival city seed lookup."""

    status: str
    candidates: tuple[FestivalCandidate, ...] = ()
    failure_signals: tuple[str, ...] = ()
    needs_clarification: bool = False

    @property
    def seeded_city_ids(self) -> tuple[str, ...]:
        """Return unique seeded city ids in candidate order."""

        seen: set[str] = set()
        city_ids: list[str] = []
        for candidate in self.candidates:
            if candidate.city_id in seen:
                continue
            seen.add(candidate.city_id)
            city_ids.append(candidate.city_id)
        return tuple(city_ids)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable seed lookup payload."""

        return {
            "status": self.status,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "seeded_city_ids": list(self.seeded_city_ids),
            "failure_signals": list(self.failure_signals),
            "needs_clarification": self.needs_clarification,
        }


@dataclass(frozen=True, slots=True)
class DestinationSearchTool:
    """Destination retrieval facade over injected repositories."""

    s3_vectors: S3VectorRepository
    search_budget: SearchBudgetSettings
    dynamodb: DynamoDbRepository | None = None

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

    def search_festival_city_seeds(
        self,
        *,
        country: str,
        travel_month: int,
        theme_pool: Sequence[str],
        city_id: str | None = None,
        max_candidates: int | None = None,
    ) -> FestivalSeedResult:
        """Find month/theme-matching festival candidates before attraction search."""

        normalized_theme_pool = _normalize_festival_theme_pool(theme_pool)
        if not normalized_theme_pool:
            return _festival_seed_failure("no_required_theme_for_festival_seed")

        normalized_country = _required_text(country, "country")
        normalized_month = _month(travel_month, "travel_month")
        normalized_city_id = _optional_text(city_id, "city_id")
        limit = _resolve_max_festival_candidates(max_candidates, self.search_budget)
        response = self._require_dynamodb().query_festival_candidates(
            country=normalized_country,
            travel_month=normalized_month,
            city_id=normalized_city_id,
            limit=limit,
        )
        # The repository narrows by country/month. This guard keeps the tool
        # contract explicit and testable even when a mock or future index
        # returns a broader page.
        candidates = tuple(
            candidate
            for item in _extract_dynamodb_items(response)
            if (
                candidate := normalize_festival_candidate(item)
            ).country == normalized_country
            and candidate.month == normalized_month
            and _festival_matches_theme(candidate, normalized_theme_pool)
            and (
                normalized_city_id is None
                or candidate.city_id == normalized_city_id
            )
        )[:limit]
        if candidates:
            return FestivalSeedResult(status="ok", candidates=candidates)
        if normalized_city_id is not None:
            return _festival_seed_failure("no_festival_in_anchor_city")
        return _festival_seed_failure("no_festival_city_seed")

    def _require_dynamodb(self) -> DynamoDbRepository:
        """Return the injected DynamoDB repository or fail fast."""

        if self.dynamodb is None:
            raise SchemaValidationError(
                "dynamodb repository is required for festival lookup",
            )
        return self.dynamodb


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


def normalize_festival_candidate(item: Mapping[str, Any]) -> FestivalCandidate:
    """Normalize one DynamoDB festival seed item."""

    normalized = _plain_dynamodb_item(item)
    return FestivalCandidate(
        festival_id=_required_text(
            _first_present(normalized, "festival_id", "id"),
            "festival_id",
        ),
        name=_required_text(_first_present(normalized, "name", "title"), "name"),
        country=_required_text(normalized.get("country"), "country"),
        city_id=_required_text(normalized.get("city_id"), "city_id"),
        city_name=_optional_text(
            _first_optional(normalized, "city_name", "city_name_ko"),
            "city_name",
        ),
        month=_month(_first_present(normalized, "month"), "month"),
        theme_tags=_normalize_string_sequence(
            _first_optional(normalized, "theme_tags", "themes"),
            "theme_tags",
        ),
        assigned_theme=_optional_text(normalized.get("assigned_theme"), "assigned_theme"),
        event_start_date=_optional_text(
            _first_optional(normalized, "event_start_date", "eventstartdate"),
            "event_start_date",
        ),
        event_end_date=_optional_text(
            _first_optional(normalized, "event_end_date", "eventenddate"),
            "event_end_date",
        ),
        source=_optional_text(
            _first_optional(normalized, "source", "source_type", "provenance"),
            "source",
        ),
        raw=normalized,
    )


def _festival_seed_failure(signal: str) -> FestivalSeedResult:
    """Build a clarification-triggering festival seed failure."""

    return FestivalSeedResult(
        status="no_candidate",
        failure_signals=(signal,),
        needs_clarification=True,
    )


def _normalize_festival_theme_pool(theme_pool: Sequence[str]) -> tuple[str, ...]:
    """Normalize user travel themes for festival OR matching."""

    themes = _normalize_string_sequence(theme_pool, "theme_pool")
    filtered: list[str] = []
    seen: set[str] = set()
    for theme in themes:
        if theme in FESTIVAL_EXCLUDED_THEME_LABELS:
            continue
        if theme in seen:
            continue
        seen.add(theme)
        filtered.append(theme)
    return tuple(filtered)


def _festival_matches_theme(
    candidate: FestivalCandidate,
    theme_pool: tuple[str, ...],
) -> bool:
    """Return whether assigned theme or any theme tag matches the user theme pool."""

    theme_set = set(theme_pool)
    return (
        candidate.assigned_theme in theme_set
        if candidate.assigned_theme is not None
        else False
    ) or any(theme in theme_set for theme in candidate.theme_tags)


def _extract_dynamodb_items(response: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Extract raw item mappings from a DynamoDB query response."""

    if not isinstance(response, Mapping):
        raise SchemaValidationError("dynamodb response must be a mapping")
    items = response.get("Items", ())
    if not isinstance(items, (list, tuple)):
        raise SchemaValidationError("dynamodb response.Items must be a list")
    copied: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise SchemaValidationError("dynamodb response item must be a mapping")
        copied.append(dict(item))
    return tuple(copied)


def _plain_dynamodb_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a plain or DynamoDB AttributeValue item to plain Python values."""

    if not isinstance(item, Mapping):
        raise SchemaValidationError("dynamodb item must be a mapping")
    return {str(key): _unwrap_dynamodb_value(value) for key, value in item.items()}


def _unwrap_dynamodb_value(value: Any) -> Any:
    """Best-effort conversion from DynamoDB AttributeValue to Python values."""

    if not isinstance(value, Mapping) or len(value) != 1:
        return value
    if "S" in value:
        return value["S"]
    if "N" in value:
        number_value = value["N"]
        if isinstance(number_value, str) and number_value.isdigit():
            return int(number_value)
        return float(number_value)
    if "BOOL" in value:
        return value["BOOL"]
    if "SS" in value:
        return tuple(value["SS"])
    if "L" in value:
        return tuple(_unwrap_dynamodb_value(item) for item in value["L"])
    if "M" in value:
        return {
            str(key): _unwrap_dynamodb_value(item)
            for key, item in value["M"].items()
        }
    if "NULL" in value:
        return None
    return value


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


def _first_optional(record: Mapping[str, Any], *field_names: str) -> Any:
    """Return the first present field value, or ``None``."""

    for field_name in field_names:
        if field_name in record:
            return record[field_name]
    return None


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


def _resolve_max_festival_candidates(
    max_candidates: int | None,
    search_budget: SearchBudgetSettings,
) -> int:
    """Use call-level festival seed limit or injected runtime budget."""

    selected = (
        search_budget.max_festival_seed_candidates
        if max_candidates is None
        else max_candidates
    )
    if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
        raise SchemaValidationError("max_candidates must be a positive integer")
    return selected


def _month(value: Any, field_name: str) -> int:
    """Validate a 1-12 month value."""

    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError as exc:
            raise SchemaValidationError(f"{field_name} must be an integer") from exc
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value < 1 or value > 12:
        raise SchemaValidationError(f"{field_name} must be between 1 and 12")
    return value


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
    "FESTIVAL_EXCLUDED_THEME_LABELS",
    "FestivalCandidate",
    "FestivalSeedResult",
    "build_attraction_filter",
    "build_attraction_search_request",
    "normalize_attraction_candidate",
    "normalize_festival_candidate",
]
