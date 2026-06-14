"""Supervisor Router helpers.

Planned responsibility:
- route between graph nodes using fulfilled matrix state,
- stop at END_WAIT_USER when clarification is required,
- enforce validation retry limits.

Task 3.1 implements fulfilled-matrix validation and transition helpers.
Task 3.2 adds deterministic route decisions and clarification stops.
Graph compilation and retry-limit behavior are handled in later subtasks.

The MVP Supervisor is deterministic. Later tasks may wrap this module behind a
swappable routing boundary so an experimental LLM Supervisor can be compared
against the same E2E fixtures after the deterministic baseline passes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lovv_agent.models.schemas import (
    CANDIDATE_EVIDENCE_STATUSES,
    CandidateEvidencePackage,
    SchemaValidationError,
    validate_clarification,
)
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

MATRIX_ROUTING_ORDER = ("evidence", "festival", "planning")

NODE_CANDIDATE_EVIDENCE = "candidate_evidence_agent"
NODE_FESTIVAL_VERIFIER = "festival_verifier_agent"
NODE_PLANNER = "planner_agent"
NODE_RESPONSE_PACKAGER = "response_packager"
NODE_END_WAIT_USER = "END_WAIT_USER"


@dataclass(frozen=True, slots=True)
class MatrixTransition:
    """Immutable record of a fulfilled-matrix status transition."""

    key: str
    previous_status: str
    next_status: str


@dataclass(frozen=True, slots=True)
class SupervisorRouteDecision:
    """Deterministic next-node decision produced by the Supervisor boundary."""

    next_node: str
    fulfilled_matrix: dict[str, str]
    needs_clarification: bool = False
    clarifying_question: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "next_node", _required_text(self.next_node, "next_node"))
        object.__setattr__(
            self,
            "fulfilled_matrix",
            validate_fulfilled_matrix(self.fulfilled_matrix),
        )
        object.__setattr__(self, "reason", _free_text(self.reason, "reason"))
        validate_clarification(self.needs_clarification, self.clarifying_question)


class SupervisorRouter:
    """Swappable deterministic routing boundary used before graph wiring.

    Future experiments may provide another object with the same ``decide``
    method, but the deterministic implementation remains the MVP source of
    truth and the hard-rule validation target.
    """

    def decide(
        self,
        *,
        fulfilled_matrix: Mapping[str, str],
        include_festivals: bool,
        completed_group: str | None = None,
        worker_status: str | None = None,
        needs_clarification: bool = False,
        clarifying_question: str | None = None,
        candidate_evidence_package: (
            CandidateEvidencePackage | Mapping[str, Any] | None
        ) = None,
    ) -> SupervisorRouteDecision:
        """Return the next route for the current graph state."""

        return decide_supervisor_route(
            fulfilled_matrix=fulfilled_matrix,
            include_festivals=include_festivals,
            completed_group=completed_group,
            worker_status=worker_status,
            needs_clarification=needs_clarification,
            clarifying_question=clarifying_question,
            candidate_evidence_package=candidate_evidence_package,
        )


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


def decide_supervisor_route(
    *,
    fulfilled_matrix: Mapping[str, str],
    include_festivals: bool,
    completed_group: str | None = None,
    worker_status: str | None = None,
    needs_clarification: bool = False,
    clarifying_question: str | None = None,
    candidate_evidence_package: (
        CandidateEvidencePackage | Mapping[str, Any] | None
    ) = None,
) -> SupervisorRouteDecision:
    """Decide the next graph node from matrix state and worker output."""

    matrix = _normalize_matrix_for_request(fulfilled_matrix, include_festivals)
    package = _coerce_candidate_evidence_package(candidate_evidence_package)
    clarified, question = _resolve_clarification(
        needs_clarification=needs_clarification,
        clarifying_question=clarifying_question,
        candidate_evidence_package=package,
    )
    if clarified:
        return SupervisorRouteDecision(
            next_node=NODE_END_WAIT_USER,
            fulfilled_matrix=matrix,
            needs_clarification=True,
            clarifying_question=question,
            reason="clarification_requested",
        )

    terminal_reason: str | None = None
    if completed_group is not None:
        matrix, terminal_reason = _apply_completed_group(
            matrix=matrix,
            completed_group=completed_group,
            include_festivals=include_festivals,
            worker_status=worker_status,
            candidate_evidence_package=package,
        )

    if terminal_reason is not None:
        return SupervisorRouteDecision(
            next_node=NODE_RESPONSE_PACKAGER,
            fulfilled_matrix=matrix,
            reason=terminal_reason,
        )

    next_node, reason = _next_pending_route(matrix)
    return SupervisorRouteDecision(
        next_node=next_node,
        fulfilled_matrix=matrix,
        reason=reason,
    )


def _normalize_matrix_for_request(
    matrix: Mapping[str, str],
    include_festivals: bool,
) -> dict[str, str]:
    """Validate matrix state and apply request-level skip rules."""

    if not isinstance(include_festivals, bool):
        raise SchemaValidationError("include_festivals must be a boolean")
    normalized = validate_fulfilled_matrix(matrix)
    if not include_festivals and normalized["festival"] != MATRIX_NOT_APPLICABLE:
        normalized, _ = mark_matrix_not_applicable(normalized, "festival")
    return normalized


def _resolve_clarification(
    *,
    needs_clarification: bool,
    clarifying_question: str | None,
    candidate_evidence_package: CandidateEvidencePackage | None,
) -> tuple[bool, str | None]:
    """Merge explicit worker clarification flags with package-level flags."""

    if not isinstance(needs_clarification, bool):
        raise SchemaValidationError("needs_clarification must be a boolean")

    package_needs_clarification = (
        candidate_evidence_package.needs_clarification
        if candidate_evidence_package is not None
        else False
    )
    resolved_needs_clarification = needs_clarification or package_needs_clarification
    resolved_question = clarifying_question
    if resolved_question is None and candidate_evidence_package is not None:
        resolved_question = candidate_evidence_package.clarifying_question

    validate_clarification(resolved_needs_clarification, resolved_question)
    return resolved_needs_clarification, resolved_question


def _apply_completed_group(
    *,
    matrix: Mapping[str, str],
    completed_group: str,
    include_festivals: bool,
    worker_status: str | None,
    candidate_evidence_package: CandidateEvidencePackage | None,
) -> tuple[dict[str, str], str | None]:
    """Apply one worker result to the matrix and return an optional terminal reason."""

    _validate_matrix_key(completed_group)
    if completed_group == "evidence":
        return _apply_candidate_evidence_result(
            matrix=matrix,
            worker_status=worker_status,
            candidate_evidence_package=candidate_evidence_package,
        )
    if completed_group == "festival" and not include_festivals:
        updated, _ = mark_matrix_not_applicable(matrix, "festival")
        return updated, None

    updated, _ = mark_matrix_complete(matrix, completed_group)
    return updated, None


def _apply_candidate_evidence_result(
    *,
    matrix: Mapping[str, str],
    worker_status: str | None,
    candidate_evidence_package: CandidateEvidencePackage | None,
) -> tuple[dict[str, str], str | None]:
    """Translate Candidate Evidence status into routing-safe matrix state."""

    status = worker_status
    if status is None and candidate_evidence_package is not None:
        status = candidate_evidence_package.status
    if status is None:
        raise SchemaValidationError("worker_status is required for evidence routing")
    if status not in CANDIDATE_EVIDENCE_STATUSES:
        allowed = ", ".join(CANDIDATE_EVIDENCE_STATUSES)
        raise SchemaValidationError(f"candidate evidence status must be one of: {allowed}")

    if status in {"ok", "insufficient_candidates"}:
        planner_safe = _candidate_package_can_feed_planner(candidate_evidence_package)
        next_status = (
            MATRIX_COMPLETE
            if status == "ok" and planner_safe
            else MATRIX_PARTIAL
        )
        updated, _ = set_matrix_status(matrix, "evidence", next_status)
        if not planner_safe:
            return updated, "candidate_evidence_not_safe_for_planner"
        return updated, None

    updated, _ = mark_matrix_partial(matrix, "evidence")
    return updated, f"candidate_evidence_{status}"


def _candidate_package_can_feed_planner(
    candidate_evidence_package: CandidateEvidencePackage | None,
) -> bool:
    """Return whether Candidate Evidence has the minimum grounded Planner inputs."""

    if candidate_evidence_package is None:
        return False
    return (
        candidate_evidence_package.selected_city is not None
        and bool(candidate_evidence_package.recommended_places)
    )


def _next_pending_route(matrix: Mapping[str, str]) -> tuple[str, str]:
    """Return the next node for the first pending matrix group."""

    validated = validate_fulfilled_matrix(matrix)
    for group in MATRIX_ROUTING_ORDER:
        if validated[group] != MATRIX_PENDING:
            continue
        if group == "evidence":
            return NODE_CANDIDATE_EVIDENCE, "pending_evidence"
        if group == "festival":
            return NODE_FESTIVAL_VERIFIER, "pending_festival"
        if group == "planning":
            return NODE_PLANNER, "pending_planning"
    return NODE_RESPONSE_PACKAGER, "ready_to_package"


def _coerce_candidate_evidence_package(
    package: CandidateEvidencePackage | Mapping[str, Any] | None,
) -> CandidateEvidencePackage | None:
    """Normalize optional Candidate Evidence package mappings for routing checks."""

    if package is None:
        return None
    if isinstance(package, CandidateEvidencePackage):
        return package
    if isinstance(package, Mapping):
        return CandidateEvidencePackage.from_mapping(package)
    raise SchemaValidationError("candidate_evidence_package must be a mapping or schema")


def _required_text(value: str, field_name: str) -> str:
    """Validate a non-empty routing string."""

    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _free_text(value: str, field_name: str) -> str:
    """Validate routing text that may be empty."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    return value.strip()


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
    "MATRIX_ROUTING_ORDER",
    "NODE_NAME",
    "NODE_CANDIDATE_EVIDENCE",
    "NODE_END_WAIT_USER",
    "NODE_FESTIVAL_VERIFIER",
    "NODE_PLANNER",
    "NODE_RESPONSE_PACKAGER",
    "OUT_OF_SCOPE",
    "RESPONSIBILITY",
    "MatrixTransition",
    "SupervisorRouteDecision",
    "SupervisorRouter",
    "create_fulfilled_matrix",
    "decide_supervisor_route",
    "mark_matrix_complete",
    "mark_matrix_not_applicable",
    "mark_matrix_partial",
    "matrix_has_pending_work",
    "set_matrix_status",
]
