"""Deterministic scoring helpers for Candidate Evidence.

ScoringTool owns pure Python score calculations only. It never calls AWS, an
LLM, or itinerary generation code; callers provide every runtime signal such as
candidate distances, user location, and congestion indexes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.tools.destination_search import (
    ATTRACTION_ENTITY_TYPE,
    FESTIVAL_EXCLUDED_THEME_LABELS,
    GOURMET_EXTERNAL_THEME_LABELS,
)

TOOL_NAME = "ScoringTool"

RESPONSIBILITY = "Compute deterministic place and city score breakdowns."

EARTH_RADIUS_KM = 6371.0088
THEME_MATCH_BONUS = 0.2
SOURCE_QUALITY_FIELD_BONUS = 0.05
LOCAL_DISTANCE_PENALTY_PER_KM = 0.005
USER_DISTANCE_PENALTY_PER_100KM = 0.05
SCALE_CORRECTION_WEIGHT = 0.02
CANDIDATE_SUFFICIENCY_THRESHOLD = 5
CANDIDATE_SUFFICIENCY_BONUS = 0.1


@dataclass(frozen=True, slots=True)
class PlaceScoreResult:
    """Scored attraction candidate with internal audit components."""

    place: Any
    place_id: str
    title: str | None
    city_id: str | None
    theme_tags: tuple[str, ...]
    latitude: float | None
    longitude: float | None
    place_score: float
    score_components: dict[str, float]
    scored: bool = True
    exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable scoring result for internal audit."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """City score breakdown fields required by the agent spec."""

    semantic_evidence: float
    theme_coverage: float
    theme_balance: float
    scale_correction: float
    candidate_sufficiency: float
    distance_penalty: float
    congestion_penalty: float

    def to_dict(self) -> dict[str, float]:
        """Return a serializable city score breakdown."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class CityScoreResult:
    """Deterministic city ranking result with selected top evidence ids."""

    city_id: str
    city_score: float
    breakdown: ScoreBreakdown
    top_place_ids: tuple[str, ...]
    candidate_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable city score result."""

        return {
            "city_id": self.city_id,
            "city_score": self.city_score,
            "score_breakdown": self.breakdown.to_dict(),
            "top_place_ids": list(self.top_place_ids),
            "candidate_count": self.candidate_count,
        }


@dataclass(frozen=True, slots=True)
class ScoringTool:
    """Facade for deterministic place and city scoring."""

    def score_place(
        self,
        candidate: Any,
        active_themes: Sequence[str],
        *,
        reference_location: Any | None = None,
    ) -> PlaceScoreResult:
        """Score one attraction candidate."""

        return score_place(
            candidate,
            active_themes,
            reference_location=reference_location,
        )

    def score_city(
        self,
        *,
        city_id: str,
        places: Sequence[Any],
        active_themes: Sequence[str],
        user_location: Any | None = None,
        primary_budget: int = CANDIDATE_SUFFICIENCY_THRESHOLD,
        congestion_index: float = 0.0,
        w_cong: float = 0.0,
    ) -> CityScoreResult:
        """Score one city from already scored place evidence."""

        return score_city(
            city_id=city_id,
            places=places,
            active_themes=active_themes,
            user_location=user_location,
            primary_budget=primary_budget,
            congestion_index=congestion_index,
            w_cong=w_cong,
        )


def score_place(
    candidate: Any,
    active_themes: Sequence[str],
    *,
    reference_location: Any | None = None,
) -> PlaceScoreResult:
    """Score one attraction candidate and return internal audit components."""

    entity_type = _optional_text(_candidate_value(candidate, "entity_type", "entityType"))
    place_id = _place_id(candidate)
    title = _optional_text(_candidate_value(candidate, "title", "name"))
    city_id = _optional_text(_candidate_value(candidate, "city_id", "cityId"))
    theme_tags = _string_tuple(
        _candidate_value(candidate, "theme_tags", "themeTags"),
        "theme_tags",
    )
    latitude = _optional_float(_candidate_value(candidate, "latitude", "lat"))
    longitude = _optional_float(_candidate_value(candidate, "longitude", "lng", "lon"))

    if entity_type != ATTRACTION_ENTITY_TYPE:
        return PlaceScoreResult(
            place=candidate,
            place_id=place_id,
            title=title,
            city_id=city_id,
            theme_tags=theme_tags,
            latitude=latitude,
            longitude=longitude,
            place_score=0.0,
            score_components=_zero_place_components(),
            scored=False,
            exclusion_reason=f"unsupported_entity_type:{entity_type or 'missing'}",
        )

    scoreable_themes = _scoreable_themes(active_themes)
    raw_similarity = _similarity_from_distance(_candidate_value(candidate, "distance"))
    soft_similarity = _similarity_from_distance(
        _candidate_value(candidate, "soft_distance", "softDistance"),
    )
    theme_match_score = (
        THEME_MATCH_BONUS
        if set(theme_tags).intersection(scoreable_themes)
        else 0.0
    )
    source_quality_score = _source_quality_score(
        title=title,
        theme_tags=theme_tags,
        city_id=city_id,
        city_name=_optional_text(_candidate_value(candidate, "city_name_ko", "cityName")),
        latitude=latitude,
        longitude=longitude,
    )
    local_distance_penalty = _local_distance_penalty(
        latitude=latitude,
        longitude=longitude,
        reference_location=reference_location,
    )
    place_score = max(
        raw_similarity
        + soft_similarity
        + theme_match_score
        + source_quality_score
        - local_distance_penalty,
        0.0,
    )
    components = {
        "raw_similarity": _round4(raw_similarity),
        "soft_similarity": _round4(soft_similarity),
        "theme_match_score": _round4(theme_match_score),
        "source_quality_score": _round4(source_quality_score),
        "local_distance_penalty": _round4(local_distance_penalty),
    }
    return PlaceScoreResult(
        place=candidate,
        place_id=place_id,
        title=title,
        city_id=city_id,
        theme_tags=theme_tags,
        latitude=latitude,
        longitude=longitude,
        place_score=_round4(place_score),
        score_components=components,
    )


def score_city(
    *,
    city_id: str,
    places: Sequence[Any],
    active_themes: Sequence[str],
    user_location: Any | None = None,
    primary_budget: int = CANDIDATE_SUFFICIENCY_THRESHOLD,
    congestion_index: float = 0.0,
    w_cong: float = 0.0,
) -> CityScoreResult:
    """Score a city from scored place evidence and runtime signals."""

    normalized_city_id = _required_text(city_id, "city_id")
    budget = _positive_int(primary_budget, "primary_budget")
    scored_places = tuple(
        place for place in (_coerce_scored_place(item) for item in places) if place.scored
    )
    if not scored_places:
        return CityScoreResult(
            city_id=normalized_city_id,
            city_score=0.0,
            breakdown=_zero_city_breakdown(),
            top_place_ids=(),
            candidate_count=0,
        )

    top_places = tuple(
        sorted(scored_places, key=lambda place: place.place_score, reverse=True)[:budget],
    )
    scoreable_themes = _scoreable_themes(active_themes)
    semantic_evidence = sum(place.place_score for place in top_places) / budget
    theme_coverage = _theme_coverage(top_places, scoreable_themes)
    theme_balance = _theme_balance(top_places, scoreable_themes)
    scale_correction = SCALE_CORRECTION_WEIGHT * math.log(len(top_places) + 1)
    candidate_sufficiency = (
        CANDIDATE_SUFFICIENCY_BONUS
        if len(top_places) >= CANDIDATE_SUFFICIENCY_THRESHOLD
        else 0.0
    )
    distance_penalty = _city_distance_penalty(top_places, user_location)
    congestion_penalty = _numeric(congestion_index, "congestion_index") * _numeric(
        w_cong,
        "w_cong",
    )
    city_score = (
        semantic_evidence
        + theme_coverage
        + theme_balance
        - scale_correction
        + candidate_sufficiency
        - distance_penalty
        - congestion_penalty
    )
    breakdown = ScoreBreakdown(
        semantic_evidence=_round4(semantic_evidence),
        theme_coverage=_round4(theme_coverage),
        theme_balance=_round4(theme_balance),
        scale_correction=_round4(scale_correction),
        candidate_sufficiency=_round4(candidate_sufficiency),
        distance_penalty=_round4(distance_penalty),
        congestion_penalty=_round4(congestion_penalty),
    )
    return CityScoreResult(
        city_id=normalized_city_id,
        city_score=_round4(city_score),
        breakdown=breakdown,
        top_place_ids=tuple(place.place_id for place in top_places),
        candidate_count=len(scored_places),
    )


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return great-circle distance between two WGS84 points in kilometers."""

    first_lat = math.radians(_numeric(lat1, "lat1"))
    first_lon = math.radians(_numeric(lon1, "lon1"))
    second_lat = math.radians(_numeric(lat2, "lat2"))
    second_lon = math.radians(_numeric(lon2, "lon2"))
    delta_lat = second_lat - first_lat
    delta_lon = second_lon - first_lon
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(first_lat)
        * math.cos(second_lat)
        * math.sin(delta_lon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(haversine))


