"""State skeleton for Lovv agent runs.

The concrete state model is defined in Task 1.3. For Task 1.1, this module only
records the state groups required by the SPEC so downstream modules have a
stable import target.
"""

from __future__ import annotations

STATE_GROUPS: tuple[str, ...] = (
    "request",
    "conversation",
    "trace",
    "intent",
    "routing",
    "evidence",
    "festival",
    "planning",
    "serving",
)

__all__ = ["STATE_GROUPS"]
