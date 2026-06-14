"""Supervisor Router helpers.

Planned responsibility:
- route between graph nodes using fulfilled matrix state,
- stop at END_WAIT_USER when clarification is required,
- enforce validation retry limits.

Task 3.1 implements only fulfilled-matrix validation and transition helpers.
Routing decisions, graph compilation, and retry-limit behavior are handled in
later Task 3 subtasks.

The MVP Supervisor is deterministic. Later tasks may wrap this module behind a
swappable routing boundary so an experimental LLM Supervisor can be compared
against the same E2E fixtures after the deterministic baseline passes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.state import (
    FULFILLED_MATRIX_KEYS,
    FULFILLED_MATRIX_STATUSES,
    default_fulfilled_matrix,
    validate_fulfilled_matrix,
)

NODE_NAME = "supervisor_router"

RESPONSIBILITY = "Route graph execution by status and fulfilled matrix."

OUT_OF_SCOPE = (
    "raw_retrieval_interpretation",
    "planner_generation",
)

MATRIX_PENDING = "X"
MATRIX_COMPLETE = "O"
MATRIX_PARTIAL = "△"
MATRIX_NOT_APPLICABLE = "N/A"


@dataclass(frozen=True, slots=True)
class MatrixTransition:
    """Immutable record of a fulfilled-matrix status transition."""

    key: str
    previous_status: str
    next_status: str


def create_fulfilled_matrix(*, include_festivals: bool = True) -> dict[str, str]:
    """Create the initial Supervisor matrix for a graph run."""

    matrix = default_fulfilled_matrix()
    if not include_festivals:
        matrix["festival"] = MATRIX_NOT_APPLICABLE
    return validate_fulfilled_matrix(matrix)


def set_matrix_status(
    matrix: Mapping[str, str],
    key: str,
    status: str,
) -> tuple[dict[str, str], MatrixTransition]:
    """Return a validated matrix copy with one status updated."""

    validated = validate_fulfilled_matrix(matrix)
    _validate_matrix_key(key)
    _validate_matrix_status(status)

    previous_status = validated[key]
    updated = dict(validated)
    updated[key] = status
    return validate_fulfilled_matrix(updated), MatrixTransition(
        key=key,
        previous_status=previous_status,
        next_status=status,
    )


def mark_matrix_complete(
    matrix: Mapping[str, str],
    key: str,
) -> tuple[dict[str, str], MatrixTransition]:
    """Mark one matrix group complete."""

    return set_matrix_status(matrix, key, MATRIX_COMPLETE)


def mark_matrix_partial(
    matrix: Mapping[str, str],
    key: str,
) -> tuple[dict[str, str], MatrixTransition]:
    """Mark one matrix group partially fulfilled."""

    return set_matrix_status(matrix, key, MATRIX_PARTIAL)


def mark_matrix_not_applicable(
    matrix: Mapping[str, str],
    key: str,
) -> tuple[dict[str, str], MatrixTransition]:
    """Mark one matrix group as not applicable for the current request."""

    return set_matrix_status(matrix, key, MATRIX_NOT_APPLICABLE)


def matrix_has_pending_work(matrix: Mapping[str, str]) -> bool:
    """Return whether any matrix group is still pending."""

    validated = validate_fulfilled_matrix(matrix)
    return any(status == MATRIX_PENDING for status in validated.values())


def _validate_matrix_key(key: str) -> None:
    """Validate a fulfilled-matrix key."""

    if key not in FULFILLED_MATRIX_KEYS:
        allowed = ", ".join(FULFILLED_MATRIX_KEYS)
        raise SchemaValidationError(f"matrix key must be one of: {allowed}")


def _validate_matrix_status(status: str) -> None:
    """Validate a fulfilled-matrix status."""

    if status not in FULFILLED_MATRIX_STATUSES:
        allowed = ", ".join(FULFILLED_MATRIX_STATUSES)
        raise SchemaValidationError(f"matrix status must be one of: {allowed}")


__all__ = [
    "MATRIX_COMPLETE",
    "MATRIX_NOT_APPLICABLE",
    "MATRIX_PARTIAL",
    "MATRIX_PENDING",
    "NODE_NAME",
    "OUT_OF_SCOPE",
    "RESPONSIBILITY",
    "MatrixTransition",
    "create_fulfilled_matrix",
    "mark_matrix_complete",
    "mark_matrix_not_applicable",
    "mark_matrix_partial",
    "matrix_has_pending_work",
    "set_matrix_status",
]
