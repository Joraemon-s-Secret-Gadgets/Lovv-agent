"""Tests for deterministic ScoringTool behavior."""

from __future__ import annotations

import unittest

from lovv_agent_v2.agents.city_select.scoring import (
    CANDIDATE_SUFFICIENCY_THRESHOLD,
    ScoringTool,
    haversine_distance,
    score_city,
    score_place,
)


def attraction(
    place_id: str,
    *,
    distance: float = 0.2,
    themes: list[str] | None = None,
    latitude: float = 37.0,
    longitude: float = 127.0,
    title: str = "Place",
) -> dict[str, object]:
    """Build a minimal attraction candidate mapping for scoring tests."""

    candidate: dict[str, object] = {
        "place_id": place_id,
        "entity_type": "attraction",
        "distance": distance,
        "title": title,
        "city_id": "city-1",
        "theme_tags": themes or ["바다·해안"],
        "latitude": latitude,
        "longitude": longitude,
    }
    return candidate


class PlaceScoringTest(unittest.TestCase):
    """Validate per-attraction score components."""

    def test_score_place_combines_similarity_theme_quality_and_distance(self) -> None:
        result = score_place(
            attraction(
                "P-1",
                distance=0.2,
                themes=["바다·해안", "자연"],
            ),
            ["바다·해안"],
            reference_location={"latitude": 37.0, "longitude": 127.0},
        )

        self.assertTrue(result.scored)
        self.assertEqual(result.place_score, 1.2)
        self.assertEqual(
            result.score_components,
            {
                "raw_similarity": 0.8,
                "base_similarity": 0.8,
                "theme_match_score": 0.2,
                "source_quality_score": 0.2,
                "local_distance_penalty": 0.0,
            },
        )

    def test_score_place_filters_external_and_festival_themes(self) -> None:
        result = score_place(
            attraction("P-1", themes=["바다·해안"]),
            ["미식·노포", "festival_event", "바다·해안"],
        )

        self.assertEqual(result.score_components["theme_match_score"], 0.2)

    def test_score_place_excludes_non_attraction_entities(self) -> None:
        for entity_type in ("restaurant", "festival"):
            with self.subTest(entity_type=entity_type):
                result = score_place(
                    {
                        "place_id": f"{entity_type}-1",
                        "entity_type": entity_type,
                        "distance": 0.1,
                        "title": "Excluded",
                        "theme_tags": ["바다·해안"],
                    },
                    ["바다·해안"],
                )

                self.assertFalse(result.scored)
                self.assertEqual(result.place_score, 0.0)
                self.assertEqual(
                    result.exclusion_reason,
                    f"unsupported_entity_type:{entity_type}",
                )

    def test_gourmet_only_theme_does_not_receive_theme_bonus(self) -> None:
        result = score_place(
            attraction("food-like", themes=["미식·노포"]),
            ["미식·노포"],
        )

        self.assertTrue(result.scored)
        self.assertEqual(result.score_components["theme_match_score"], 0.0)

    def test_festival_theme_label_does_not_receive_theme_bonus(self) -> None:
        result = score_place(
            attraction("festival-like", themes=["festival_event"]),
            ["festival_event"],
        )

        self.assertTrue(result.scored)
        self.assertEqual(result.score_components["theme_match_score"], 0.0)

    def test_haversine_distance_returns_kilometers(self) -> None:
        distance = haversine_distance(37.5665, 126.9780, 35.1796, 129.0756)

        self.assertGreater(distance, 320.0)
        self.assertLess(distance, 330.0)


