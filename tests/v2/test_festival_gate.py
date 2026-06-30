from __future__ import annotations

import unittest

from lovv_agent_v2.agents.festival_verifier.verifier import build_festival_gate_result
from lovv_agent_v2.models.schemas import SchemaValidationError


def festival_candidate(
    festival_id: str,
    *,
    city_id: str = "KR-ANDONG",
    city_name: str = "안동시",
    ddb_pk: str | None = None,
    event_start_date: str | None = None,
    date_status: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "festival_id": festival_id,
        "name": f"축제 {festival_id}",
        "country": "KR",
        "city_id": city_id,
        "city_name": city_name,
        "month": 10,
        "theme_tags": ("festival",),
        "event_end_date": "2026-10-05",
        "source": "dynamodb",
    }
    if event_start_date is not None:
        payload["event_start_date"] = event_start_date
    if date_status is not None:
        payload["date_status"] = date_status
    if ddb_pk is not None:
        payload["ddb_pk"] = ddb_pk
    return payload


class FestivalGateResultTest(unittest.TestCase):
    def test_discovery_confirmed_candidates_limit_allowed_city_ids(self) -> None:
        # Given: discovery has one confirmed festival and one outdated festival.
        candidates = (
            festival_candidate("F-A", city_id="KR-A", ddb_pk="CITY#GIMHAE"),
            festival_candidate("F-OLD", city_id="KR-OLD", event_start_date="2025-10"),
        )

        # When: the festival gate is built.
        result = build_festival_gate_result(
            include_festivals=True,
            travel_month=10,
            target_year=2026,
            candidates=candidates,
        )

        # Then: only confirmed festival cities are allowed downstream.
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.tier, "confirmed")
        self.assertEqual(result.allowed_city_ids, ("KR-A",))
        self.assertEqual(result.verified_festival_cities[0]["ddb_pk"], "CITY#GIMHAE")
        self.assertIsNone(result.clarification)

    def test_discovery_tentative_only_returns_structured_clarification(self) -> None:
        # Given: discovery has only tentative festival candidates.
        candidates = (
            festival_candidate(
                "F-T",
                city_id="KR-T",
                city_name="통영시",
                date_status="tentative",
            ),
        )

        # When: the festival gate is built.
        result = build_festival_gate_result(
            include_festivals=True,
            travel_month=10,
            target_year=2026,
            candidates=candidates,
        )

        # Then: city_select must wait for the user instead of using tentative data.
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.tier, "tentative")
        self.assertEqual(result.allowed_city_ids, ())
        self.assertIsNotNone(result.clarification)
        assert result.clarification is not None
        self.assertEqual(result.clarification.reason_code, "festival_tentative")
        self.assertEqual(result.clarification.options[0].then, "anchor")
        self.assertEqual(result.clarification.options[0].apply.destination_id, "KR-T")
        self.assertTrue(result.clarification.options[0].apply.allow_tentative_festivals)
        self.assertTrue(result.clarification.options[0].apply.accepted_festival_risk)

    def test_anchored_city_without_confirmed_festival_returns_conflict(self) -> None:
        # Given: the requested city has only outdated festival data.
        candidates = (
            festival_candidate(
                "F-OLD",
                city_id="KR-A",
                event_start_date="2025-10",
            ),
        )

        # When: the gate runs in anchored mode.
        result = build_festival_gate_result(
            include_festivals=True,
            travel_month=10,
            target_year=2026,
            requested_destination_id="KR-A",
            candidates=candidates,
        )

        # Then: the response asks whether to continue without festival in anchor.
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.tier, "none")
        self.assertIsNotNone(result.clarification)
        assert result.clarification is not None
        self.assertEqual(result.clarification.reason_code, "anchor_festival_conflict")
        self.assertEqual(
            result.clarification.options[0].option_id,
            "continue_without_festival_in_anchor",
        )
        self.assertEqual(result.clarification.options[0].then, "anchor")
        self.assertFalse(result.clarification.options[0].apply.include_festivals)

    def test_outdated_unknown_and_skipped_are_not_automatic_candidates(self) -> None:
        # Given: every candidate is excluded by date status.
        candidates = (
            festival_candidate("F-OLD", event_start_date="2025-10"),
            festival_candidate("F-UNKNOWN", date_status="unknown"),
            festival_candidate("F-SKIP", date_status="skipped"),
        )

        # When: the gate evaluates discovery.
        result = build_festival_gate_result(
            include_festivals=True,
            travel_month=10,
            target_year=2026,
            candidates=candidates,
        )

        # Then: excluded statuses are treated as no usable festival candidates.
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.tier, "none")
        self.assertEqual(result.audit["candidate_counts"]["excluded"], 3)
        self.assertIsNotNone(result.clarification)
        assert result.clarification is not None
        self.assertEqual(result.clarification.reason_code, "festival_none")

    def test_matching_month_with_stale_year_is_excluded(self) -> None:
        candidates = (
            festival_candidate("F-STALE", event_start_date="2025-10-01"),
        )

        result = build_festival_gate_result(
            include_festivals=True,
            travel_month=10,
            target_year=2026,
            candidates=candidates,
        )

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.audit["candidate_counts"]["excluded"], 1)
        self.assertEqual(result.candidates, ())

    def test_invalid_date_status_is_rejected(self) -> None:
        with self.assertRaises(SchemaValidationError):
            build_festival_gate_result(
                include_festivals=True,
                travel_month=10,
                target_year=2026,
                candidates=(festival_candidate("F-BAD", date_status="maybe"),),
            )


if __name__ == "__main__":
    unittest.main()
