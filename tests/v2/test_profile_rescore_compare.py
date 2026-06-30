from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
import unittest


def _load_compare() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "profile_rescore_compare.py"
    spec = importlib.util.spec_from_file_location("profile_rescore_compare", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProfileRescoreCompareTest(unittest.TestCase):
    def test_persona_weights_use_activation_gate(self) -> None:
        compare = _load_compare()

        cold = compare.persona_weights(
            {
                "saved_trip_count": 2,
                "saved_theme_counts": {
                    "sea_coast": 1,
                    "nature_trekking": 0,
                    "history_tradition": 0,
                    "art_sense": 0,
                    "healing_rest": 0,
                },
            },
            alpha=1.5,
            min_weight=0.8,
            max_weight=1.3,
            activation=3.0,
        )
        active = compare.persona_weights(
            {
                "saved_trip_count": 3,
                "saved_theme_counts": {
                    "sea_coast": 3,
                    "nature_trekking": 0,
                    "history_tradition": 0,
                    "art_sense": 0,
                    "healing_rest": 0,
                },
            },
            alpha=1.5,
            min_weight=0.8,
            max_weight=1.3,
            activation=3.0,
        )

        self.assertEqual(cold["sea_coast"], 1.0)
        self.assertEqual(cold["nature_trekking"], 1.0)
        self.assertEqual(active["sea_coast"], 1.3)
        self.assertEqual(active["nature_trekking"], 0.8)

    def test_active_weights_normalize_requested_theme_subset(self) -> None:
        compare = _load_compare()

        weights = compare.active_weights(
            ["바다·해안", "온천·휴양"],
            {"sea_coast": 1.3, "healing_rest": 0.8},
        )

        self.assertAlmostEqual(weights["바다·해안"], 1.3 / 2.1)
        self.assertAlmostEqual(weights["온천·휴양"], 0.8 / 2.1)


if __name__ == "__main__":
    unittest.main()
