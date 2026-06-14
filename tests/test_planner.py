"""Tests for Planner Agent behavior."""

from __future__ import annotations

import unittest

from lovv_agent.agents.planner import PlannerAgent, TRIP_SLOT_TEMPLATES
from lovv_agent.models.schemas import CandidateEvidencePackage, SelectedCity


def place(place_id: str, *, title: str | None = None) -> dict[str, object]:
    """Return one lightweight Candidate Evidence place payload."""

    return {
        "place_id": place_id,
        "title": title or f"장소 {place_id}",
        "city_id": "KR-A",
        "city_name_ko": "에이군",
        "theme_tags": ["바다·해안"],
        "ddb_pk": f"CITY#KR-A",
        "ddb_sk": f"ATTRACTION#{place_id}",
    }


def evidence_package(
    *,
    status: str = "ok",
    recommended_count: int = 6,
    selected_city: SelectedCity | None = None,
    failure_signals: tuple[str, ...] = (),
) -> CandidateEvidencePackage:
    """Build a Candidate Evidence package for Planner tests."""

    return CandidateEvidencePackage(
        status=status,
        failure_signals=failure_signals,
        mode="city_discovery",
        selected_city=selected_city
        or SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=tuple(place(f"P-{index}") for index in range(recommended_count)),
        reserve_places=tuple(place(f"R-{index}") for index in range(2)),
        coverage_audit={"candidate_sufficiency": "sufficient"},
        candidate_counts={"recommended_places": recommended_count},
    )


class PlannerStatusAndSlotTest(unittest.TestCase):
    """Validate Task 8.1 Planner status gates and slot templates."""

    def test_ok_status_creates_itinerary_from_grounded_candidates(self) -> None:
        output = PlannerAgent().plan(evidence_package(), trip_type="daytrip")

        self.assertEqual(len(output.itinerary), len(TRIP_SLOT_TEMPLATES["daytrip"]))
        self.assertEqual(output.itinerary[0]["item_type"], "attraction")
        self.assertEqual(output.itinerary[0]["placeId"], "P-0")
        self.assertEqual(output.validation_result["planner_status_gate"], "ok")

    def test_insufficient_candidates_creates_reduced_itinerary_when_safe(self) -> None:
        output = PlannerAgent().plan(
            evidence_package(status="insufficient_candidates", recommended_count=2),
            trip_type="daytrip",
        )

        self.assertEqual(len(output.itinerary), 2)
        self.assertEqual(output.validation_result["planner_status_gate"], "insufficient_candidates")
        self.assertTrue(output.user_notice)
        self.assertLess(output.confidence, 0.72)

    def test_no_candidate_does_not_create_normal_itinerary(self) -> None:
        output = PlannerAgent().plan(
            CandidateEvidencePackage(
                status="no_candidate",
                failure_signals=("no_city_after_theme_gate",),
                mode="city_discovery",
            ),
            trip_type="daytrip",
        )

        self.assertEqual(output.itinerary, ())
        self.assertEqual(output.validation_result["status"], "blocked")
        self.assertEqual(output.confidence, 0.0)

    def test_error_does_not_create_normal_itinerary(self) -> None:
        output = PlannerAgent().plan(
            CandidateEvidencePackage(
                status="error",
                failure_signals=("s3_vector_failure",),
                mode="city_discovery",
            ),
            trip_type="2d1n",
        )

        self.assertEqual(output.itinerary, ())
        self.assertEqual(output.validation_result["planner_status_gate"], "error")

    def test_trip_type_slot_template_controls_slot_count(self) -> None:
        output = PlannerAgent().plan(
            evidence_package(recommended_count=10),
            trip_type="2d1n",
        )

        self.assertEqual(len(output.itinerary), len(TRIP_SLOT_TEMPLATES["2d1n"]))
        self.assertEqual(
            [(slot["day"], slot["slot"]) for slot in output.itinerary],
            list(TRIP_SLOT_TEMPLATES["2d1n"]),
        )


if __name__ == "__main__":
    unittest.main()
