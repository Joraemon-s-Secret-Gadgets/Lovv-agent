"""Supervisor Router node placeholder.

Planned responsibility:
- route between graph nodes using fulfilled matrix state,
- stop at END_WAIT_USER when clarification is required,
- enforce validation retry limits.

Task 1.1 does not implement routing decisions yet.
"""

from __future__ import annotations

NODE_NAME = "supervisor_router"

RESPONSIBILITY = "Route graph execution by status and fulfilled matrix."

OUT_OF_SCOPE = (
    "raw_retrieval_interpretation",
    "planner_generation",
)

__all__ = ["NODE_NAME", "OUT_OF_SCOPE", "RESPONSIBILITY"]
