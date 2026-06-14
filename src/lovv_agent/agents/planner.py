"""Planner Agent node placeholder.

Planned responsibility:
- convert grounded evidence into itinerary internals,
- apply festival overlay and placeholder policies,
- validate user-facing itinerary safety.

Task 1.1 keeps the module import-only and does not generate itinerary text.
"""

from __future__ import annotations

NODE_NAME = "planner_agent"

RESPONSIBILITY = "Create safe itinerary internals from grounded evidence."

OUT_OF_SCOPE = (
    "new_place_search",
    "ungrounded_restaurant_generation",
    "festival_date_confirmation",
)

__all__ = ["NODE_NAME", "OUT_OF_SCOPE", "RESPONSIBILITY"]
