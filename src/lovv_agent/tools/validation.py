"""Minimal Planner output validation helpers.

This module intentionally stays small for the MVP. It checks only decisions
that are already explicit in the current SPEC: attractions must come from the
Candidate Evidence package, restaurants must not be invented, and placed
festivals must be confirmed by Festival Verifier.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    FestivalVerification,
    SchemaValidationError,
)

TOOL_NAME = "ValidationHelper"

RESPONSIBILITY = "Validate Planner output before public response packaging."


# Supervisor에는 pass/fail, retry action, error summary만 필요하므로
# validation은 compact dict를 반환한다.
def validate_planner_output(
    planner_output: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    *,
    package: CandidateEvidencePackage | Mapping[str, Any],
    festival_verifications: Sequence[Any] = (),
) -> dict[str, Any]:
    """Return a compact validation result for Supervisor retry decisions."""

    candidate_package = _coerce_candidate_package(package)
    itinerary = _coerce_itinerary(planner_output)
    grounded_place_ids = _grounded_place_ids(candidate_package)
    confirmed_festival_ids = _confirmed_festival_ids(festival_verifications)
    errors: list[dict[str, Any]] = []

    for index, item in enumerate(itinerary):
        item_type = str(item.get("item_type", ""))
        if item_type == "attraction":
            _validate_attraction_item(item, index, grounded_place_ids, errors)
        elif item_type == "festival":
            _validate_festival_item(item, index, confirmed_festival_ids, errors)
        elif item_type == "restaurant":
            errors.append(
                _error(
                    index,
                    "named_restaurant_not_allowed",
                    "Planner must not generate named restaurants in the current phase.",
                ),
            )
        elif item_type == "meal_placeholder" and item.get("placeId") is not None:
            errors.append(
                _error(
                    index,
                    "meal_placeholder_must_not_have_place_id",
                    "Meal placeholders must use placeId=null.",
                ),
            )

    is_valid = not errors
    return {
        "status": "valid" if is_valid else "invalid",
        "is_valid": is_valid,
        "valid": is_valid,
        "errors": tuple(errors),
        "retry_action": "none" if is_valid else "remove_or_rewrite_offending_items",
        "checked_item_count": len(itinerary),
    }


def _validate_attraction_item(
    item: Mapping[str, Any],
    index: int,
    grounded_place_ids: set[str],
    errors: list[dict[str, Any]],
) -> None:
    """Validate one attraction item against Candidate Evidence place ids."""

    place_id = item.get("placeId")
    if not isinstance(place_id, str) or place_id not in grounded_place_ids:
        errors.append(
            _error(
                index,
                "ungrounded_attraction",
                "Attraction items must use a Candidate Evidence placeId.",
            ),
        )


def _validate_festival_item(
    item: Mapping[str, Any],
    index: int,
    confirmed_festival_ids: set[str],
    errors: list[dict[str, Any]],
) -> None:
    """Validate one festival item against confirmed verifier outputs."""

    festival_id = item.get("festivalId")
    if not isinstance(festival_id, str) or festival_id not in confirmed_festival_ids:
        errors.append(
            _error(
                index,
                "unconfirmed_festival",
                "Festival items must come from confirmed Festival Verifier output.",
            ),
        )


def _grounded_place_ids(package: CandidateEvidencePackage) -> set[str]:
    """Collect place ids Planner may use for attraction items."""

    ids: set[str] = set()
    for place in (*package.recommended_places, *package.reserve_places):
        place_id = place.get("place_id")
        if isinstance(place_id, str) and place_id:
            ids.add(place_id)
    return ids


def _confirmed_festival_ids(festival_verifications: Sequence[Any]) -> set[str]:
    """Collect verifier-approved festival ids."""

    ids: set[str] = set()
    for verification in _festival_verification_tuple(festival_verifications):
        if (
            verification.date_status == "confirmed"
            and verification.is_applicable_to_trip
            and verification.planner_policy == "placeable"
        ):
            ids.add(verification.festival_id)
    return ids


def _coerce_itinerary(
    planner_output: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Accept either a PlannerOutput-like mapping or a raw itinerary sequence."""

    if isinstance(planner_output, Mapping):
        planner_output = planner_output.get("itinerary", ())
    if not isinstance(planner_output, Sequence) or isinstance(planner_output, (str, bytes)):
        raise SchemaValidationError("planner_output itinerary must be a sequence")
    itinerary: list[dict[str, Any]] = []
    for item in planner_output:
        if not isinstance(item, Mapping):
            raise SchemaValidationError("itinerary items must be mappings")
        itinerary.append(dict(item))
    return tuple(itinerary)


def _coerce_candidate_package(
    package: CandidateEvidencePackage | Mapping[str, Any],
) -> CandidateEvidencePackage:
    """Accept schema or mapping package payloads."""

    if isinstance(package, CandidateEvidencePackage):
        return package
    if isinstance(package, Mapping):
        return CandidateEvidencePackage.from_mapping(package)
    raise SchemaValidationError("package must be a CandidateEvidencePackage or mapping")


def _festival_verification_tuple(
    festival_verifications: Sequence[Any],
) -> tuple[FestivalVerification, ...]:
    """Normalize festival verifier outputs."""

    if not isinstance(festival_verifications, Sequence) or isinstance(
        festival_verifications,
        (str, bytes),
    ):
        raise SchemaValidationError("festival_verifications must be a sequence")
    return tuple(
        item
        if isinstance(item, FestivalVerification)
        else FestivalVerification.from_mapping(_mapping(item, "festival_verification"))
        for item in festival_verifications
    )


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Copy one mapping payload."""

    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return dict(value)


def _error(index: int, code: str, message: str) -> dict[str, Any]:
    """Build one compact validation error."""

    return {
        "item_index": index,
        "code": code,
        "message": message,
    }


__all__ = [
    "RESPONSIBILITY",
    "TOOL_NAME",
    "validate_planner_output",
]
