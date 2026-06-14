"""Intent Agent deterministic input normalization.

Planned responsibility:
- normalize API structured input,
- split raw and soft preference queries,
- keep core API fields from being re-inferred from natural language.
- skip LLM extraction for empty or too-short natural-language input and
  continue from valid structured API fields.

Task 2.1 implements only deterministic API input normalization and theme
mapping. Natural-language extraction, LLM structured output, retrieval, and
planning stay out of this module for now.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from lovv_agent.config import DEFAULT_MIN_NATURAL_LANGUAGE_QUERY_CHARS
from lovv_agent.models.schemas import CandidateEvidenceInput, GeoPoint, SchemaValidationError

NODE_NAME = "intent_agent"

RESPONSIBILITY = "Normalize request input into Candidate Evidence input."

OUT_OF_SCOPE = (
    "city_search",
    "scoring",
    "itinerary_generation",
)

ENTRY_TYPES: tuple[str, ...] = ("map_marker", "chat", "home_recommendation")
COUNTRY_CODES: tuple[str, ...] = ("KR", "JP")
TRIP_TYPES: tuple[str, ...] = ("daytrip", "2d1n", "3d2n", "4d3n", "5d4n")

THEME_LABELS: dict[str, str] = {
    "sea_coast": "바다·해안",
    "nature_trekking": "자연·트레킹",
    "food_local": "미식·노포",
    "history_tradition": "역사·전통",
    "art_sense": "예술·감성",
    "healing_rest": "온천·휴양",
}

EXTERNAL_LINK_THEME_IDS: frozenset[str] = frozenset({"food_local"})
LEGACY_FESTIVAL_THEME_IDS: frozenset[str] = frozenset(
    {
        "festival_event",
        "festival",
        "축제·이벤트",
    },
)

UNSUPPORTED_CONDITION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("숙소 가격/예약 가능 여부", ("숙소 가격", "호텔 가격", "객실", "예약 가능", "예약가능")),
    ("실시간 혼잡도", ("실시간 혼잡", "혼잡도", "붐비는지 실시간", "사람 많은지")),
    ("실시간 영업 여부", ("실시간 영업", "영업 중", "오늘 영업", "오픈 여부")),
    ("주차 보장", ("주차 보장", "주차 자리", "주차 가능 보장")),
    ("날씨/기상 대체", ("날씨", "비 오면", "비오면", "우천")),
)

SOFT_PREFERENCE_KEYWORDS: tuple[str, ...] = (
    "감성",
    "덜 붐",
    "붐비지",
    "사진",
    "산책",
    "여유",
    "전망",
    "조용",
    "편안",
    "한적",
    "힐링",
)

TRIP_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "daytrip": ("당일", "당일치기"),
    "2d1n": ("1박 2일", "1박2일"),
    "3d2n": ("2박 3일", "2박3일"),
    "4d3n": ("3박 4일", "3박4일"),
    "5d4n": ("4박 5일", "4박5일"),
}

_MISSING = object()


@dataclass(frozen=True, slots=True)
class ThemeMappingResult:
    """Normalized theme labels and routing groups derived from API theme IDs."""

    canonical_theme_ids: tuple[str, ...]
    active_required_themes: tuple[str, ...]
    searchable_place_themes: tuple[str, ...]
    external_link_themes: tuple[str, ...]
    include_festivals: bool
    handoff_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NaturalLanguageExtraction:
    """Conservative extraction result from ``naturalLanguageQuery``."""

    cleaned_raw_query: str = ""
    soft_preference_query: str = ""
    unsupported_conditions: tuple[str, ...] = ()
    handoff_notes: tuple[str, ...] = ()
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class IntentNormalizationResult:
    """Deterministic Intent output before LLM-assisted extraction is added."""

    needs_clarification: bool
    clarifying_question: str | None
    extracted_inputs: dict[str, Any] = field(default_factory=dict)
    candidate_evidence_input: CandidateEvidenceInput | None = None
    active_required_themes: tuple[str, ...] = ()
    searchable_place_themes: tuple[str, ...] = ()
    external_link_themes: tuple[str, ...] = ()
    cleaned_raw_query: str = ""
    soft_preference_query: str = ""
    unsupported_conditions: tuple[str, ...] = ()
    handoff_notes: tuple[str, ...] = ()
    fulfilled_matrix: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.needs_clarification, bool):
            raise SchemaValidationError("needs_clarification must be a boolean")
        if self.needs_clarification and not self.clarifying_question:
            raise SchemaValidationError(
                "clarifying_question is required when clarification is needed",
            )
        if not self.needs_clarification and self.candidate_evidence_input is None:
            raise SchemaValidationError(
                "candidate_evidence_input is required when clarification is not needed",
            )
        if self.fulfilled_matrix:
            allowed = {"X", "O", "△", "N/A"}
            if set(self.fulfilled_matrix) != {"evidence", "festival", "planning"}:
                raise SchemaValidationError("fulfilled_matrix has invalid keys")
            invalid = set(self.fulfilled_matrix.values()) - allowed
            if invalid:
                raise SchemaValidationError("fulfilled_matrix has invalid statuses")


def normalize_recommendation_request(
    payload: Mapping[str, Any],
) -> IntentNormalizationResult:
    """Normalize the MVP ``POST /recommendations`` request for Candidate Evidence.

    The function deliberately does not inspect ``naturalLanguageQuery`` to infer
    core fields. It only validates API structured input, maps canonical theme
    IDs to Candidate Evidence labels, and prepares the deterministic handoff
    payload used by downstream graph nodes.
    """

    try:
        request = _validate_request_payload(payload)
        theme_mapping = map_theme_ids(
            request["themes"],
            include_festivals=request["includeFestivals"],
        )
        _validate_theme_count(theme_mapping.canonical_theme_ids)
        language_extraction = extract_natural_language_query(
            request["naturalLanguageQuery"],
            structured_request=request,
        )
        execution_mode = resolve_execution_mode(
            request["destinationId"],
            theme_mapping.include_festivals,
        )

        candidate_input = CandidateEvidenceInput(
            country=request["country"],
            travel_month=request["travelMonth"],
            travel_year=request["travelYear"],
            trip_type=request["tripType"],
            destination_id=request["destinationId"],
            active_required_themes=theme_mapping.active_required_themes,
            cleaned_raw_query=language_extraction.cleaned_raw_query,
            soft_preference_query=language_extraction.soft_preference_query,
            unsupported_conditions=language_extraction.unsupported_conditions,
            user_location=request["user_location"],
            include_festivals=theme_mapping.include_festivals,
            execution_mode=execution_mode,
            fixed_city_id=request["destinationId"],
            city_anchor=None,
        )
    except SchemaValidationError as exc:
        return _clarification_result(str(exc))

    extracted_inputs = {
        "entryType": request["entryType"],
        "country": request["country"],
        "travelMonth": request["travelMonth"],
        "travelYear": request["travelYear"],
        "tripType": request["tripType"],
        "destinationId": request["destinationId"],
        "themes": theme_mapping.canonical_theme_ids,
        "includeFestivals": theme_mapping.include_festivals,
        "naturalLanguageQuery": request["naturalLanguageQuery"],
        "user_location": (
            asdict(request["user_location"])
            if request["user_location"] is not None
            else None
        ),
        "execution_mode": execution_mode,
        "cleaned_raw_query": language_extraction.cleaned_raw_query,
        "soft_preference_query": language_extraction.soft_preference_query,
        "unsupported_conditions": language_extraction.unsupported_conditions,
    }

    return IntentNormalizationResult(
        needs_clarification=False,
        clarifying_question=None,
        extracted_inputs=extracted_inputs,
        candidate_evidence_input=candidate_input,
        active_required_themes=theme_mapping.active_required_themes,
        searchable_place_themes=theme_mapping.searchable_place_themes,
        external_link_themes=theme_mapping.external_link_themes,
        cleaned_raw_query=language_extraction.cleaned_raw_query,
        soft_preference_query=language_extraction.soft_preference_query,
        unsupported_conditions=language_extraction.unsupported_conditions,
        handoff_notes=theme_mapping.handoff_notes + language_extraction.handoff_notes,
        fulfilled_matrix=_initial_fulfilled_matrix(theme_mapping.include_festivals),
    )


def map_theme_ids(
    theme_ids: Sequence[Any],
    *,
    include_festivals: bool,
) -> ThemeMappingResult:
    """Map API canonical theme IDs into Candidate Evidence theme labels."""

    if isinstance(theme_ids, str) or not isinstance(theme_ids, Sequence):
        raise SchemaValidationError("themes must be a list of canonical theme IDs")
    if not isinstance(include_festivals, bool):
        raise SchemaValidationError("includeFestivals must be a boolean")

    canonical_ids: list[str] = []
    handoff_notes: list[str] = []
    normalized_include_festivals = include_festivals

    for raw_theme in theme_ids:
        theme_id = _required_text(raw_theme, "themes")
        if theme_id in LEGACY_FESTIVAL_THEME_IDS:
            normalized_include_festivals = True
            handoff_notes.append(
                "legacy festival theme was normalized to includeFestivals=true",
            )
            continue
        if theme_id not in THEME_LABELS:
            raise SchemaValidationError(f"unsupported canonical theme: {theme_id}")
        if theme_id not in canonical_ids:
            canonical_ids.append(theme_id)

    active_required_themes = tuple(THEME_LABELS[theme_id] for theme_id in canonical_ids)
    searchable_place_themes = tuple(
        THEME_LABELS[theme_id]
        for theme_id in canonical_ids
        if theme_id not in EXTERNAL_LINK_THEME_IDS
    )
    external_link_themes = tuple(
        THEME_LABELS[theme_id]
        for theme_id in canonical_ids
        if theme_id in EXTERNAL_LINK_THEME_IDS
    )

    return ThemeMappingResult(
        canonical_theme_ids=tuple(canonical_ids),
        active_required_themes=active_required_themes,
        searchable_place_themes=searchable_place_themes,
        external_link_themes=external_link_themes,
        include_festivals=normalized_include_festivals,
        handoff_notes=tuple(dict.fromkeys(handoff_notes)),
    )


def resolve_execution_mode(destination_id: str | None, include_festivals: bool) -> str:
    """Return the Candidate Evidence execution mode for structured input."""

    if destination_id is not None:
        return "anchored_place_search"
    if include_festivals:
        return "festival_seeded_city_discovery"
    return "city_discovery"


def extract_natural_language_query(
    natural_language_query: str,
    *,
    structured_request: Mapping[str, Any],
    min_natural_language_query_chars: int = DEFAULT_MIN_NATURAL_LANGUAGE_QUERY_CHARS,
) -> NaturalLanguageExtraction:
    """Extract only safe supplementary signals from natural-language input.

    This MVP extractor is deliberately conservative until the structured-output
    LLM adapter is added. It never fills or overrides core structured fields.
    """

    query = _free_text(natural_language_query, "naturalLanguageQuery")
    if len(query) < min_natural_language_query_chars:
        return NaturalLanguageExtraction(skipped=True)

    clauses = _split_query_clauses(query)
    unsupported_conditions = _extract_unsupported_conditions(clauses)
    unsupported_clauses = tuple(
        clause
        for clause in clauses
        if _clause_contains_unsupported_condition(clause)
    )
    supported_clauses = tuple(
        clause
        for clause in clauses
        if clause not in unsupported_clauses
    )
    soft_clauses = tuple(
        clause
        for clause in supported_clauses
        if any(keyword in clause for keyword in SOFT_PREFERENCE_KEYWORDS)
    )
    handoff_notes = _detect_structured_field_conflicts(query, structured_request)

    return NaturalLanguageExtraction(
        cleaned_raw_query=" ".join(supported_clauses).strip(),
        soft_preference_query=" ".join(soft_clauses).strip(),
        unsupported_conditions=unsupported_conditions,
        handoff_notes=handoff_notes,
        skipped=False,
    )


def _validate_request_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the structured MVP recommendation request."""

    if not isinstance(payload, Mapping):
        raise SchemaValidationError("request payload must be an object")

    entry_type = _choice(_get(payload, "entryType", "entry_type"), ENTRY_TYPES, "entryType")
    destination_id = _optional_text(
        _get(payload, "destinationId", "destination_id", default=None),
        "destinationId",
    )
    if entry_type == "map_marker" and destination_id is None:
        raise SchemaValidationError("destinationId is required for map_marker entryType")

    country = _choice(_get(payload, "country"), COUNTRY_CODES, "country")
    travel_year = _positive_int(_get(payload, "travelYear", "travel_year"), "travelYear")
    travel_month = _month(_get(payload, "travelMonth", "travel_month"), "travelMonth")
    trip_type = _choice(_get(payload, "tripType", "trip_type"), TRIP_TYPES, "tripType")
    themes = _get(payload, "themes")
    include_festivals = _bool(
        _get(payload, "includeFestivals", "include_festivals"),
        "includeFestivals",
    )
    natural_language_query = _free_text(
        _get(payload, "naturalLanguageQuery", "natural_language_query", default=""),
        "naturalLanguageQuery",
    )
    user_location = _normalize_user_location(
        _get(payload, "userLocation", "user_location", default=None),
    )

    return {
        "entryType": entry_type,
        "destinationId": destination_id,
        "country": country,
        "travelYear": travel_year,
        "travelMonth": travel_month,
        "tripType": trip_type,
        "themes": themes,
        "includeFestivals": include_festivals,
        "naturalLanguageQuery": natural_language_query,
        "user_location": user_location,
    }