class CityScoringTest(unittest.TestCase):
    """Validate city-level scoring and required breakdown fields."""

    def test_score_city_uses_weighted_best_similarity_minus_missing_penalty(self) -> None:
        scored_places = [
            score_place(
                attraction(
                    "P-1",
                    distance=0.1,
                    themes=["바다·해안"],
                    latitude=37.0,
                    longitude=127.0,
                ),
                ["바다·해안", "역사·문화"],
            ),
            score_place(
                attraction(
                    "P-2",
                    distance=0.15,
                    themes=["역사·문화"],
                    latitude=37.01,
                    longitude=127.01,
                ),
                ["바다·해안", "역사·문화"],
            ),
            score_place(
                attraction("P-3", distance=0.25, themes=["바다·해안"]),
                ["바다·해안", "역사·문화"],
            ),
            score_place(
                attraction("P-4", distance=0.3, themes=["역사·문화"]),
                ["바다·해안", "역사·문화"],
            ),
            score_place(
                attraction("P-5", distance=0.35, themes=["바다·해안"]),
                ["바다·해안", "역사·문화"],
            ),
            score_place(
                attraction("P-6", distance=0.05, themes=["바다·해안"], title="Extra"),
                ["바다·해안", "역사·문화"],
            ),
        ]

        result = score_city(
            city_id="city-1",
            places=scored_places,
            active_themes=["바다·해안", "역사·문화"],
            primary_budget=CANDIDATE_SUFFICIENCY_THRESHOLD,
            theme_weights={"바다·해안": 3.0, "역사·문화": 1.0},
        )

        self.assertEqual(result.candidate_count, 6)
        self.assertEqual(len(result.top_place_ids), 5)
        self.assertEqual(result.city_score, 0.925)
        self.assertEqual(result.breakdown.weighted_theme_coverage, 0.925)
        self.assertEqual(result.breakdown.weighted_missing_theme_penalty, 0.0)
        self.assertEqual(result.breakdown.distance_penalty, 0.0)
        self.assertEqual(result.breakdown.congestion_penalty, 0.0)

    def test_score_city_penalizes_missing_explicit_themes(self) -> None:
        result = score_city(
            city_id="city-1",
            places=[
                score_place(
                    attraction("P-1", distance=0.2, themes=["바다·해안"]),
                    ["바다·해안", "역사·문화"],
                ),
            ],
            active_themes=["바다·해안", "역사·문화"],
        )

        self.assertEqual(result.breakdown.weighted_theme_coverage, 0.4)
        self.assertEqual(result.breakdown.weighted_missing_theme_penalty, 0.5)
        self.assertEqual(result.city_score, -0.1)

    def test_score_city_scales_distance_penalty_by_trip_duration(self) -> None:
        scored_places = [
            score_place(
                attraction(
                    "P-1",
                    distance=0.2,
                    themes=["바다·해안"],
                    latitude=35.1796,
                    longitude=129.0756,
                ),
                ["바다·해안"],
            ),
        ]
        user_location = {"latitude": 37.5665, "longitude": 126.9780}

        daytrip = score_city(
            city_id="city-1",
            places=scored_places,
            active_themes=["바다·해안"],
            user_location=user_location,
            trip_type="daytrip",
        )
        overnight = score_city(
            city_id="city-1",
            places=scored_places,
            active_themes=["바다·해안"],
            user_location=user_location,
            trip_type="2d1n",
        )
        long_trip = score_city(
            city_id="city-1",
            places=scored_places,
            active_themes=["바다·해안"],
            user_location=user_location,
            trip_type="3d2n",
        )

        self.assertEqual(daytrip.breakdown.distance_penalty, 0.08)
        self.assertEqual(overnight.breakdown.distance_penalty, 0.04)
        self.assertEqual(long_trip.breakdown.distance_penalty, 0.0)

    def test_score_city_returns_zero_breakdown_for_empty_candidates(self) -> None:
        result = ScoringTool().score_city(
            city_id="city-empty",
            places=[],
            active_themes=["바다·해안"],
        )

        self.assertEqual(result.city_score, 0.0)
        self.assertEqual(result.top_place_ids, ())
        self.assertEqual(
            result.breakdown.to_dict(),
            {
                "weighted_theme_coverage": 0.0,
                "weighted_missing_theme_penalty": 0.0,
                "distance_penalty": 0.0,
                "congestion_penalty": 0.0,
            },
        )

    def test_score_city_rejects_unscored_inputs(self) -> None:
        with self.assertRaisesRegex(Exception, "place_score is required"):
            score_city(
                city_id="city-1",
                places=[attraction("P-1")],
                active_themes=["바다·해안"],
            )


if __name__ == "__main__":
    unittest.main()
