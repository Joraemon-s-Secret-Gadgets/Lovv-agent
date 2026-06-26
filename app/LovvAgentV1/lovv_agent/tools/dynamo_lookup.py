"""DynamoLookupTool helpers for Lovv domain data reads.

This tool owns DynamoDB-backed lookups that are not S3 Vector search:
festival seed lookup before attraction retrieval and detail enrichment after
Planner final placement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from lovv_agent.config import SearchBudgetSettings
from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.repositories.dynamodb import DynamoDbRepository
from lovv_agent.tools.destination_search import AttractionCandidate

TOOL_NAME = "DynamoLookupTool"

RESPONSIBILITY = "Read festival seed candidates and final item details from DynamoDB."


# Festival seed record는 discovery hint이며 최종 Planner 배치가 아니다.
@dataclass(frozen=True, slots=True)
class FestivalCandidate:
    """Normalized festival seed candidate from DynamoDB."""

    festival_id: str
    name: str
    country: str
    city_id: str
    city_name: str | None
    month: int
    theme: str | None
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
    def seed_city_ids(self) -> tuple[str, ...]:
        """Return unique seed city ids in candidate order."""

        seen: set[str] = set()
        city_ids: list[str] = []
        for candidate in self.candidates:
            if candidate.city_id in seen:
                continue
            seen.add(candidate.city_id)
            city_ids.append(candidate.city_id)
        return tuple(city_ids)

    @property
    def seeded_city_ids(self) -> tuple[str, ...]:
        """Backward-compatible alias for ``seed_city_ids``."""

        return self.seed_city_ids

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable seed lookup payload."""

        return {
            "status": self.status,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "seed_city_ids": list(self.seed_city_ids),
            "failure_signals": list(self.failure_signals),
            "needs_clarification": self.needs_clarification,
        }


