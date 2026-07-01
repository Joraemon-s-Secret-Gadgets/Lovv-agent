"""Tests for deterministic candidate selection quota behavior."""

from __future__ import annotations

import unittest

from lovv_agent_v2.agents.city_select.scoring.selection import (
    CandidateSelectionHelper,
    candidate_budgets_for_trip,
    select_primary_with_theme_quotas,
)


def candidate(
    place_id: str,
    title: str,
    score: float,
    themes: list[str],
) -> dict[str, object]:
    """Build one scored candidate payload."""

    return {
        "place_id": place_id,
        "title": title,
        "place_score": score,
        "theme_tags": themes,
    }


class CandidateBudgetTest(unittest.TestCase):
    def test_candidate_budgets_for_trip(self) -> None:
        self.assertEqual(candidate_budgets_for_trip("daytrip"), 6)
        self.assertEqual(candidate_budgets_for_trip("2d1n"), 10)
        self.assertEqual(candidate_budgets_for_trip("3d2n"), 14)
        self.assertEqual(candidate_budgets_for_trip("4d3n"), 18)
        self.assertEqual(candidate_budgets_for_trip("5d4n"), 18)


class CandidateSelectionTest(unittest.TestCase):
    def test_select_primary_fills_min_quota_before_score_tail(self) -> None:
        candidates = [
            candidate("sea-1", "Sea 1", 1.00, ["바다·해안"]),
            candidate("sea-2", "Sea 2", 0.99, ["바다·해안"]),
            candidate("sea-3", "Sea 3", 0.98, ["바다·해안"]),
            candidate("sea-4", "Sea 4", 0.97, ["바다·해안"]),
            candidate("sea-5", "Sea 5", 0.96, ["바다·해안"]),
            candidate("history-1", "History 1", 0.30, ["역사·문화"]),
            candidate("history-2", "History 2", 0.29, ["역사·문화"]),
        ]

        result = select_primary_with_theme_quotas(
            candidates,
            ["바다·해안", "역사·문화"],
            primary_budget=6,
        )

        primary_ids = [item["place_id"] for item in result.primary]
        self.assertIn("history-1", primary_ids)
        self.assertNotIn("sea-5", primary_ids)
        self.assertEqual(result.coverage_audit["theme_min_quota"], 1)
        self.assertEqual(
            result.coverage_audit["primary_theme_counts"],
            {"바다·해안": 4, "역사·문화": 2},
        )

    def test_soft_max_relaxes_only_when_slots_would_remain_empty(self) -> None:
        candidates = [
            candidate("sea-1", "Sea 1", 1.00, ["바다·해안"]),
            candidate("sea-2", "Sea 2", 0.99, ["바다·해안"]),
            candidate("sea-3", "Sea 3", 0.98, ["바다·해안"]),
            candidate("sea-4", "Sea 4", 0.97, ["바다·해안"]),
            candidate("sea-5", "Sea 5", 0.96, ["바다·해안"]),
            candidate("history-1", "History 1", 0.50, ["역사·문화"]),
            candidate("history-2", "History 2", 0.49, ["역사·문화"]),
        ]

        result = CandidateSelectionHelper().select_primary_with_theme_quotas(
            candidates,
            ["바다·해안", "역사·문화"],
            primary_budget=6,
        )

        self.assertEqual(len(result.primary), 6)
        self.assertTrue(result.coverage_audit["max_quota_relaxed"])
        self.assertEqual(result.coverage_audit["relaxed_slots"], 1)
        self.assertEqual(
            result.coverage_audit["primary_theme_counts"],
            {"바다·해안": 4, "역사·문화": 2},
        )

    def test_title_dedup_runs_before_primary_selection(self) -> None:
        candidates = [
            candidate("P-1", "Same Title", 1.0, ["바다·해안"]),
            candidate("P-2", " same title ", 0.9, ["바다·해안"]),
            candidate("P-3", "Other Title", 0.8, ["바다·해안"]),
            candidate("P-4", "", 0.7, ["바다·해안"]),
            candidate("P-5", "", 0.6, ["바다·해안"]),
        ]

        result = select_primary_with_theme_quotas(
            candidates,
            ["바다·해안"],
            primary_budget=3,
        )

        selected_ids = [item["place_id"] for item in result.primary]
        self.assertIn("P-1", selected_ids)
        self.assertNotIn("P-2", selected_ids)
        self.assertIn("P-4", selected_ids)
        self.assertEqual(result.coverage_audit["deduplicated_title_count"], 1)

    def test_quota_shortfall_and_unfilled_slots_are_audited(self) -> None:
        result = select_primary_with_theme_quotas(
            [
                candidate("sea-1", "Sea 1", 1.0, ["바다·해안"]),
                candidate("sea-2", "Sea 2", 0.9, ["바다·해안"]),
            ],
            ["바다·해안", "역사·문화"],
            primary_budget=6,
        )

        self.assertEqual(result.coverage_audit["min_quota_shortfalls"], {"역사·문화": 1})
        self.assertEqual(result.coverage_audit["unfilled_primary_slots"], 4)
        self.assertEqual(result.coverage_audit["planner_capacity"], "insufficient")

    def test_total_candidate_shortage_keeps_available_primary(self) -> None:
        result = select_primary_with_theme_quotas(
            [candidate("P-1", "Only", 1.0, ["자연"])],
            ["자연", "역사·문화"],
            primary_budget=4,
        )

        self.assertEqual([item["place_id"] for item in result.primary], ["P-1"])
        self.assertEqual(result.coverage_audit["min_quota_shortfalls"], {"역사·문화": 1})
        self.assertEqual(result.coverage_audit["unfilled_primary_slots"], 3)
        self.assertEqual(result.coverage_audit["planner_capacity"], "insufficient")

    def test_soft_max_relaxation_is_audit_not_failure_signal(self) -> None:
        result = select_primary_with_theme_quotas(
            [
                candidate("P-1", "A", 1.0, ["자연"]),
                candidate("P-2", "B", 0.9, ["자연"]),
                candidate("P-3", "C", 0.8, ["자연"]),
            ],
            ["자연", "역사·문화"],
            primary_budget=4,
        )

        self.assertTrue(result.coverage_audit["max_quota_relaxed"])
        self.assertGreater(result.coverage_audit["relaxed_slots"], 0)
        self.assertIn("역사·문화", result.coverage_audit["min_quota_shortfalls"])

    def test_no_searchable_themes_selects_by_score_without_quota(self) -> None:
        result = select_primary_with_theme_quotas(
            [
                candidate("P-1", "A", 0.9, ["미식·노포"]),
                candidate("P-2", "B", 0.8, ["미식·노포"]),
                candidate("P-3", "C", 0.7, ["미식·노포"]),
            ],
            [],
            primary_budget=2,
            required_themes=["미식·노포"],
            no_support_themes=["미식·노포"],
        )

        self.assertEqual([item["place_id"] for item in result.primary], ["P-1", "P-2"])
        self.assertEqual(result.coverage_audit["theme_min_quota"], 0)
        self.assertEqual(result.coverage_audit["no_support_themes"], ["미식·노포"])


if __name__ == "__main__":
    unittest.main()
