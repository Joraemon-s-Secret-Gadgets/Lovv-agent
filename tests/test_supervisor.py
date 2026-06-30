"""Tests for Supervisor Router helper contracts."""

from __future__ import annotations

import unittest

from lovv_agent.agents.supervisor import (
    MATRIX_COMPLETE,
    MATRIX_NOT_APPLICABLE,
    MATRIX_PARTIAL,
    MATRIX_PENDING,
    MAX_PLANNER_VALIDATION_RETRIES,
    NODE_CANDIDATE_EVIDENCE,
    NODE_END_WAIT_USER,
    NODE_FESTIVAL_VERIFIER,
    NODE_PLANNER,
    NODE_RESPONSE_PACKAGER,
    SupervisorRouter,
    create_fulfilled_matrix,
    decide_supervisor_route,
    mark_matrix_complete,
    mark_matrix_not_applicable,
    mark_matrix_partial,
    matrix_has_pending_work,
    set_matrix_status,
)
from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    SchemaValidationError,
    SelectedCity,
)
from lovv_agent.state import FULFILLED_MATRIX_KEYS, FULFILLED_MATRIX_STATUSES


def _candidate_package(
    *,
    status: str = "ok",
    selected_city: bool = True,
    recommended_places: bool = True,
    needs_clarification: bool = False,
    clarifying_question: str | None = None,
) -> CandidateEvidencePackage:
    """Create a compact Candidate Evidence package for routing tests."""

    return CandidateEvidencePackage(
        status=status,
        selected_city=(
            SelectedCity(
                city_id="city-1",
                city_name_ko="샘플시",
                country="KR",
            )
            if selected_city
            else None
        ),
        recommended_places=(
            ({"place_id": "place-1", "title": "샘플 명소"},)
            if recommended_places
            else ()
        ),
        needs_clarification=needs_clarification,
        clarifying_question=clarifying_question,
    )


class SupervisorMatrixTest(unittest.TestCase):
    """Validate fulfilled-matrix state transitions for Task 3.1."""

    def test_matrix_keys_and_statuses_are_fixed(self) -> None:
        self.assertEqual(FULFILLED_MATRIX_KEYS, ("evidence", "festival", "planning"))
        self.assertEqual(FULFILLED_MATRIX_STATUSES, ("X", "O", "△", "N/A"))
        self.assertEqual(MATRIX_PENDING, "X")
        self.assertEqual(MATRIX_COMPLETE, "O")
        self.assertEqual(MATRIX_PARTIAL, "△")
        self.assertEqual(MATRIX_NOT_APPLICABLE, "N/A")

    def test_create_matrix_marks_festival_pending_when_included(self) -> None:
        matrix = create_fulfilled_matrix(include_festivals=True)

        self.assertEqual(
            matrix,
            {"evidence": "X", "festival": "X", "planning": "X"},
        )
        self.assertTrue(matrix_has_pending_work(matrix))

    def test_create_matrix_marks_festival_not_applicable_when_excluded(self) -> None:
        matrix = create_fulfilled_matrix(include_festivals=False)

        self.assertEqual(
            matrix,
            {"evidence": "X", "festival": "N/A", "planning": "X"},
        )
        self.assertTrue(matrix_has_pending_work(matrix))

    def test_matrix_status_transition_returns_validated_copy(self) -> None:
        matrix = create_fulfilled_matrix(include_festivals=True)

        updated, transition = mark_matrix_complete(matrix, "evidence")

        self.assertEqual(matrix["evidence"], "X")
        self.assertEqual(updated["evidence"], "O")
        self.assertEqual(transition.key, "evidence")
        self.assertEqual(transition.previous_status, "X")
        self.assertEqual(transition.next_status, "O")

    def test_matrix_partial_and_not_applicable_transitions(self) -> None:
        matrix = create_fulfilled_matrix(include_festivals=True)

        partial, partial_transition = mark_matrix_partial(matrix, "planning")
        skipped, skipped_transition = mark_matrix_not_applicable(partial, "festival")

        self.assertEqual(partial["planning"], "△")
        self.assertEqual(partial_transition.next_status, "△")
        self.assertEqual(skipped["festival"], "N/A")
        self.assertEqual(skipped_transition.previous_status, "X")

    def test_matrix_has_pending_work_returns_false_after_all_terminal(self) -> None:
        matrix = {
            "evidence": "O",
            "festival": "N/A",
            "planning": "O",
        }

        self.assertFalse(matrix_has_pending_work(matrix))

    def test_invalid_matrix_key_fails_validation(self) -> None:
        matrix = create_fulfilled_matrix(include_festivals=True)

        with self.assertRaises(SchemaValidationError):
            set_matrix_status(matrix, "unknown", MATRIX_COMPLETE)

    def test_invalid_matrix_value_fails_validation(self) -> None:
        matrix = create_fulfilled_matrix(include_festivals=True)

        with self.assertRaises(SchemaValidationError):
            set_matrix_status(matrix, "evidence", "DONE")

        with self.assertRaises(SchemaValidationError):
            matrix_has_pending_work({"evidence": "X", "festival": "X", "planning": "DONE"})


