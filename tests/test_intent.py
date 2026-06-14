"""Tests for Intent Agent deterministic request normalization."""

from __future__ import annotations

import unittest

from lovv_agent.agents.intent import (
    map_theme_ids,
    normalize_recommendation_request,
    resolve_execution_mode,
)
from lovv_agent.models.schemas import SchemaValidationError


def _base_request() -> dict[str, object]:
    """Return a valid MVP recommendation request sample."""

    return {
        "entryType": "chat",
        "destinationId": None,
        "country": "KR",
        "travelYear": 2026,
        "travelMonth": 10,
        "tripType": "2d1n",
        "themes": ["sea_coast", "food_local"],
        "includeFestivals": False,
        "naturalLanguageQuery": "일본 말고 조용한 바다도 보고 싶어요",
        "userLocation": {
            "latitude": 37.5665,
            "longitude": 126.978,
        },
    }


class IntentNormalizationTest(unittest.TestCase):
    """Validate Task 2.1 structured input and theme mapping behavior."""

    def test_normalization_preserves_api_core_fields(self) -> None:
        result = normalize_recommendation_request(_base_request())

        self.assertFalse(result.needs_clarification)
        self.assertIsNone(result.clarifying_question)
        self.assertIsNotNone(result.candidate_evidence_input)

        candidate_input = result.candidate_evidence_input
        assert candidate_input is not None
        self.assertEqual(candidate_input.country, "KR")
        self.assertEqual(candidate_input.travel_year, 2026)
        self.assertEqual(candidate_input.travel_month, 10)
        self.assertEqual(candidate_input.trip_type, "2d1n")
        self.assertIsNone(candidate_input.destination_id)
        self.assertFalse(candidate_input.include_festivals)
        self.assertEqual(candidate_input.cleaned_raw_query, "")
        self.assertEqual(candidate_input.soft_preference_query, "")
        self.assertEqual(candidate_input.unsupported_conditions, ())
        self.assertEqual(candidate_input.user_location.latitude, 37.5665)

    def test_theme_mapping_splits_searchable_and_external_link_labels(self) -> None:
        result = normalize_recommendation_request(_base_request())

        self.assertEqual(result.active_required_themes, ("바다·해안", "미식·노포"))
        self.assertEqual(result.searchable_place_themes, ("바다·해안",))
        self.assertEqual(result.external_link_themes, ("미식·노포",))
        self.assertEqual(
            result.candidate_evidence_input.active_required_themes,
            ("바다·해안", "미식·노포"),
        )

    def test_include_festivals_controls_mode_not_theme_labels(self) -> None:
        request = _base_request()
        request["themes"] = ["history_tradition"]
        request["includeFestivals"] = True

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.active_required_themes, ("역사·전통",))
        self.assertEqual(result.fulfilled_matrix["festival"], "X")
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "festival_seeded_city_discovery",
        )
        self.assertTrue(result.candidate_evidence_input.include_festivals)

    def test_destination_id_sets_anchored_mode_and_preserves_festival_choice(self) -> None:
        request = _base_request()
        request["entryType"] = "map_marker"
        request["destinationId"] = "city-123"
        request["includeFestivals"] = True

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "anchored_place_search",
        )
        self.assertEqual(result.candidate_evidence_input.fixed_city_id, "city-123")
        self.assertTrue(result.candidate_evidence_input.include_festivals)

    def test_user_location_accepts_snake_case_boundary_input(self) -> None:
        request = _base_request()
        request.pop("userLocation")
        request["user_location"] = {
            "latitude": 35.1796,
            "longitude": 129.0756,
        }

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.candidate_evidence_input.user_location.latitude, 35.1796)
        self.assertEqual(
            result.extracted_inputs["user_location"],
            {"latitude": 35.1796, "longitude": 129.0756},
        )

    def test_legacy_festival_theme_is_not_an_active_required_theme(self) -> None:
        request = _base_request()
        request["themes"] = ["festival_event", "sea_coast"]
        request["includeFestivals"] = False

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertTrue(result.candidate_evidence_input.include_festivals)
        self.assertEqual(result.active_required_themes, ("바다·해안",))
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "festival_seeded_city_discovery",
        )
        self.assertIn("legacy festival theme", result.handoff_notes[0])

    def test_legacy_festival_theme_alone_requires_travel_theme(self) -> None:
        request = _base_request()
        request["themes"] = ["festival_event"]

        result = normalize_recommendation_request(request)

        self.assertTrue(result.needs_clarification)
        self.assertIsNone(result.candidate_evidence_input)
        self.assertIn("at least one canonical travel theme", result.clarifying_question)

    def test_map_marker_without_destination_needs_clarification(self) -> None:
        request = _base_request()
        request["entryType"] = "map_marker"
        request["destinationId"] = None

        result = normalize_recommendation_request(request)

        self.assertTrue(result.needs_clarification)
        self.assertIn("destinationId is required", result.clarifying_question)

    def test_unknown_theme_needs_clarification(self) -> None:
        request = _base_request()
        request["themes"] = ["sea_coast", "unknown_theme"]

        result = normalize_recommendation_request(request)

        self.assertTrue(result.needs_clarification)
        self.assertIn("unsupported canonical theme", result.clarifying_question)

    def test_theme_mapping_rejects_non_boolean_festival_flag(self) -> None:
        with self.assertRaises(SchemaValidationError):
            map_theme_ids(["sea_coast"], include_festivals="false")

    def test_execution_mode_resolution(self) -> None:
        self.assertEqual(resolve_execution_mode(None, False), "city_discovery")
        self.assertEqual(
            resolve_execution_mode(None, True),
            "festival_seeded_city_discovery",
        )
        self.assertEqual(
            resolve_execution_mode("city-1", False),
            "anchored_place_search",
        )


if __name__ == "__main__":
    unittest.main()
