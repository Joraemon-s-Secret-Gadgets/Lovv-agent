"""Candidate Evidence Agent node placeholder.

Planned responsibility:
- orchestrate runtime retrieval,
- rank city and place evidence,
- build the internal Candidate Evidence Package.

Task 1.1 intentionally does not perform AWS calls, scoring, or package
construction.
"""

from __future__ import annotations

NODE_NAME = "candidate_evidence_agent"

RESPONSIBILITY = "Build grounded city/place evidence for Planner input."

OUT_OF_SCOPE = (
    "final_user_response",
    "itinerary_generation",
    "festival_date_verification",
)

__all__ = ["NODE_NAME", "OUT_OF_SCOPE", "RESPONSIBILITY"]
