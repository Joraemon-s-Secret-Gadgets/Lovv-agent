"""Safe external link builders for Planner and Response Packager.

The link helper is intentionally deterministic. It does not call external
services, verify live restaurant availability, or create named restaurant
recommendations. Planner can use the returned payload as a public-safe CTA when
the gourmet theme is present but restaurant grounding is unavailable.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

TOOL_NAME = "LinkBuilder"

RESPONSIBILITY = "Build safe external links for Planner and Response Packager."

FOOD_SEARCH_LINK_TYPE = "foodSearch"
MAP_LINK_TYPE = "map"
STAY_SEARCH_LINK_TYPE = "staySearch"
GOURMET_THEME_LABEL = "미식·노포"


def build_default_city_links(
    *,
    city_name_ko: str,
    country: str,
) -> dict[str, dict[str, Any]]:
    """Build default public links for a selected recommendation city."""

    return {
        MAP_LINK_TYPE: build_map_link(city_name_ko=city_name_ko, country=country),
        STAY_SEARCH_LINK_TYPE: build_stay_search_link(
            city_name_ko=city_name_ko,
            country=country,
        ),
        FOOD_SEARCH_LINK_TYPE: build_food_search_link(
            city_name_ko=city_name_ko,
            country=country,
        ),
    }


def build_map_link(
    *,
    city_name_ko: str,
    country: str,
) -> dict[str, Any]:
    """Build a selected-city map link."""

    city_name = _required_text(city_name_ko, "city_name_ko")
    normalized_country = _required_text(country, "country")
    query = f"{city_name}"
    return {
        "type": MAP_LINK_TYPE,
        "label": f"{city_name} 지도 보기",
        "url": f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}",
        "query": query,
        "city_name_ko": city_name,
        "country": normalized_country,
        "source": "external_map_link",
    }


def build_stay_search_link(
    *,
    city_name_ko: str,
    country: str,
) -> dict[str, Any]:
    """Build a selected-city stay search link."""

    city_name = _required_text(city_name_ko, "city_name_ko")
    normalized_country = _required_text(country, "country")
    query = f"{city_name} 숙소"
    return {
        "type": STAY_SEARCH_LINK_TYPE,
        "label": f"{city_name} 숙소 검색하기",
        "url": f"https://www.google.com/search?q={quote_plus(query)}",
        "query": query,
        "city_name_ko": city_name,
        "country": normalized_country,
        "source": "external_search_link",
    }


def build_food_search_link(
    *,
    city_name_ko: str,
    country: str,
) -> dict[str, Any]:
    """Build a selected-city food search CTA without naming restaurants."""

    city_name = _required_text(city_name_ko, "city_name_ko")
    normalized_country = _required_text(country, "country")
    query = f"{city_name} 맛집"
    return {
        "type": FOOD_SEARCH_LINK_TYPE,
        "label": f"{city_name} 음식점 검색하기",
        "url": f"https://www.google.com/search?q={quote_plus(query)}",
        "query": query,
        "city_name_ko": city_name,
        "country": normalized_country,
        "source": "external_search_link",
    }


def _required_text(value: str, field_name: str) -> str:
    """Validate non-empty link input text."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


__all__ = [
    "FOOD_SEARCH_LINK_TYPE",
    "GOURMET_THEME_LABEL",
    "MAP_LINK_TYPE",
    "RESPONSIBILITY",
    "STAY_SEARCH_LINK_TYPE",
    "TOOL_NAME",
    "build_default_city_links",
    "build_food_search_link",
    "build_map_link",
    "build_stay_search_link",
]