def _coerce_scored_place(place: Any) -> PlaceScoreResult:
    """Convert dict/object scored place payloads into ``PlaceScoreResult``."""

    if isinstance(place, PlaceScoreResult):
        return place
    if isinstance(place, Mapping):
        score = _optional_float(_mapping_get(place, "place_score", "score"))
        if score is None:
            raise SchemaValidationError("place_score is required for city scoring")
        return PlaceScoreResult(
            place=place,
            place_id=_required_text(_mapping_get(place, "place_id", "placeId"), "place_id"),
            title=_optional_text(_mapping_get(place, "title", "name", default=None)),
            city_id=_optional_text(_mapping_get(place, "city_id", "cityId", default=None)),
            theme_tags=_string_tuple(
                _mapping_get(place, "theme_tags", "themeTags", default=()),
                "theme_tags",
            ),
            latitude=_optional_float(_mapping_get(place, "latitude", "lat", default=None)),
            longitude=_optional_float(_mapping_get(place, "longitude", "lng", "lon", default=None)),
            place_score=_round4(score),
            score_components=dict(_mapping_get(place, "score_components", default={})),
            scored=bool(_mapping_get(place, "scored", default=True)),
            exclusion_reason=_optional_text(
                _mapping_get(place, "exclusion_reason", default=None),
            ),
        )
    score = _optional_float(getattr(place, "place_score", None))
    if score is None:
        raise SchemaValidationError("place_score is required for city scoring")
    return PlaceScoreResult(
        place=place,
        place_id=_place_id(place),
        title=_optional_text(_candidate_value(place, "title", "name")),
        city_id=_optional_text(_candidate_value(place, "city_id", "cityId")),
        theme_tags=_string_tuple(
            _candidate_value(place, "theme_tags", "themeTags"),
            "theme_tags",
        ),
        latitude=_optional_float(_candidate_value(place, "latitude", "lat")),
        longitude=_optional_float(_candidate_value(place, "longitude", "lng", "lon")),
        place_score=_round4(score),
        score_components={},
    )