class SupervisorRoutingTest(unittest.TestCase):
    """Validate deterministic route decisions for Task 3.2."""

    def test_routing_starts_with_candidate_evidence(self) -> None:
        decision = SupervisorRouter().decide(
            fulfilled_matrix=create_fulfilled_matrix(include_festivals=True),
            include_festivals=True,
        )

        self.assertEqual(decision.next_node, NODE_CANDIDATE_EVIDENCE)
        self.assertEqual(decision.reason, "pending_evidence")

    def test_clarification_routes_to_user_wait_and_blocks_downstream(self) -> None:
        decision = decide_supervisor_route(
            fulfilled_matrix=create_fulfilled_matrix(include_festivals=True),
            include_festivals=True,
            completed_group="evidence",
            candidate_evidence_package=_candidate_package(
                status="no_candidate",
                selected_city=False,
                recommended_places=False,
                needs_clarification=True,
                clarifying_question="축제 조건 없이 계속할까요?",
            ),
        )

        self.assertEqual(decision.next_node, NODE_END_WAIT_USER)
        self.assertTrue(decision.needs_clarification)
        self.assertEqual(decision.clarifying_question, "축제 조건 없이 계속할까요?")
        self.assertEqual(decision.fulfilled_matrix["festival"], MATRIX_PENDING)
        self.assertEqual(decision.fulfilled_matrix["planning"], MATRIX_PENDING)

    def test_include_festivals_false_skips_verifier_after_evidence(self) -> None:
        decision = decide_supervisor_route(
            fulfilled_matrix=create_fulfilled_matrix(include_festivals=True),
            include_festivals=False,
            completed_group="evidence",
            candidate_evidence_package=_candidate_package(status="ok"),
        )

        self.assertEqual(decision.next_node, NODE_PLANNER)
        self.assertEqual(decision.fulfilled_matrix["evidence"], MATRIX_COMPLETE)
        self.assertEqual(decision.fulfilled_matrix["festival"], MATRIX_NOT_APPLICABLE)

    def test_routing_order_sends_festival_before_planning_when_included(self) -> None:
        after_evidence = decide_supervisor_route(
            fulfilled_matrix=create_fulfilled_matrix(include_festivals=True),
            include_festivals=True,
            completed_group="evidence",
            candidate_evidence_package=_candidate_package(status="ok"),
        )

        self.assertEqual(after_evidence.next_node, NODE_FESTIVAL_VERIFIER)
        self.assertEqual(after_evidence.reason, "pending_festival")

        after_festival = decide_supervisor_route(
            fulfilled_matrix=after_evidence.fulfilled_matrix,
            include_festivals=True,
            completed_group="festival",
        )

        self.assertEqual(after_festival.next_node, NODE_PLANNER)
        self.assertEqual(after_festival.reason, "pending_planning")

    def test_safe_insufficient_candidates_can_proceed_to_planner(self) -> None:
        decision = decide_supervisor_route(
            fulfilled_matrix=create_fulfilled_matrix(include_festivals=False),
            include_festivals=False,
            completed_group="evidence",
            candidate_evidence_package=_candidate_package(status="insufficient_candidates"),
        )

        self.assertEqual(decision.next_node, NODE_PLANNER)
        self.assertEqual(decision.fulfilled_matrix["evidence"], MATRIX_PARTIAL)

    def test_unsafe_insufficient_candidates_do_not_call_planner(self) -> None:
        decision = decide_supervisor_route(
            fulfilled_matrix=create_fulfilled_matrix(include_festivals=False),
            include_festivals=False,
            completed_group="evidence",
            candidate_evidence_package=_candidate_package(
                status="insufficient_candidates",
                selected_city=False,
                recommended_places=False,
            ),
        )

        self.assertEqual(decision.next_node, NODE_RESPONSE_PACKAGER)
        self.assertEqual(decision.reason, "candidate_evidence_not_safe_for_planner")
        self.assertEqual(decision.fulfilled_matrix["evidence"], MATRIX_PARTIAL)

    def test_evidence_status_without_package_does_not_call_planner(self) -> None:
        decision = decide_supervisor_route(
            fulfilled_matrix=create_fulfilled_matrix(include_festivals=False),
            include_festivals=False,
            completed_group="evidence",
            worker_status="ok",
        )

        self.assertEqual(decision.next_node, NODE_RESPONSE_PACKAGER)
        self.assertEqual(decision.reason, "candidate_evidence_not_safe_for_planner")
        self.assertEqual(decision.fulfilled_matrix["evidence"], MATRIX_PARTIAL)


