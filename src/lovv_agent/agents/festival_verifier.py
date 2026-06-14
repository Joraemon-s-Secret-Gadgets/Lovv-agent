"""Festival Verifier Agent helpers.

The Festival Verifier runs after Candidate Evidence has already selected one
city. It verifies only ``selected_festival_candidates`` from that package and
returns structured verification state for Planner. It must not create festival
city seeds, rerank cities, or change the selected destination.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent.models.schemas import CandidateEvidencePackage, SchemaValidationError

NODE_NAME = "festival_verifier_agent"

RESPONSIBILITY = "Verify selected-city festival candidates before planning."

OUT_OF_SCOPE = (
    "festival_city_seed_creation",
    "city_reranking",
    "itinerary_generation",
)

FESTIVAL_VERIFIER_STATUSES: tuple[str, ...] = ("skipped", "no_candidate", "ok", "error")


@dataclass(frozen=True, slots=True)
class FestivalVerifierInput:
    """Bounded verifier input after Candidate Evidence final city selection."""

    include_festivals: bool
    travel_year: int
    travel_month: int
    selected_festival_candidates: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class FestivalVerifierResult:
    """Structured verifier result consumed by Planner and graph routing."""

    status: str
    verifications: tuple[Any, ...] = ()
    failure_signals: tuple[str, ...] = ()
    skipped: bool = False

    def __post_init__(self) -> None:
        if self.status not in FESTIVAL_VERIFIER_STATUSES:
            allowed = ", ".join(FESTIVAL_VERIFIER_STATUSES)
            raise SchemaValidationError(f"festival verifier status must be one of: {allowed}")

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable verifier result."""

        return {
            "status": self.status,
            "verifications": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in self.verifications
            ],
            "failure_signals": list(self.failure_signals),
            "skipped": self.skipped,
        }


class FestivalVerifierAgent:
    """Verify selected-city festival candidates before Planner placement."""

    def build_input(
        self,
        *,
        include_festivals: bool,
        travel_year: int,
        travel_month: int,
        candidate_evidence_package: CandidateEvidencePackage | Mapping[str, Any] | None,
    ) -> FestivalVerifierInput:
        """Build verifier input from the Candidate Evidence package boundary."""

        return build_festival_verifier_input(
            include_festivals=include_festivals,
            travel_year=travel_year,
            travel_month=travel_month,
            candidate_evidence_package=candidate_evidence_package,
        )

    def verify(
        self,
        verifier_input: FestivalVerifierInput,
    ) -> FestivalVerifierResult:
        """Return skip/no-candidate state for Task 7.1 scoped verification."""

        if not verifier_input.include_festivals:
            return FestivalVerifierResult(
                status="skipped",
                failure_signals=("include_festivals_false",),
                skipped=True,
            )
        if not verifier_input.selected_festival_candidates:
            return FestivalVerifierResult(
                status="no_candidate",
                failure_signals=("no_selected_festival_candidates",),
            )
        return FestivalVerifierResult(status="ok")


def build_festival_verifier_input(
    *,
    include_festivals: bool,
    travel_year: int,
    travel_month: int,
    candidate_evidence_package: CandidateEvidencePackage | Mapping[str, Any] | None,
) -> FestivalVerifierInput:
    """Extract only selected-city festival candidates for verification."""

    if not isinstance(include_festivals, bool):
        raise SchemaValidationError("include_festivals must be a boolean")
    normalized_year = _positive_int(travel_year, "travel_year")
    normalized_month = _month(travel_month, "travel_month")
    selected_candidates: tuple[dict[str, Any], ...] = ()
    if candidate_evidence_package is not None:
        package = _coerce_candidate_evidence_package(candidate_evidence_package)
        selected_candidates = _mapping_tuple(
            package.selected_festival_candidates,
            "selected_festival_candidates",
        )
    return FestivalVerifierInput(
        include_festivals=include_festivals,
        travel_year=normalized_year,
        travel_month=normalized_month,
        selected_festival_candidates=selected_candidates,
    )


def _coerce_candidate_evidence_package(
    package: CandidateEvidencePackage | Mapping[str, Any],
) -> CandidateEvidencePackage:
    """Accept schema or mapping package payloads at the verifier boundary."""

    if isinstance(package, CandidateEvidencePackage):
        return package
    if isinstance(package, Mapping):
        return CandidateEvidencePackage.from_mapping(package)
    raise SchemaValidationError("candidate_evidence_package must be a schema or mapping")


def _mapping_tuple(value: Sequence[Mapping[str, Any]], field_name: str) -> tuple[dict[str, Any], ...]:
    """Copy a sequence of mapping payloads."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SchemaValidationError(f"{field_name} must be a sequence")
    copied: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise SchemaValidationError(f"{field_name} must contain mappings")
        copied.append(dict(item))
    return tuple(copied)


def _positive_int(value: Any, field_name: str) -> int:
    """Validate a positive integer."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value < 1:
        raise SchemaValidationError(f"{field_name} must be positive")
    return value


def _month(value: Any, field_name: str) -> int:
    """Validate a month number."""

    parsed = _positive_int(value, field_name)
    if parsed > 12:
        raise SchemaValidationError(f"{field_name} must be between 1 and 12")
    return parsed


__all__ = [
    "FESTIVAL_VERIFIER_STATUSES",
    "NODE_NAME",
    "OUT_OF_SCOPE",
    "RESPONSIBILITY",
    "FestivalVerifierAgent",
    "FestivalVerifierInput",
    "FestivalVerifierResult",
    "build_festival_verifier_input",
]
