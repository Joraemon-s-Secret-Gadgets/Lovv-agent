"""Tests for Planner Agent behavior."""

from __future__ import annotations

import unittest

from lovv_agent.agents.planner import PlannerAgent, TRIP_SLOT_TEMPLATES
from lovv_agent.models.schemas import CandidateEvidencePackage, FestivalVerification, SelectedCity
from lovv_agent.tools.validation import validate_planner_output


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


def festival_package(*, mode: str = "festival_seeded_city_discovery") -> CandidateEvidencePackage:
    """Build a Candidate Evidence package with a selected festival candidate."""

    return CandidateEvidencePackage(
        status="ok",
        mode=mode,
        selected_city=SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=tuple(place(f"P-{index}") for index in range(4)),
        selected_festival_candidates=(
            {
                "festival_id": "F-A",
                "name": "에이 축제",
                "city_id": "KR-A",
                "city_name": "에이군",
                "month": 10,
            },
        ),
    )


def gourmet_package() -> CandidateEvidencePackage:
    """Build a package whose gourmet theme must become an external link."""

    return CandidateEvidencePackage(
        status="ok",
        mode="city_discovery",
        selected_city=SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=tuple(place(f"P-{index}") for index in range(4)),
        coverage_audit={"external_link_themes": ["미식·노포"]},
    )


def festival_verification(
    *,
    festival_id: str = "F-A",
    date_status: str = "confirmed",
    applicable: bool = True,
    planner_policy: str = "placeable",
) -> FestivalVerification:
    """Return one Festival Verifier output for Planner tests."""

    return FestivalVerification(
        festival_id=festival_id,
        name="에이 축제",
        date_status=date_status,
        start_date="2026-10-10",
        end_date="2026-10-12",
        is_applicable_to_trip=applicable,
        planner_policy=planner_policy,
        source_type="dynamodb_detail",
        confidence=0.8,
        evidence_summary="verified",
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


class PlannerFestivalOverlayTest(unittest.TestCase):
    """Validate Task 8.2 festival overlay policy."""

    def test_festival_overlay_places_only_confirmed_applicable_festival(self) -> None:
        output = PlannerAgent().plan(
            festival_package(),
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(festival_verification(),),
        )

        festival_items = [
            item for item in output.itinerary if item["item_type"] == "festival"
        ]
        self.assertEqual(len(festival_items), 1)
        self.assertEqual(festival_items[0]["festivalId"], "F-A")
        self.assertEqual(festival_items[0]["source"], "festival_verifier")
        self.assertEqual(output.validation_result["festival_placed_count"], 1)

    def test_festival_overlay_skips_unconfirmed_or_inapplicable_festivals(self) -> None:
        output = PlannerAgent().plan(
            festival_package(),
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(
                festival_verification(date_status="tentative", planner_policy="not_placeable"),
                festival_verification(date_status="unknown", planner_policy="not_placeable"),
                festival_verification(date_status="outdated", planner_policy="not_placeable"),
                festival_verification(applicable=False, planner_policy="not_placeable"),
            ),
        )

        self.assertFalse(any(item["item_type"] == "festival" for item in output.itinerary))
        self.assertEqual(output.validation_result["festival_placed_count"], 0)
        self.assertEqual(output.validation_result["festival_skipped_count"], 4)
        self.assertTrue(output.user_notice)

    def test_festival_overlay_requires_selected_city_provenance(self) -> None:
        output = PlannerAgent().plan(
            festival_package(),
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(festival_verification(festival_id="F-B"),),
        )

        self.assertFalse(any(item["item_type"] == "festival" for item in output.itinerary))
        self.assertEqual(output.validation_result["festival_placed_count"], 0)

    def test_anchored_mode_keeps_anchored_city(self) -> None:
        output = PlannerAgent().plan(
            festival_package(mode="anchored_place_search"),
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(festival_verification(),),
        )

        attraction_cities = {
            item["city_id"]
            for item in output.itinerary
            if item["item_type"] == "attraction"
        }
        self.assertEqual(attraction_cities, {"KR-A"})
        self.assertTrue(any(item["item_type"] == "festival" for item in output.itinerary))


class PlannerGourmetPolicyTest(unittest.TestCase):
    """Validate Task 8.3 gourmet link and placeholder policy."""

    def test_gourmet_theme_adds_food_search_link_and_placeholder(self) -> None:
        output = PlannerAgent().plan(gourmet_package(), trip_type="daytrip")

        self.assertIn("foodSearch", output.external_links)
        self.assertEqual(output.external_links["foodSearch"]["type"], "foodSearch")
        self.assertEqual(output.external_links["foodSearch"]["query"], "에이군 맛집")
        self.assertEqual(
            output.validation_result["food_search_link_required"],
            True,
        )

        placeholders = [
            item for item in output.itinerary if item["item_type"] == "meal_placeholder"
        ]
        self.assertEqual(len(placeholders), 1)
        self.assertIsNone(placeholders[0]["placeId"])
        self.assertEqual(placeholders[0]["source"], "placeholder")
        self.assertEqual(placeholders[0]["linkRef"], "foodSearch")

    def test_gourmet_theme_does_not_generate_named_restaurant_items(self) -> None:
        output = PlannerAgent().plan(gourmet_package(), trip_type="daytrip")

        restaurant_items = [
            item for item in output.itinerary if item["item_type"] == "restaurant"
        ]
        self.assertEqual(restaurant_items, [])
        self.assertFalse(
            any(
                item.get("placeId")
                for item in output.itinerary
                if item["item_type"] == "meal_placeholder"
            ),
        )

    def test_non_gourmet_package_does_not_add_food_placeholder(self) -> None:
        output = PlannerAgent().plan(evidence_package(), trip_type="daytrip")

        self.assertNotIn("foodSearch", output.external_links)
        self.assertFalse(
            any(item["item_type"] == "meal_placeholder" for item in output.itinerary),
        )


class PlannerValidationTest(unittest.TestCase):
    """Validate Task 8.4 minimal Planner validation helper."""

    def test_validation_passes_grounded_planner_output(self) -> None:
        output = PlannerAgent().plan(evidence_package(), trip_type="daytrip")

        self.assertEqual(output.validation_result["status"], "valid")
        self.assertTrue(output.validation_result["is_valid"])
        self.assertEqual(output.validation_result["errors"], ())

    def test_validation_rejects_ungrounded_attraction(self) -> None:
        result = validate_planner_output(
            (
                {
                    "item_type": "attraction",
                    "placeId": "UNKNOWN",
                    "title": "근거 없는 장소",
                },
            ),
            package=evidence_package(),
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"][0]["code"], "ungrounded_attraction")
        self.assertEqual(result["retry_action"], "remove_or_rewrite_offending_items")

    def test_validation_rejects_named_restaurant_from_model_knowledge(self) -> None:
        result = validate_planner_output(
            (
                {
                    "item_type": "restaurant",
                    "placeId": "restaurant#model",
                    "title": "모델이 만든 식당명",
                    "source": "model_knowledge",
                },
            ),
            package=evidence_package(),
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"][0]["code"], "named_restaurant_not_allowed")

    def test_validation_rejects_unconfirmed_festival_placement(self) -> None:
        result = validate_planner_output(
            (
                {
                    "item_type": "festival",
                    "festivalId": "F-A",
                    "title": "에이 축제",
                    "source": "festival_verifier",
                },
            ),
            package=festival_package(),
            festival_verifications=(
                festival_verification(date_status="tentative", planner_policy="not_placeable"),
            ),
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"][0]["code"], "unconfirmed_festival")


if __name__ == "__main__":
    unittest.main()
