"""Festival Verifier Agent node placeholder.

Planned responsibility:
- verify selected-city festival candidates,
- produce date status for Planner placement policy.

This placeholder does not create festival city seeds or rerank destinations.
"""

from __future__ import annotations

NODE_NAME = "festival_verifier_agent"

RESPONSIBILITY = "Verify selected-city festival candidates before planning."

OUT_OF_SCOPE = (
    "festival_city_seed_creation",
    "city_reranking",
    "itinerary_generation",
)

__all__ = ["NODE_NAME", "OUT_OF_SCOPE", "RESPONSIBILITY"]