def _candidate_value(candidate: Any, *field_names: str) -> Any:
    """Read a candidate field from object, mapping, or nested metadata."""

    if isinstance(candidate, Mapping):
        for field_name in field_names:
            if field_name in candidate:
                return candidate[field_name]
        metadata = candidate.get("metadata")
        if isinstance(metadata, Mapping):
            return _mapping_get(metadata, *field_names, default=None)
        return None
    for field_name in field_names:
        if hasattr(candidate, field_name):
            return getattr(candidate, field_name)
    metadata = getattr(candidate, "metadata", None)
    if isinstance(metadata, Mapping):
        return _mapping_get(metadata, *field_names, default=None)
    return None


def _place_id(candidate: Any) -> str:
    """Return a stable place id for scoring audit."""

    return _required_text(
        _candidate_value(candidate, "place_id", "placeId", "id", "key"),
        "place_id",
    )


def _source_quality_score(
    *,
    title: str | None,
    theme_tags: tuple[str, ...],
    city_id: str | None,
    city_name: str | None,
    latitude: float | None,
    longitude: float | None,
) -> float:
    """Score metadata completeness, not subjective content quality."""

    score = 0.0
    if latitude is not None and longitude is not None:
        score += SOURCE_QUALITY_FIELD_BONUS
    if title:
        score += SOURCE_QUALITY_FIELD_BONUS
    if theme_tags:
        score += SOURCE_QUALITY_FIELD_BONUS
    if city_id or city_name:
        score += SOURCE_QUALITY_FIELD_BONUS
    return min(score, SOURCE_QUALITY_FIELD_BONUS * 4)


def _local_distance_penalty(
    *,
    latitude: float | None,
    longitude: float | None,
    reference_location: Any | None,
) -> float:
    """Return weak local-distance penalty from a city reference coordinate."""

    if latitude is None or longitude is None or reference_location is None:
        return 0.0
    reference = _location_pair(reference_location)
    if reference is None:
        return 0.0
    distance_km = haversine_distance(latitude, longitude, reference[0], reference[1])
    return distance_km * LOCAL_DISTANCE_PENALTY_PER_KM


def _city_distance_penalty(
    top_places: Sequence[PlaceScoreResult],
    user_location: Any | None,
) -> float:
    """Return user-origin distance penalty from average top-place coordinate."""

    if user_location is None:
        return 0.0
    origin = _location_pair(user_location)
    if origin is None:
        return 0.0
    coordinates = tuple(
        (place.latitude, place.longitude)
        for place in top_places
        if place.latitude is not None and place.longitude is not None
    )
    if not coordinates:
        return 0.0
    avg_latitude = sum(item[0] for item in coordinates) / len(coordinates)
    avg_longitude = sum(item[1] for item in coordinates) / len(coordinates)
    distance_km = haversine_distance(origin[0], origin[1], avg_latitude, avg_longitude)
    return (distance_km / 100.0) * USER_DISTANCE_PENALTY_PER_100KM