class SupervisorRetryTest(unittest.TestCase):
    """Validate Planner validation retry limits for Task 3.3."""

    def test_planner_validation_failure_retries_until_limit(self) -> None:
        matrix = {
            "evidence": MATRIX_COMPLETE,
            "festival": MATRIX_NOT_APPLICABLE,
            "planning": MATRIX_PENDING,
        }

        first_retry = decide_supervisor_route(
            fulfilled_matrix=matrix,
            include_festivals=False,
            completed_group="planning",
            validation_retry_count=0,
            planner_validation_passed=False,
        )
        second_retry = decide_supervisor_route(
            fulfilled_matrix=first_retry.fulfilled_matrix,
            include_festivals=False,
            completed_group="planning",
            validation_retry_count=first_retry.validation_retry_count,
            planner_validation_result={"valid": False},
        )

        self.assertEqual(first_retry.next_node, NODE_PLANNER)
        self.assertEqual(first_retry.validation_retry_count, 1)
        self.assertEqual(first_retry.fulfilled_matrix["planning"], MATRIX_PENDING)
        self.assertEqual(second_retry.next_node, NODE_PLANNER)
        self.assertEqual(
            second_retry.validation_retry_count,
            MAX_PLANNER_VALIDATION_RETRIES,
        )
        self.assertEqual(second_retry.reason, "planner_validation_retry")

    def test_planner_validation_retry_exhaustion_routes_to_safe_fallback(self) -> None:
        matrix = {
            "evidence": MATRIX_COMPLETE,
            "festival": MATRIX_NOT_APPLICABLE,
            "planning": MATRIX_PENDING,
        }

        decision = decide_supervisor_route(
            fulfilled_matrix=matrix,
            include_festivals=False,
            completed_group="planning",
            validation_retry_count=MAX_PLANNER_VALIDATION_RETRIES,
            planner_validation_result={"status": "invalid"},
        )

        self.assertEqual(decision.next_node, NODE_RESPONSE_PACKAGER)
        self.assertEqual(decision.validation_retry_count, MAX_PLANNER_VALIDATION_RETRIES)
        self.assertEqual(decision.fulfilled_matrix["planning"], MATRIX_PARTIAL)
        self.assertEqual(decision.reason, "planner_validation_retry_exhausted")

    def test_stale_over_limit_retry_count_is_clamped_to_limit(self) -> None:
        matrix = {
            "evidence": MATRIX_COMPLETE,
            "festival": MATRIX_NOT_APPLICABLE,
            "planning": MATRIX_PENDING,
        }

        decision = decide_supervisor_route(
            fulfilled_matrix=matrix,
            include_festivals=False,
            completed_group="planning",
            validation_retry_count=99,
            planner_validation_passed=False,
        )

        self.assertEqual(decision.next_node, NODE_RESPONSE_PACKAGER)
        self.assertEqual(decision.validation_retry_count, MAX_PLANNER_VALIDATION_RETRIES)

    def test_planner_validation_success_completes_planning(self) -> None:
        matrix = {
            "evidence": MATRIX_COMPLETE,
            "festival": MATRIX_NOT_APPLICABLE,
            "planning": MATRIX_PENDING,
        }

        decision = decide_supervisor_route(
            fulfilled_matrix=matrix,
            include_festivals=False,
            completed_group="planning",
            validation_retry_count=1,
            planner_validation_result={"passed": True},
        )

        self.assertEqual(decision.next_node, NODE_RESPONSE_PACKAGER)
        self.assertEqual(decision.validation_retry_count, 1)
        self.assertEqual(decision.fulfilled_matrix["planning"], MATRIX_COMPLETE)
        self.assertEqual(decision.reason, "ready_to_package")

    def test_invalid_retry_count_fails_validation(self) -> None:
        matrix = {
            "evidence": MATRIX_COMPLETE,
            "festival": MATRIX_NOT_APPLICABLE,
            "planning": MATRIX_PENDING,
        }

        with self.assertRaises(SchemaValidationError):
            decide_supervisor_route(
                fulfilled_matrix=matrix,
                include_festivals=False,
                completed_group="planning",
                validation_retry_count=-1,
                planner_validation_passed=False,
            )


if __name__ == "__main__":
    unittest.main()
