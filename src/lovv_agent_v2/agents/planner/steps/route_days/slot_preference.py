from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, Protocol, TypeVar


class SlotPreferredPlace(Protocol):
    place_id: str
    title: str
    payload: Mapping[str, object]


TPlace = TypeVar("TPlace", bound=SlotPreferredPlace)

MORNING_KEYWORDS: Final[tuple[str, ...]] = ("일출", "sunrise")
EVENING_KEYWORDS: Final[tuple[str, ...]] = ("낙조", "야경", "sunset", "night")
EVENING_AVOID_SUBTYPE_CODES: Final[frozenset[str]] = frozenset(
    {
        "NA010100",
        "NA010200",
        "NA010300",
        "NA010400",
        "NA020800",
        "NA030100",
        "NA030300",
        "NA030400",
        "NA040100",
        "NA040200",
        "NA040300",
        "NA040400",
        "NA040500",
        "NA040600",
        "NA040700",
        "VE040300",
        "VE070100",
        "VE070600",
        "HS010100",
        "HS010200",
        "HS010600",
        "HS010700",
        "HS010800",
        "HS011000",
        "HS030100",
    },
)
EVENING_PREFER_SUBTYPE_CODES: Final[frozenset[str]] = frozenset(
    {
        "NA020700",
        "NA020900",
        "VE010200",
        "VE010300",
        "VE010400",
        "VE010800",
        "VE020500",
        "VE030100",
    },
)


def order_by_slot_preference(places: Sequence[TPlace]) -> tuple[TPlace, ...]:
    morning = tuple(place for place in places if _has_keyword(place, MORNING_KEYWORDS))
    evening = tuple(place for place in places if _has_keyword(place, EVENING_KEYWORDS))
    pinned_ids = {place.place_id for place in (*morning, *evening)}
    remaining = tuple(place for place in places if place.place_id not in pinned_ids)
    avoid = tuple(place for place in remaining if _slot_bias(place) == "avoid")
    prefer = tuple(place for place in remaining if _slot_bias(place) == "prefer")
    neutral = tuple(place for place in remaining if _slot_bias(place) == "neutral")
    return (*morning, *avoid, *neutral, *prefer, *evening)


def _slot_bias(place: SlotPreferredPlace) -> str:
    subtype_code = place.payload.get("attraction_subtype_code")
    if not isinstance(subtype_code, str):
        return "neutral"
    normalized = subtype_code.strip()
    if normalized in EVENING_AVOID_SUBTYPE_CODES:
        return "avoid"
    if normalized in EVENING_PREFER_SUBTYPE_CODES:
        return "prefer"
    return "neutral"


def _has_keyword(place: SlotPreferredPlace, keywords: Sequence[str]) -> bool:
    title = place.title.casefold()
    return any(keyword.casefold() in title for keyword in keywords)