def _split_query_clauses(query: str) -> tuple[str, ...]:
    """Split a query into lightweight clauses without semantic rewriting."""

    normalized = re.sub(r"\s+", " ", query).strip()
    if not normalized:
        return ()
    clauses = re.split(r"[.!?。！？\n]+|(?:\s*,\s*)", normalized)
    return tuple(clause.strip() for clause in clauses if clause.strip())


def _extract_unsupported_conditions(clauses: tuple[str, ...]) -> tuple[str, ...]:
    """Return normalized unsupported conditions found in natural-language clauses."""

    conditions: list[str] = []
    for clause in clauses:
        for condition, keywords in UNSUPPORTED_CONDITION_PATTERNS:
            if any(keyword in clause for keyword in keywords) and condition not in conditions:
                conditions.append(condition)
    return tuple(conditions)


def _clause_contains_unsupported_condition(clause: str) -> bool:
    """Return whether a query clause asks for currently unsupported live data."""

    return any(
        keyword in clause
        for _, keywords in UNSUPPORTED_CONDITION_PATTERNS
        for keyword in keywords
    )


def _detect_structured_field_conflicts(
    query: str,
    structured_request: Mapping[str, Any],
) -> tuple[str, ...]:
    """Record explicit change requests without changing structured fields."""

    notes: list[str] = []
    country = structured_request["country"]
    if country == "KR" and _contains_country_change_request(query, "일본", "JP"):
        notes.append("natural language requests country change to JP")
    if country == "JP" and _contains_country_change_request(query, "한국", "KR"):
        notes.append("natural language requests country change to KR")

    requested_months = {
        int(match)
        for match in re.findall(r"(?<!\d)(1[0-2]|[1-9])\s*월", query)
    }
    travel_month = structured_request["travelMonth"]
    if any(month != travel_month for month in requested_months):
        notes.append("natural language mentions a travelMonth different from structured input")

    requested_trip_types = _detect_trip_type_mentions(query)
    trip_type = structured_request["tripType"]
    if any(requested != trip_type for requested in requested_trip_types):
        notes.append("natural language mentions a tripType different from structured input")

    include_festivals = structured_request["includeFestivals"]
    if "축제" in query or "행사" in query or "이벤트" in query:
        if include_festivals and any(token in query for token in ("빼", "제외", "말고")):
            notes.append("natural language requests festival exclusion")
        if not include_festivals and not any(token in query for token in ("빼", "제외", "말고")):
            notes.append("natural language requests festival inclusion")

    return tuple(dict.fromkeys(notes))


