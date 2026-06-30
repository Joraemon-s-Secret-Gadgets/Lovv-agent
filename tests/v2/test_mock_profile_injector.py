from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any
import unittest

from lovv_agent_v2.models.schemas import CitySelectInput


def _load_injector() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "mock_profile_injector.py"
    spec = importlib.util.spec_from_file_location("mock_profile_injector", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _intent_mock() -> dict[str, Any]:
    return {
        "intent_output": {
            "country": "KR",
            "travel_month": 9,
            "travel_year": 2026,
            "trip_type": "3d2n",
            "active_required_themes": ["바다·해안", "자연·트레킹"],
            "include_festivals": False,
            "cleaned_raw_query": "숲길과 바다를 함께 보고 싶어요.",
            "soft_preference_query": "",
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
            "destination_id": None,
            "user_location": None,
            "execution_mode": "city_discovery",
            "unsupported_conditions": [],
        },
    }


def _persona_doc(saved_trip_count: int) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "lookup_key": "actor_id",
        "records": [
            {
                "actor_id": "mock://profile/P_sea",
                "profile_id": "P_sea",
                "profile_status": "found",
                "lovv_user_profile": {
                    "saved_trip_count": saved_trip_count,
                    "saved_theme_counts": {
                        "sea_coast": saved_trip_count,
                        "nature_trekking": 0,
                        "history_tradition": 0,
                        "art_sense": 0,
                        "healing_rest": 0,
                    },
                },
            },
        ],
    }


class MockProfileInjectorTest(unittest.TestCase):
    def test_build_city_select_input_adds_active_profile_theme_weights(self) -> None:
        injector = _load_injector()

        payload = injector.build_city_select_input(
            _intent_mock(),
            _persona_doc(saved_trip_count=3),
            actor_id="P_sea",
        )

        self.assertEqual(
            payload["theme_weights"],
            {"바다·해안": 1.3, "자연·트레킹": 0.8},
        )
        self.assertTrue(payload["profile_mock"]["profile_active"])
        CitySelectInput.from_mapping(payload)

    def test_build_city_select_input_keeps_profile_off_before_activation(self) -> None:
        injector = _load_injector()

        payload = injector.build_city_select_input(
            _intent_mock(),
            _persona_doc(saved_trip_count=2),
            actor_id="mock://profile/P_sea",
        )

        self.assertNotIn("theme_weights", payload)
        self.assertFalse(payload["profile_mock"]["profile_active"])
        CitySelectInput.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