def _theme_coverage(
    top_places: Sequence[PlaceScoreResult],
    active_themes: tuple[str, ...],
) -> float:
    """Return ratio of required themes covered by top places."""

    if not active_themes:
        return 0.0
    covered = {
        theme
        for place in top_places
        for theme in place.theme_tags
        if theme in active_themes
    }
    return len(covered) / len(active_themes)


def _theme_balance(
    top_places: Sequence[PlaceScoreResult],
    active_themes: tuple[str, ...],
) -> float:
    """Return normalized Shannon entropy across active theme evidence."""

    if not active_themes:
        return 0.0
    counts = {
        theme: sum(1 for place in top_places if theme in place.theme_tags)
        for theme in active_themes
    }
    total = sum(counts.values())
    if total == 0:
        return 0.0
    if len(active_themes) == 1:
        return 1.0
    entropy = 0.0
    for count in counts.values():
        if count == 0:
            continue
        probability = count / total
        entropy -= probability * math.log(probability)
    return entropy / math.log(len(active_themes))


def _scoreable_themes(active_themes: Sequence[str]) -> tuple[str, ...]:
    """Remove non-scored external or festival labels from active themes."""

    themes = _string_tuple(active_themes, "active_themes")
    excluded = GOURMET_EXTERNAL_THEME_LABELS | FESTIVAL_EXCLUDED_THEME_LABELS
    filtered: list[str] = []
    seen: set[str] = set()
    for theme in themes:
        if theme in excluded or theme in seen:
            continue
        seen.add(theme)
        filtered.append(theme)
    return tuple(filtered)


def _similarity_from_distance(value: Any) -> float:
    """Convert vector distance to a non-negative similarity contribution."""

    distance = _optional_float(value)
    if distance is None:
        return 0.0
    return max(1.0 - distance, 0.0)


def _location_pair(location: Any) -> tuple[float, float] | None:
    """Normalize mapping/object/tuple location values into lat/lon."""

    if isinstance(location, (list, tuple)) and len(location) == 2:
        return (_numeric(location[0], "latitude"), _numeric(location[1], "longitude"))
    if isinstance(location, Mapping):
        latitude = _mapping_get(location, "latitude", "lat", default=None)
        longitude = _mapping_get(location, "longitude", "lng", "lon", default=None)
    else:
        latitude = getattr(location, "latitude", getattr(location, "lat", None))
        longitude = getattr(
            location,
            "longitude",
            getattr(location, "lng", getattr(location, "lon", None)),
        )
    if latitude is None or longitude is None:
        return None
    return (_numeric(latitude, "latitude"), _numeric(longitude, "longitude"))


def _mapping_get(
    payload: Mapping[str, Any],
    *field_names: str,
    default: Any = None,
) -> Any:
    """Return the first present field from a mapping."""

    for field_name in field_names:
        if field_name in payload:
            return payload[field_name]
    return default


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    """Validate and normalize a string sequence."""

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


def _optional_text(value: Any) -> str | None:
    """Normalize optional text, treating blank strings as missing."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError("optional text must be a string")
    normalized = value.strip()
    return normalized or None


def _positive_int(value: Any, field_name: str) -> int:
    """Validate a positive integer input."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return value


def _numeric(value: Any, field_name: str) -> float:
    """Validate a numeric input."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be numeric")
    return float(value)


def _optional_float(value: Any) -> float | None:
    """Validate an optional numeric input."""

    if value is None:
        return None
    return _numeric(value, "value")


def _round4(value: float) -> float:
    """Round a score component to four decimals."""

    return round(value, 4)


def _zero_place_components() -> dict[str, float]:
    """Return zeroed place-score components."""

    return {
        "raw_similarity": 0.0,
        "soft_similarity": 0.0,
        "theme_match_score": 0.0,
        "source_quality_score": 0.0,
        "local_distance_penalty": 0.0,
    }


def _zero_city_breakdown() -> ScoreBreakdown:
    """Return a zeroed city-score breakdown."""

    return ScoreBreakdown(
        semantic_evidence=0.0,
        theme_coverage=0.0,
        theme_balance=0.0,
        scale_correction=0.0,
        candidate_sufficiency=0.0,
        distance_penalty=0.0,
        congestion_penalty=0.0,
    )


__all__ = [
    "CANDIDATE_SUFFICIENCY_THRESHOLD",
    "CityScoreResult",
    "PlaceScoreResult",
    "RESPONSIBILITY",
    "ScoreBreakdown",
    "ScoringTool",
    "TOOL_NAME",
    "haversine_distance",
    "score_city",
    "score_place",
]
