"""Schema skeletons for Lovv agent handoff contracts.

Task 1.3 will define concrete TypedDict/dataclass or Pydantic-compatible
schemas. For Task 1.1, this module only names the contract groups so imports
remain stable while implementation proceeds one subtask at a time.
"""

from __future__ import annotations

SCHEMA_GROUPS: tuple[str, ...] = (
    "CandidateEvidenceInput",
    "CandidateEvidencePackage",
    "FestivalVerification",
    "PlannerOutput",
    "BackendResponse",
)

__all__ = ["SCHEMA_GROUPS"]