def _contains_country_change_request(query: str, country_word: str, country_code: str) -> bool:
    """Return whether the query explicitly asks to change the country."""

    if country_word not in query and country_code not in query:
        return False
    if any(blocker in query for blocker in (f"{country_word} 말고", f"{country_word} 제외")):
        return False
    return any(token in query for token in ("가고", "바꿔", "변경", "수정", "추천"))


def _detect_trip_type_mentions(query: str) -> tuple[str, ...]:
    """Detect explicit trip-type mentions from Korean natural language."""

    detected: list[str] = []
    for trip_type, keywords in TRIP_TYPE_KEYWORDS.items():
        if any(keyword in query for keyword in keywords):
            detected.append(trip_type)
    return tuple(detected)


def _validate_theme_count(canonical_theme_ids: tuple[str, ...]) -> None:
    """Validate API canonical theme count after removing legacy festival tokens."""

    if len(canonical_theme_ids) < 1:
        raise SchemaValidationError("themes must include at least one canonical travel theme")
    if len(canonical_theme_ids) > 3:
        raise SchemaValidationError("themes must include at most three canonical travel themes")


def _normalize_user_location(value: Any) -> GeoPoint | None:
    """Normalize optional API userLocation into the internal GeoPoint type."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SchemaValidationError("userLocation must be an object when provided")
    return GeoPoint.from_mapping(value)


def _initial_fulfilled_matrix(include_festivals: bool) -> dict[str, str]:
    """Return the initial Supervisor matrix after Intent normalization."""

    return {
        "evidence": "X",
        "festival": "X" if include_festivals else "N/A",
        "planning": "X",
    }


def _clarification_result(reason: str) -> IntentNormalizationResult:
    """Return a safe clarification result for invalid structured input."""

    return IntentNormalizationResult(
        needs_clarification=True,
        clarifying_question=f"추천 생성을 위해 구조화 입력을 보완해 주세요: {reason}",
        handoff_notes=(reason,),
        fulfilled_matrix={"evidence": "X", "festival": "N/A", "planning": "X"},
    )


def _get(payload: Mapping[str, Any], *keys: str, default: Any = _MISSING) -> Any:
    """Return the first present key, supporting camelCase and snake_case inputs."""

    for key in keys:
        if key in payload:
            return payload[key]
    if default is not _MISSING:
        return default
    joined = " or ".join(keys)
    raise SchemaValidationError(f"{joined} is required in structured API input")


def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty string."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    """Validate optional text and normalize blank values to None."""

    if value is None:
        return None
    return _required_text(value, field_name)


def _free_text(value: Any, field_name: str) -> str:
    """Validate free text where empty values are allowed."""

    if value is None:
        return ""
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string or null")
    return value.strip()


def _choice(value: Any, allowed: tuple[str, ...], field_name: str) -> str:
    """Validate an enum-like API field."""

    normalized = _required_text(value, field_name)
    if normalized not in allowed:
        allowed_values = ", ".join(allowed)
        raise SchemaValidationError(f"{field_name} must be one of: {allowed_values}")
    return normalized


def _positive_int(value: Any, field_name: str) -> int:
    """Validate a positive integer without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value < 1:
        raise SchemaValidationError(f"{field_name} must be positive")
    return value


def _month(value: Any, field_name: str) -> int:
    """Validate month range."""

    parsed = _positive_int(value, field_name)
    if parsed > 12:
        raise SchemaValidationError(f"{field_name} must be between 1 and 12")
    return parsed


def _bool(value: Any, field_name: str) -> bool:
    """Validate a strict boolean field."""

    if not isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a boolean")
    return value


__all__ = [
    "COUNTRY_CODES",
    "ENTRY_TYPES",
    "EXTERNAL_LINK_THEME_IDS",
    "LEGACY_FESTIVAL_THEME_IDS",
    "NODE_NAME",
    "OUT_OF_SCOPE",
    "RESPONSIBILITY",
    "THEME_LABELS",
    "TRIP_TYPES",
    "IntentNormalizationResult",
    "NaturalLanguageExtraction",
    "ThemeMappingResult",
    "extract_natural_language_query",
    "map_theme_ids",
    "normalize_recommendation_request",
    "resolve_execution_mode",
]
