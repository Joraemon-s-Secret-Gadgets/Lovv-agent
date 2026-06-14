"""Agent node namespace.

Each module in this package owns one graph node responsibility. Task 1.1 keeps
the modules lightweight and side-effect free; later tasks add behavior behind
the same import paths.
"""

from __future__ import annotations

AGENT_MODULES: tuple[str, ...] = (
    "intent",
    "supervisor",
    "candidate_evidence",
    "festival_verifier",
    "planner",
)

__all__ = ["AGENT_MODULES"]
