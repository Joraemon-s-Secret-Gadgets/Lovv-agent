"""Agent node namespace.

Each module in this package owns one graph node responsibility. Task 1.1 keeps
the modules lightweight and side-effect free; later tasks add behavior behind
the same import paths.
"""

from __future__ import annotations

# Agent 모듈은 graph node 책임과 1:1로 대응한다.
AGENT_MODULES: tuple[str, ...] = (
    "intent",
    "supervisor",
    "candidate_evidence",
    "festival_verifier",
    "planner",
)

__all__ = ["AGENT_MODULES"]
