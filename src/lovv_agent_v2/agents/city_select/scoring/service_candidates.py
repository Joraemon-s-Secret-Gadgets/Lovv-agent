from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.service_types import (
    PlaceScoreResult,
    ScoreBreakdown,
)
from lovv_agent_v2.agents.city_select.scoring.service_validation import (
    candidate_value,
    mapping_get,
    optional_float,
    optional_text,
    place_id,
    required_text,
    round4,
    string_tuple,
)
from lovv_agent_v2.models.schemas import SchemaValidationError

SOURCE_QUALITY_FIELD_BONUS = 0.05


def coerce_scored_place(place: Any) -> PlaceScoreResult:
    if isinstance(place, PlaceScoreResult):
        return place
    if isinstance(place, Mapping):
        score = optional_float(mapping_get(place, "place_score", "score"))
        if score is None:
            raise SchemaValidationError("place_score is required for city scoring")
        return PlaceScoreResult(
            place=place,
            place_id=required_text(mapping_get(place, "place_id", "placeId"), "place_id"),
            title=optional_text(mapping_get(place, "title", "name", default=None)),
            city_id=optional_text(mapping_get(place, "city_id", "cityId", default=None)),
            theme_tags=string_tuple(
                mapping_get(place, "theme_tags", "themeTags", default=()),
                "theme_tags",
            ),
            latitude=optional_float(mapping_get(place, "latitude", "lat", default=None)),
            longitude=optional_float(
                mapping_get(place, "longitude", "lng", "lon", default=None),
            ),
            place_score=round4(score),
            score_components=dict(mapping_get(place, "score_components", default={})),
            scored=bool(mapping_get(place, "scored", default=True)),
            exclusion_reason=optional_text(
                mapping_get(place, "exclusion_reason", default=None),
            ),
        )
    score = optional_float(getattr(place, "place_score", None))
    if score is None:
        raise SchemaValidationError("place_score is required for city scoring")
    return PlaceScoreResult(
        place=place,
        place_id=place_id(place),
        title=optional_text(candidate_value(place, "title", "name")),
        city_id=optional_text(candidate_value(place, "city_id", "cityId")),
        theme_tags=string_tuple(
            candidate_value(place, "theme_tags", "themeTags"),
            "theme_tags",
        ),
        latitude=optional_float(candidate_value(place, "latitude", "lat")),
        longitude=optional_float(candidate_value(place, "longitude", "lng", "lon")),
        place_score=round4(score),
        score_components={},
    )


def source_quality_score(
    *,
    title: str | None,
    theme_tags: tuple[str, ...],
    city_id: str | None,
    city_name: str | None,
    latitude: float | None,
    longitude: float | None,
) -> float:
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


def similarity_from_distance(value: Any) -> float:
    distance = optional_float(value)
    if distance is None:
        return 0.0
    return max(1.0 - distance, 0.0)


def zero_place_components() -> dict[str, float]:
    return {
        "raw_similarity": 0.0,
        "source_quality_score": 0.0,
        "place_reference_distance_penalty": 0.0,
    }


def zero_city_breakdown() -> ScoreBreakdown:
    return ScoreBreakdown(
        weighted_theme_coverage=0.0,
        weighted_missing_theme_penalty=0.0,
        distance_penalty=0.0,
        congestion_penalty=0.0,
    )
