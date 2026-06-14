"""Festival Verifier Agent helpers.

The Festival Verifier runs after Candidate Evidence has already selected one
city. It verifies only ``selected_festival_candidates`` from that package and
returns structured verification state for Planner. It must not create festival
city seeds, rerank cities, or change the selected destination.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    FestivalVerification,
    SchemaValidationError,
)

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
        """Verify selected festival dates for Planner placement policy."""

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
        verifications = tuple(
            verify_festival_candidate(
                candidate,
                travel_year=verifier_input.travel_year,
                travel_month=verifier_input.travel_month,
            )
            for candidate in verifier_input.selected_festival_candidates
        )
        return FestivalVerifierResult(status="ok", verifications=verifications)


def verify_festival_candidate(
    candidate: Mapping[str, Any],
    *,
    travel_year: int,
    travel_month: int,
) -> FestivalVerification:
    """Verify one selected festival candidate from normalized DynamoDB fields."""

    normalized_year = _positive_int(travel_year, "travel_year")
    normalized_month = _month(travel_month, "travel_month")
    payload = _mapping(candidate, "festival_candidate")
    festival_id = _required_text(_first_present(payload, "festival_id", "id"), "festival_id")
    name = _required_text(_first_present(payload, "name", "title"), "name")
    start_date = normalize_festival_date(
        _first_optional(payload, "start_date", "event_start_date", "eventstartdate"),
    )
    end_date = normalize_festival_date(
        _first_optional(payload, "end_date", "event_end_date", "eventenddate"),
    )
    date_status = _date_status(start_date=start_date, travel_year=normalized_year)
    is_applicable = _is_applicable_to_month(
        start_date=start_date,
        end_date=end_date,
        travel_month=normalized_month,
    )
    planner_policy = (
        "placeable"
        if date_status == "confirmed" and is_applicable
        else "not_placeable"
    )
    source_type = _optional_text(_first_optional(payload, "source_type", "source", "provenance"))
    confidence = 0.8 if planner_policy == "placeable" else 0.4

    return FestivalVerification(
        festival_id=festival_id,
        name=name,
        date_status=date_status,
        start_date=start_date.isoformat() if start_date is not None else None,
        end_date=end_date.isoformat() if end_date is not None else None,
        is_applicable_to_trip=is_applicable,
        planner_policy=planner_policy,
        source_type=source_type or "dynamodb_detail",
        confidence=confidence,
        evidence_summary=_evidence_summary(
            date_status=date_status,
            start_date=start_date,
            travel_year=normalized_year,
            travel_month=normalized_month,
            is_applicable=is_applicable,
        ),
    )


def normalize_festival_date(value: Any) -> date | None:
    """Normalize supported festival date strings to ``date`` values."""

    if value is None:
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise SchemaValidationError("festival date must be a string")
    text = value.strip()
    if not text:
        return None
    digits = re.findall(r"\d+", text)
    if len(digits) >= 3:
        year, month, day = (int(digits[0]), int(digits[1]), int(digits[2]))
        return date(year, month, day)
    if len(digits) == 1 and len(digits[0]) == 8:
        compact = digits[0]
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    raise SchemaValidationError("festival date must include year, month, and day")


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


def _date_status(*, start_date: date | None, travel_year: int) -> str:
    """Return initial date status from normalized DynamoDB start date."""

    if start_date is None:
        return "unknown"
    if start_date.year == travel_year:
        return "confirmed"
    return "outdated"


def _is_applicable_to_month(
    *,
    start_date: date | None,
    end_date: date | None,
    travel_month: int,
) -> bool:
    """Return whether a festival overlaps the request travel month."""

    if start_date is None:
        return False
    if end_date is None or end_date < start_date:
        return start_date.month == travel_month
    current_months = _months_between(start_date, end_date)
    return travel_month in current_months


def _months_between(start_date: date, end_date: date) -> set[int]:
    """Return month numbers touched by an inclusive date range."""

    months: set[int] = set()
    year = start_date.year
    month = start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.add(month)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def _evidence_summary(
    *,
    date_status: str,
    start_date: date | None,
    travel_year: int,
    travel_month: int,
    is_applicable: bool,
) -> str:
    """Build a short internal verification summary."""

    if start_date is None:
        return "내부 축제 후보에서 시작일을 확인하지 못했다."
    if date_status == "confirmed" and is_applicable:
        return (
            f"내부 정규화 detail의 시작일 {start_date.isoformat()}이 "
            f"{travel_year}년과 일치하고 {travel_month}월 여행에 해당한다."
        )
    if date_status == "confirmed":
        return (
            f"내부 정규화 detail의 시작일 {start_date.isoformat()}은 "
            f"{travel_year}년과 일치하지만 {travel_month}월 여행에는 해당하지 않는다."
        )
    return (
        f"내부 정규화 detail의 시작일 {start_date.isoformat()}이 "
        f"요청 연도 {travel_year}년과 일치하지 않는다."
    )


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


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Copy a mapping payload."""

    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return dict(value)


def _first_present(record: Mapping[str, Any], *field_names: str) -> Any:
    """Return the first present field value."""

    for field_name in field_names:
        if field_name in record:
            return record[field_name]
    joined = " or ".join(field_names)
    raise SchemaValidationError(f"missing required field: {joined}")


def _first_optional(record: Mapping[str, Any], *field_names: str) -> Any:
    """Return the first present field value or ``None``."""

    for field_name in field_names:
        if field_name in record:
            return record[field_name]
    return None


def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty string."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any) -> str | None:
    """Normalize optional text."""

    if value is None:
        return None
    return _required_text(value, "optional_text")


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
    "normalize_festival_date",
    "verify_festival_candidate",
]
