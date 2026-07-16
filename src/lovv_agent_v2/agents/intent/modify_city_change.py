from __future__ import annotations

from collections.abc import Mapping
from typing import Final, TypedDict

from lovv_agent_v2.agents.intent.modify_slots import avoid_city_ids
from lovv_agent_v2.models.city_identity import load_default_city_identity_map
from lovv_agent_v2.models.city_identity_text import find_city_identity_in_text

_GENERIC_CHANGE_PHRASES: Final = (
    "도시 바꿔",
    "도시를 바꿔",
    "도시 변경",
    "도시를 변경",
    "도시 교체",
    "도시를 교체",
    "지역 바꿔",
    "지역을 바꿔",
    "지역 변경",
    "지역을 변경",
    "지역 교체",
    "지역을 교체",
)

CurrentOrderValue = str | int | float | bool | None


class CityChange(TypedDict):
    target_city_id: str | None
    target_city_name: str | None
    city_preference_query: str
    carry_over_themes: bool
    carry_over_festivals: bool
    avoid_city_ids: list[str]


def build_city_change(
    raw_query: str,
    current_order: tuple[Mapping[str, CurrentOrderValue], ...],
) -> CityChange | None:
    if "도시" not in raw_query and "지역" not in raw_query:
        return None
    if not any(keyword in raw_query for keyword in ("바꿔", "변경", "교체")):
        return None
    city_map = load_default_city_identity_map()
    identity = find_city_identity_in_text(city_map, raw_query)
    if identity is not None:
        return {
            "target_city_id": identity.city_id,
            "target_city_name": identity.city_name_ko,
            "city_preference_query": raw_query,
            "carry_over_themes": True,
            "carry_over_festivals": True,
            "avoid_city_ids": avoid_city_ids(current_order),
        }
    if "다른" not in raw_query and not any(
        phrase in raw_query for phrase in _GENERIC_CHANGE_PHRASES
    ):
        return None
    return {
        "target_city_id": None,
        "target_city_name": None,
        "city_preference_query": raw_query,
        "carry_over_themes": True,
        "carry_over_festivals": True,
        "avoid_city_ids": avoid_city_ids(current_order),
    }


def city_change_routing_hint(city_change: CityChange) -> str:
    target_id = city_change.get("target_city_id")
    if isinstance(target_id, str) and target_id.strip():
        return "planner_direct_anchor"
    return "city_select_rediscovery"


__all__ = ["build_city_change", "city_change_routing_hint"]
