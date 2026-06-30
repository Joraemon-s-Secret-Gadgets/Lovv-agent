"""Unit tests for city_select node."""

from __future__ import annotations

import unittest

from lovv_agent_v2.models.schemas import CitySelectionResult, SelectedCity


class CitySelectionResultSchemaTest(unittest.TestCase):
    def test_city_selection_result_accepts_v2_15_planner_contract(self) -> None:
        result = CitySelectionResult(
            selected_city=SelectedCity(
                city_id="KR-47-ANDONG",
                city_name_ko="안동시",
                country="KR",
                ddb_pk="CITY#ANDONG",
                province="경상북도",
            ),
            alternative_city={
                "ddb_pk": "CITY#YEONGJU",
                "city_name_ko": "영주시",
                "score_delta": 0.042,
            },
            selection_reason_code=("theme_match", "small_city_lean"),
            representative_seed={
                "place_id": "PLACE#1",
                "ddb_sk": "DETAIL#1",
                "title": "대표 장소",
                "theme": "history_tradition",
                "sim": 0.74,
                "lat": 36.5,
                "lon": 128.7,
                "subtype": "유적지",
            },
            seeds=(
                {
                    "theme": "history_tradition",
                    "place_id": "PLACE#1",
                    "ddb_sk": "DETAIL#1",
                    "title": "대표 장소",
                    "sim": 0.74,
                    "lat": 36.5,
                    "lon": 128.7,
                    "subtype": "유적지",
                    "must_include": True,
                },
            ),
            headline_seed="PLACE#1",
            theme_evidence=(
                {
                    "theme": "history_tradition",
                    "best_place": {
                        "place_id": "PLACE#1",
                        "title": "대표 장소",
                        "sim": 0.74,
                    },
                    "coverage_strength": 0.74,
                },
            ),
            missing_themes=(),
            passthrough={
                "active_themes": ["history_tradition"],
                "theme_weights": {"history_tradition": 1.0},
                "trip_duration": "2d1n",
                "congestion_pref": "neutral",
                "transport_pref": "unknown",
                "soft_query": "고즈넉한",
                "user_location": None,
                "session_avoid": [],
            },
            score_breakdown={"weighted_theme_coverage": 0.74},
            retrieval_audit={"survived_city_count": 2},
        )

        payload = result.to_dict()

        self.assertEqual(payload["selected_city"]["ddb_pk"], "CITY#ANDONG")
        self.assertEqual(payload["alternative_city"]["ddb_pk"], "CITY#YEONGJU")
        self.assertEqual(payload["selection_reason_code"], ("theme_match", "small_city_lean"))
        self.assertTrue(payload["seeds"][0]["must_include"])
        self.assertEqual(payload["headline_seed"], "PLACE#1")
        self.assertEqual(payload["theme_evidence"][0]["best_place"]["sim"], 0.74)
        self.assertEqual(payload["passthrough"]["soft_query"], "고즈넉한")


if __name__ == "__main__":
    unittest.main()
