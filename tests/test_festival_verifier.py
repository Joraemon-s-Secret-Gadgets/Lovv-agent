"""Tests for Festival Verifier Agent behavior."""

from __future__ import annotations

import unittest

from lovv_agent.agents.festival_verifier import (
    FestivalVerifierAgent,
    build_festival_verifier_input,
)
from lovv_agent.models.schemas import CandidateEvidencePackage, SelectedCity


def festival_payload(
    festival_id: str,
    *,
    city_id: str = "KR-A",
    event_start_date: str = "2026-10-10",
) -> dict[str, object]:
    """Return a compact selected festival candidate payload."""

    return {
        "festival_id": festival_id,
        "name": f"축제 {festival_id}",
        "country": "KR",
        "city_id": city_id,
        "city_name": "에이군",
        "month": 10,
        "theme_tags": ["바다·해안"],
        "assigned_theme": "바다·해안",
        "event_start_date": event_start_date,
        "event_end_date": "2026-10-12",
        "source": "dynamodb",
    }


def package_with_festivals() -> CandidateEvidencePackage:
    """Return a Candidate Evidence package with broad and selected festivals."""

    return CandidateEvidencePackage(
        status="ok",
        mode="festival_seeded_city_discovery",
        selected_city=SelectedCity(
            city_id="KR-A",
            city_name_ko="에이군",
            country="KR",
        ),
        festival_candidates=(
            festival_payload("F-A", city_id="KR-A"),
            festival_payload("F-B", city_id="KR-B"),
        ),
        selected_festival_candidates=(festival_payload("F-A", city_id="KR-A"),),
    )


class FestivalVerifierScopeTest(unittest.TestCase):
    """Validate Task 7.1 verifier scope and skip behavior."""

    def test_scope_reads_only_selected_festival_candidates(self) -> None:
        verifier_input = build_festival_verifier_input(
            include_festivals=True,
            travel_year=2026,
            travel_month=10,
            candidate_evidence_package=package_with_festivals(),
        )

        self.assertEqual(len(verifier_input.selected_festival_candidates), 1)
        self.assertEqual(
            verifier_input.selected_festival_candidates[0]["festival_id"],
            "F-A",
        )

    def test_skip_when_include_festivals_false(self) -> None:
        agent = FestivalVerifierAgent()
        verifier_input = agent.build_input(
            include_festivals=False,
            travel_year=2026,
            travel_month=10,
            candidate_evidence_package=package_with_festivals(),
        )

        result = agent.verify(verifier_input)

        self.assertEqual(result.status, "skipped")
        self.assertTrue(result.skipped)
        self.assertEqual(result.verifications, ())
        self.assertIn("include_festivals_false", result.failure_signals)

    def test_empty_selected_candidates_returns_no_candidate_state(self) -> None:
        package = CandidateEvidencePackage(
            status="ok",
            mode="festival_seeded_city_discovery",
            selected_city=SelectedCity(
                city_id="KR-A",
                city_name_ko="에이군",
                country="KR",
            ),
            festival_candidates=(festival_payload("F-A"),),
            selected_festival_candidates=(),
        )
        agent = FestivalVerifierAgent()
        verifier_input = agent.build_input(
            include_festivals=True,
            travel_year=2026,
            travel_month=10,
            candidate_evidence_package=package,
        )

        result = agent.verify(verifier_input)

        self.assertEqual(result.status, "no_candidate")
        self.assertEqual(result.verifications, ())
        self.assertIn("no_selected_festival_candidates", result.failure_signals)

    def test_mapping_package_input_is_accepted(self) -> None:
        verifier_input = build_festival_verifier_input(
            include_festivals=True,
            travel_year=2026,
            travel_month=10,
            candidate_evidence_package=package_with_festivals().to_dict(),
        )

        self.assertEqual(verifier_input.travel_year, 2026)
        self.assertEqual(verifier_input.travel_month, 10)
        self.assertEqual(len(verifier_input.selected_festival_candidates), 1)


if __name__ == "__main__":
    unittest.main()
