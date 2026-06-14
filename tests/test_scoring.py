"""Tests for deterministic ScoringTool behavior."""

from __future__ import annotations

import unittest

from lovv_agent.tools.scoring import (
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
    soft_distance: float | None = None,
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
    if soft_distance is not None:
        candidate["soft_distance"] = soft_distance
    return candidate


class PlaceScoringTest(unittest.TestCase):
    """Validate per-attraction score components."""

    def test_score_place_combines_similarity_theme_quality_and_distance(self) -> None:
        result = score_place(
            attraction(
                "P-1",
                distance=0.2,
                soft_distance=0.3,
                themes=["바다·해안", "자연"],
            ),
            ["바다·해안"],
            reference_location={"latitude": 37.0, "longitude": 127.0},
        )

        self.assertTrue(result.scored)
        self.assertEqual(result.place_score, 1.9)
        self.assertEqual(
            result.score_components,
            {
                "raw_similarity": 0.8,
                "soft_similarity": 0.7,
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

    def test_haversine_distance_returns_kilometers(self) -> None:
        distance = haversine_distance(37.5665, 126.9780, 35.1796, 129.0756)

        self.assertGreater(distance, 320.0)
        self.assertLess(distance, 330.0)


class CityScoringTest(unittest.TestCase):
    """Validate city-level scoring and required breakdown fields."""

    def test_score_city_uses_top_budget_and_breakdown_components(self) -> None:
        scored_places = [
            score_place(
                attraction(
                    "P-1",
                    distance=0.1,
                    soft_distance=0.2,
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
            user_location={"latitude": 37.0, "longitude": 127.0},
            primary_budget=CANDIDATE_SUFFICIENCY_THRESHOLD,
            congestion_index=0.25,
            w_cong=0.5,
        )

        self.assertEqual(result.candidate_count, 6)
        self.assertEqual(len(result.top_place_ids), 5)
        self.assertNotIn("P-5", result.top_place_ids)
        self.assertGreater(result.city_score, 0.0)
        self.assertEqual(result.breakdown.theme_coverage, 1.0)
        self.assertGreater(result.breakdown.theme_balance, 0.0)
        self.assertEqual(result.breakdown.candidate_sufficiency, 0.1)
        self.assertEqual(result.breakdown.congestion_penalty, 0.125)

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
                "semantic_evidence": 0.0,
                "theme_coverage": 0.0,
                "theme_balance": 0.0,
                "scale_correction": 0.0,
                "candidate_sufficiency": 0.0,
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
