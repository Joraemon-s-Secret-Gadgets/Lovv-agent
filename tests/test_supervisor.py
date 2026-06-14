"""Tests for Supervisor Router helper contracts."""

from __future__ import annotations

import unittest

from lovv_agent.agents.supervisor import (
    MATRIX_COMPLETE,
    MATRIX_NOT_APPLICABLE,
    MATRIX_PARTIAL,
    MATRIX_PENDING,
    create_fulfilled_matrix,
    mark_matrix_complete,
    mark_matrix_not_applicable,
    mark_matrix_partial,
    matrix_has_pending_work,
    set_matrix_status,
)
from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.state import FULFILLED_MATRIX_KEYS, FULFILLED_MATRIX_STATUSES


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


if __name__ == "__main__":
    unittest.main()
