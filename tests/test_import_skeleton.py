"""Smoke tests for the Task 1.1 package skeleton."""

from __future__ import annotations

import unittest

import lovv_agent
from lovv_agent.graph import CLARIFICATION_TERMINAL, get_graph_skeleton
from lovv_agent.state import STATE_GROUPS


class PackageSkeletonTest(unittest.TestCase):
    """Verify that package imports stay side-effect free and stable."""

    def test_package_has_version(self) -> None:
        self.assertTrue(lovv_agent.__version__)

    def test_graph_skeleton_contains_expected_boundary_nodes(self) -> None:
        graph_nodes = get_graph_skeleton()

        self.assertIn("intent_agent", graph_nodes)
        self.assertIn("candidate_evidence_agent", graph_nodes)
        self.assertIn("response_packager", graph_nodes)
        self.assertEqual(CLARIFICATION_TERMINAL, "END_WAIT_USER")

    def test_state_groups_match_spec_boundaries(self) -> None:
        self.assertEqual(
            STATE_GROUPS,
            (
                "request",
                "conversation",
                "trace",
                "intent",
                "routing",
                "evidence",
                "festival",
                "planning",
                "serving",
            ),
        )


if __name__ == "__main__":
    unittest.main()
