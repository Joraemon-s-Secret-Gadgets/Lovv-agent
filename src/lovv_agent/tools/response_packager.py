"""Response Packager placeholder.

Planned responsibility:
- package Planner internals into the public recommendation response,
- hide internal evidence, audit, and tool payloads.

This is a deterministic packaging component, not an LLM agent. Task 1.1 does
not implement API response mapping yet.
"""

from __future__ import annotations

NODE_NAME = "response_packager"

RESPONSIBILITY = "Package safe user-facing recommendation responses."

OUT_OF_SCOPE = (
    "recommendation_reasoning_changes",
    "internal_payload_exposure",
)

__all__ = ["NODE_NAME", "OUT_OF_SCOPE", "RESPONSIBILITY"]
