"""Tests for Festival Verifier Agent behavior."""

from __future__ import annotations

import unittest

from lovv_agent.agents.festival_verifier import (
    FestivalVerifierAgent,
    build_festival_cache_key,
    build_festival_verifier_input,
    normalize_festival_date,
    verify_festival_candidate,
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


class FestivalVerifierDatePolicyTest(unittest.TestCase):
    """Validate Task 7.2 date normalization and initial policy."""

    def test_normalize_date_accepts_event_start_date_variants(self) -> None:
        self.assertEqual(normalize_festival_date("2026-10-10").isoformat(), "2026-10-10")
        self.assertEqual(normalize_festival_date("2026.10.10").isoformat(), "2026-10-10")
        self.assertEqual(normalize_festival_date("2026/10/10").isoformat(), "2026-10-10")
        self.assertEqual(normalize_festival_date("20261010").isoformat(), "2026-10-10")

    def test_confirmed_requires_start_year_matching_travel_year(self) -> None:
        verification = verify_festival_candidate(
            festival_payload("F-A", event_start_date="2026-10-10"),
            travel_year=2026,
            travel_month=10,
        )

        self.assertEqual(verification.date_status, "confirmed")
        self.assertTrue(verification.is_applicable_to_trip)
        self.assertEqual(verification.planner_policy, "placeable")
        self.assertEqual(verification.start_date, "2026-10-10")

    def test_outdated_when_start_year_differs_from_travel_year(self) -> None:
        verification = verify_festival_candidate(
            festival_payload("F-A", event_start_date="2025-10-10"),
            travel_year=2026,
            travel_month=10,
        )

        self.assertEqual(verification.date_status, "outdated")
        self.assertEqual(verification.planner_policy, "not_placeable")
        self.assertTrue(verification.is_applicable_to_trip)

    def test_unknown_without_start_date(self) -> None:
        payload = festival_payload("F-A")
        payload.pop("event_start_date")

        verification = verify_festival_candidate(
            payload,
            travel_year=2026,
            travel_month=10,
        )

        self.assertEqual(verification.date_status, "unknown")
        self.assertFalse(verification.is_applicable_to_trip)
        self.assertEqual(verification.planner_policy, "not_placeable")

    def test_month_overlap_uses_start_and_end_date_range(self) -> None:
        payload = festival_payload("F-A", event_start_date="2026-09-29")
        payload["event_end_date"] = "2026-10-03"

        verification = verify_festival_candidate(
            payload,
            travel_year=2026,
            travel_month=10,
        )

        self.assertEqual(verification.date_status, "confirmed")
        self.assertTrue(verification.is_applicable_to_trip)
        self.assertEqual(verification.planner_policy, "placeable")

    def test_agent_verify_returns_verification_tuple(self) -> None:
        agent = FestivalVerifierAgent()
        verifier_input = agent.build_input(
            include_festivals=True,
            travel_year=2026,
            travel_month=10,
            candidate_evidence_package=package_with_festivals(),
        )

        result = agent.verify(verifier_input)

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.verifications), 1)
        self.assertEqual(result.verifications[0].date_status, "confirmed")


class FakeCache:
    """Tiny cache adapter for verifier cache-boundary tests."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, dict[str, object]]] = []

    def get(self, key: str) -> dict[str, object] | None:
        self.get_calls.append(key)
        return self.values.get(key)

    def set(self, key: str, value: dict[str, object]) -> None:
        self.set_calls.append((key, value))
        self.values[key] = dict(value)


class FestivalVerifierCacheBoundaryTest(unittest.TestCase):
    """Validate Task 7.3 cache key and status policy."""

    def test_cache_key_uses_festival_id_and_travel_year(self) -> None:
        self.assertEqual(
            build_festival_cache_key(festival_id="F-A", travel_year=2026),
            "F-A:2026",
        )

    def test_verified_result_is_written_to_cache(self) -> None:
        cache = FakeCache()

        verification = verify_festival_candidate(
            festival_payload("F-A"),
            travel_year=2026,
            travel_month=10,
            cache_adapter=cache,
        )

        self.assertEqual(verification.date_status, "confirmed")
        self.assertEqual(cache.get_calls, ["F-A:2026"])
        self.assertEqual(cache.set_calls[0][0], "F-A:2026")
        self.assertEqual(cache.values["F-A:2026"]["date_status"], "confirmed")

    def test_cached_date_status_recalculates_request_month_applicability(self) -> None:
        cache = FakeCache()
        cache.values["F-A:2026"] = {
            "date_status": "confirmed",
            "start_date": "2026-10-10",
            "end_date": "2026-10-12",
            "source_type": "cache",
            "confidence": 0.7,
        }

        verification = verify_festival_candidate(
            festival_payload("F-A"),
            travel_year=2026,
            travel_month=11,
            cache_adapter=cache,
        )

        self.assertEqual(verification.date_status, "confirmed")
        self.assertFalse(verification.is_applicable_to_trip)
        self.assertEqual(verification.planner_policy, "not_placeable")

    def test_tentative_status_is_not_placeable(self) -> None:
        payload = festival_payload("F-A")
        payload["date_status"] = "tentative"

        verification = verify_festival_candidate(
            payload,
            travel_year=2026,
            travel_month=10,
        )

        self.assertEqual(verification.date_status, "tentative")
        self.assertTrue(verification.is_applicable_to_trip)
        self.assertEqual(verification.planner_policy, "not_placeable")

    def test_full_status_suite_covers_skipped_unknown_outdated_and_no_candidate(self) -> None:
        skipped = FestivalVerifierAgent().verify(
            build_festival_verifier_input(
                include_festivals=False,
                travel_year=2026,
                travel_month=10,
                candidate_evidence_package=package_with_festivals(),
            ),
        )
        no_candidate = FestivalVerifierAgent().verify(
            build_festival_verifier_input(
                include_festivals=True,
                travel_year=2026,
                travel_month=10,
                candidate_evidence_package=None,
            ),
        )
        unknown_payload = festival_payload("F-UNKNOWN")
        unknown_payload.pop("event_start_date")
        unknown = verify_festival_candidate(
            unknown_payload,
            travel_year=2026,
            travel_month=10,
        )
        outdated = verify_festival_candidate(
            festival_payload("F-OLD", event_start_date="2025-10-10"),
            travel_year=2026,
            travel_month=10,
        )

        self.assertEqual(skipped.status, "skipped")
        self.assertEqual(no_candidate.status, "no_candidate")
        self.assertEqual(unknown.date_status, "unknown")
        self.assertEqual(outdated.date_status, "outdated")


if __name__ == "__main__":
    unittest.main()
