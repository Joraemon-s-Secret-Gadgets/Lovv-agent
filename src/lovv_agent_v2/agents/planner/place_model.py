from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from lovv_agent_v2.models.schemas import SchemaValidationError


@dataclass(frozen=True, slots=True)
class PlannerPlace:
    place_id: str
    title: str
    theme_tags: tuple[str, ...]
    similarity: float
    soft_similarity: float
    latitude: float | None
    longitude: float | None
    payload: dict[str, object]
    assigned_theme: str | None = None
    is_seed: bool = False


def coerce_place(payload: Mapping[str, object]) -> PlannerPlace:
    score_components = _mapping(_mapping(payload.get("score_audit")).get("score_components"))
    similarity = _float(score_components.get("raw_similarity", payload.get("sim", 0.0)))
    return PlannerPlace(
        place_id=text(payload.get("place_id", payload.get("placeId")), "place_id"),
        title=text(payload.get("title"), "title"),
        theme_tags=theme_tuple(payload.get("theme_tags", payload.get("themeTags", ()))),
        similarity=similarity,
        soft_similarity=_float(payload.get("soft_similarity", payload.get("soft_sim", similarity))),
        latitude=_optional_float(payload.get("latitude", payload.get("lat"))),
        longitude=_optional_float(payload.get("longitude", payload.get("lon"))),
        payload=dict(payload),
        assigned_theme=_optional_text(payload.get("assigned_theme")),
    )


def with_seed_flag(place: PlannerPlace, selected_seed_ids: set[str]) -> PlannerPlace:
    return replace(place, is_seed=place.place_id in selected_seed_ids)


def merge_by_place_id(places: Sequence[PlannerPlace]) -> tuple[PlannerPlace, ...]:
    merged: dict[str, PlannerPlace] = {}
    for place in sorted(places, key=selection_sort_key, reverse=True):
        merged.setdefault(place.place_id, place)
    return tuple(merged.values())


def selection_sort_key(place: PlannerPlace) -> tuple[bool, float, float]:
    return (place.is_seed, place.soft_similarity, place.similarity)


def seed_ids(seeds: Sequence[Mapping[str, object]]) -> set[str]:
    return {text(seed.get("place_id", seed.get("placeId")), "seed.place_id") for seed in seeds}


def theme_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (text(value, "theme"),)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text(item, "theme") for item in value)


def positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or value <= 0:
        raise SchemaValidationError(f"{field_name} must be positive")
    return value


def text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
