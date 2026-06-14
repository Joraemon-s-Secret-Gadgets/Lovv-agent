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
GOURMET_THEME_LABEL = "미식·노포"


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
    "RESPONSIBILITY",
    "TOOL_NAME",
    "build_food_search_link",
]