@dataclass(frozen=True, slots=True)
class DetailEnrichmentWarning:
    """Structured warning emitted during final item detail enrichment."""

    code: str
    place_id: str
    key: str
    message: str
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable detail enrichment warning."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class DetailEnrichmentResult:
    """Final placed candidates after optional DynamoDB detail enrichment."""

    places: tuple[AttractionCandidate, ...]
    warnings: tuple[DetailEnrichmentWarning, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable detail enrichment result."""

        return {
            "places": [place.to_dict() for place in self.places],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class DynamoLookupTool:
    """DynamoDB lookup facade over an injected repository."""

    dynamodb: DynamoDbRepository
    search_budget: SearchBudgetSettings

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

        return search_festival_city_seeds(
            country=country,
            travel_month=travel_month,
            theme_pool=theme_pool,
            city_id=city_id,
            max_candidates=max_candidates,
            dynamodb=self.dynamodb,
            search_budget=self.search_budget,
        )

    def enrich_final_places(
        self,
        final_places: Sequence[AttractionCandidate],
    ) -> DetailEnrichmentResult:
        """Attach DynamoDB details after Planner final placement."""

        return enrich_final_places(final_places, dynamodb=self.dynamodb)

    def city_visitor_stats(
        self,
        city_ids: Sequence[str],
        travel_month: int,
    ) -> dict[str, float | None]:
        """Fetch per-city monthly visitor totals (congestion proxy) in one batch."""

        return self.dynamodb.batch_get_city_visitor_stats(
            city_ids=city_ids,
            travel_month=travel_month,
        )


def search_festival_city_seeds(
    *,
    country: str,
    travel_month: int,
    theme_pool: Sequence[str],
    city_id: str | None = None,
    max_candidates: int | None = None,
    dynamodb: DynamoDbRepository,
    search_budget: SearchBudgetSettings,
) -> FestivalSeedResult:
    """Find month-matching festival candidates before attraction search."""

    normalized_country = _required_text(country, "country")
    normalized_month = _month(travel_month, "travel_month")
    normalized_city_id = _optional_text(city_id, "city_id")
    # Festival documents do not currently persist travel-theme fields. Keep the
    # argument for caller compatibility, but do not use it as a filter.
    del theme_pool
    limit = _resolve_max_festival_candidates(max_candidates, search_budget)
    response = dynamodb.query_festival_candidates(
        country=normalized_country,
        travel_month=normalized_month,
        city_id=normalized_city_id,
        limit=limit,
    )
    # detail 문서에는 country 속성이 없거나(지역 단위 배포) 표기가 제각각이라
    # (KR/대한민국/Korea 등) country 동등 비교는 멀쩡한 축제까지 떨어뜨리는 footgun이다.
    # 따라서 country는 정규화용으로만 주입하고 실제 필터는 month/(선택 city)로만 한다.
    candidates = tuple(
        candidate
        for item in _extract_dynamodb_items(response)
        if (
            candidate := normalize_festival_candidate(
                _with_default_country(item, normalized_country),
            )
        ).month == normalized_month
        and (normalized_city_id is None or candidate.city_id == normalized_city_id)
    )[:limit]
    if candidates:
        return FestivalSeedResult(status="ok", candidates=candidates)
    if normalized_city_id is not None:
        return _festival_seed_failure("no_festival_in_anchor_city")
    return _festival_seed_failure("no_festival_city_seed")


def enrich_final_places(
    final_places: Sequence[AttractionCandidate],
    *,
    dynamodb: DynamoDbRepository,
) -> DetailEnrichmentResult:
    """Enrich final itinerary places and isolate detail lookup warnings."""

    places: list[AttractionCandidate] = []
    warnings: list[DetailEnrichmentWarning] = []
    for candidate in final_places:
        pk = candidate.ddb_pk
        sk = candidate.ddb_sk
        if pk is None or sk is None:
            places.append(replace(candidate, details=None))
            warnings.append(
                _detail_enrichment_warning(
                    "missing_detail_key",
                    candidate,
                    "Missing ddb_pk or ddb_sk; details remain null.",
                ),
            )
            continue

        try:
            response = dynamodb.get_detail_item(pk=pk, sk=sk)
            details = _extract_detail_item(response)
        except Exception as exc:
            places.append(replace(candidate, details=None))
            warnings.append(
                _detail_enrichment_warning(
                    "dynamodb_detail_failure",
                    candidate,
                    "DynamoDB detail lookup failed; details remain null.",
                    error_type=type(exc).__name__,
                ),
            )
            continue

        if details is None:
            places.append(replace(candidate, details=None))
            warnings.append(
                _detail_enrichment_warning(
                    "missing_detail_item",
                    candidate,
                    "DynamoDB returned no detail item; details remain null.",
                ),
            )
            continue

        places.append(replace(candidate, details=details))

    return DetailEnrichmentResult(
        places=tuple(places),
        warnings=tuple(warnings),
    )


def normalize_festival_candidate(item: Mapping[str, Any]) -> FestivalCandidate:
    """Normalize one DynamoDB festival seed item."""

    normalized = _plain_dynamodb_item(item)
    return FestivalCandidate(
        festival_id=_required_text(
            _first_present(normalized, "festival_id", "id", "entity_id", "content_id"),
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
        theme=_optional_text(
            _first_optional(normalized, "theme", "travel_theme"),
            "theme",
        ),
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


def _with_default_country(item: Mapping[str, Any], country: str) -> dict[str, Any]:
    """Inject the requested country when the detail item omits the attribute.

    Normalized detail documents do not persist a country attribute (regional
    deployment), so we default it to the requested country before candidate
    normalization. A plain string is safe because ``_unwrap_dynamodb_value``
    passes non-mapping values through unchanged.
    """

    existing = item.get("country")
    if isinstance(existing, Mapping) and str(existing.get("S", "")).strip():
        return dict(item)
    if isinstance(existing, str) and existing.strip():
        return dict(item)
    enriched = dict(item)
    enriched["country"] = country
    return enriched


def _plain_dynamodb_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a plain or DynamoDB AttributeValue item to plain Python values."""

    if not isinstance(item, Mapping):
        raise SchemaValidationError("dynamodb item must be a mapping")
    return {str(key): _unwrap_dynamodb_value(value) for key, value in item.items()}


def _extract_detail_item(response: Mapping[str, Any]) -> dict[str, Any] | None:
    """Deserialize a DynamoDB GetItem detail response."""

    if not isinstance(response, Mapping):
        raise SchemaValidationError("dynamodb detail response must be a mapping")
    item = response.get("Item")
    if item is None:
        return None
    if not isinstance(item, Mapping):
        raise SchemaValidationError("dynamodb detail response.Item must be a mapping")
    return _normalize_detail_overview(_plain_dynamodb_item(item))


# 수집 파이프라인은 TourAPI overview 텍스트를 detail item의 `description` 속성으로
# 적재한다. Planner/Explanation 계층은 공개 설명 필드로 `overview`를 읽으므로,
# detail item이 agent 경계로 들어오는 이 지점에서 한 번만 별칭을 채운다.
def _normalize_detail_overview(detail: dict[str, Any]) -> dict[str, Any]:
    """Alias the persisted `description` text to the `overview` field readers expect."""

    existing = detail.get("overview")
    if isinstance(existing, str) and existing.strip():
        return detail
    description = detail.get("description")
    if isinstance(description, str) and description.strip():
        detail["overview"] = description
    return detail


def _detail_enrichment_warning(
    code: str,
    candidate: AttractionCandidate,
    message: str,
    *,
    error_type: str | None = None,
) -> DetailEnrichmentWarning:
    """Build a structured final item detail enrichment warning."""

    return DetailEnrichmentWarning(
        code=code,
        place_id=candidate.place_id,
        key=candidate.key,
        message=message,
        error_type=error_type,
    )


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


__all__ = [
    "DetailEnrichmentResult",
    "DetailEnrichmentWarning",
    "DynamoLookupTool",
    "FestivalCandidate",
    "FestivalSeedResult",
    "RESPONSIBILITY",
    "TOOL_NAME",
    "enrich_final_places",
    "normalize_festival_candidate",
    "search_festival_city_seeds",
]
