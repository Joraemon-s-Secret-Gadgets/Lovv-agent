"""Intent Agent node placeholder.

Planned responsibility:
- normalize API structured input,
- split raw and soft preference queries,
- keep core API fields from being re-inferred from natural language.

No parsing, LLM call, or search behavior is implemented in Task 1.1.
"""

from __future__ import annotations

NODE_NAME = "intent_agent"

RESPONSIBILITY = "Normalize request input into Candidate Evidence input."

OUT_OF_SCOPE = (
    "city_search",
    "scoring",
    "itinerary_generation",
)

__all__ = ["NODE_NAME", "OUT_OF_SCOPE", "RESPONSIBILITY"]
