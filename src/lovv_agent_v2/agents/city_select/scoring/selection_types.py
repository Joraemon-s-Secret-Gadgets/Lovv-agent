from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.service import PlaceScoreResult


@dataclass(frozen=True, slots=True)
class SelectionCandidate:
    payload: Any
    place_id: str
    title: str | None
    theme_tags: tuple[str, ...]
    place_score: float
    assigned_theme: str | None = None

    def with_role(self, slot_role: str, assigned_theme: str | None) -> dict[str, Any]:
        """Return a serializable payload with selection fields attached."""

        if isinstance(self.payload, PlaceScoreResult):
            result = self.payload.to_dict()
        elif isinstance(self.payload, Mapping):
            result = dict(self.payload)
        else:
            result = {
                "place_id": self.place_id,
                "title": self.title,
                "theme_tags": list(self.theme_tags),
            }
        result["place_id"] = self.place_id
        result["place_score"] = self.place_score
        result["slot_role"] = slot_role
        result["assigned_theme"] = assigned_theme
        result["_assigned_theme"] = assigned_theme
        return result


@dataclass(frozen=True, slots=True)
class CandidateSelectionResult:
    primary: tuple[dict[str, Any], ...]
    coverage_audit: dict[str, Any]
    deduplicated_candidates: tuple[SelectionCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable selection result."""

        return {
            "recommended_places": list(self.primary),
            "coverage_audit": dict(self.coverage_audit),
            "deduplicated_candidates": [
                asdict(candidate) for candidate in self.deduplicated_candidates
            ],
        }
