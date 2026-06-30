"""Unit tests for Profile Agent theme weight computation.

Tests validate V2_24 §4.4 formula including:
- Activation threshold (saved_trip_count < 3 → inactive)
- Confidence ramp
- Max/min clamp
- Active theme filtering
- Edge cases (zero counts, single theme, uniform distribution)
"""

from __future__ import annotations

import unittest

from lovv_agent.agents.profile import (
    PROFILE_ACTIVATION_SAVED_TRIP_COUNT,
    PROFILE_MAX_WEIGHT,
    PROFILE_MIN_WEIGHT,
    ProfileRecord,
    ProfileResult,
    compute_theme_weights,
)


class TestProfileActivation(unittest.TestCase):
    """Test activation threshold behavior."""

    def test_inactive_when_zero_trips(self) -> None:
        profile = ProfileRecord(saved_trip_count=0, saved_theme_counts={})
        result = compute_theme_weights(profile, ("바다·해안",))

        self.assertFalse(result.profile_active)
        self.assertIsNone(result.effective_theme_weights)
        self.assertEqual(result.audit["reason"], "below_activation_threshold")

    def test_inactive_when_one_trip(self) -> None:
        profile = ProfileRecord(
            saved_trip_count=1,
            saved_theme_counts={"sea_coast": 1},
        )
        result = compute_theme_weights(profile, ("바다·해안",))

        self.assertFalse(result.profile_active)
        self.assertIsNone(result.effective_theme_weights)

    def test_inactive_at_boundary_two_trips(self) -> None:
        profile = ProfileRecord(
            saved_trip_count=2,
            saved_theme_counts={"sea_coast": 2},
        )
        result = compute_theme_weights(profile, ("바다·해안",))

        self.assertFalse(result.profile_active)
        self.assertIsNone(result.effective_theme_weights)

    def test_active_at_threshold(self) -> None:
        profile = ProfileRecord(
            saved_trip_count=3,
            saved_theme_counts={"sea_coast": 3},
        )
        result = compute_theme_weights(profile, ("바다·해안",))

        self.assertTrue(result.profile_active)
        self.assertIsNotNone(result.effective_theme_weights)


class TestWeightCalculation(unittest.TestCase):
    """Test the weight computation formula."""

    def test_single_theme_max_clamp(self) -> None:
        """All trips in one theme → weight should be clamped at max."""
        profile = ProfileRecord(
            saved_trip_count=5,
            saved_theme_counts={"sea_coast": 5},
        )
        result = compute_theme_weights(profile, ("바다·해안",))

        self.assertTrue(result.profile_active)
        assert result.effective_theme_weights is not None
        weight = result.effective_theme_weights["바다·해안"]
        self.assertAlmostEqual(weight, PROFILE_MAX_WEIGHT, places=5)

    def test_uniform_distribution_weight_near_one(self) -> None:
        """Equal distribution across all themes → weight ≈ 1.0."""
        profile = ProfileRecord(
            saved_trip_count=5,
            saved_theme_counts={
                "sea_coast": 2,
                "nature_trekking": 2,
                "history_tradition": 2,
                "art_sense": 2,
                "healing_rest": 2,
            },
        )
        result = compute_theme_weights(profile, ("바다·해안", "자연·트레킹"))

        self.assertTrue(result.profile_active)
        assert result.effective_theme_weights is not None
        for label, weight in result.effective_theme_weights.items():
            self.assertAlmostEqual(weight, 1.0, places=5)

    def test_min_clamp_for_unused_theme(self) -> None:
        """Theme with 0 count should be clamped at min weight."""
        profile = ProfileRecord(
            saved_trip_count=5,
            saved_theme_counts={
                "sea_coast": 5,
                "nature_trekking": 0,
                "history_tradition": 0,
                "art_sense": 0,
                "healing_rest": 0,
            },
        )
        result = compute_theme_weights(profile, ("자연·트레킹",))

        self.assertTrue(result.profile_active)
        assert result.effective_theme_weights is not None
        weight = result.effective_theme_weights["자연·트레킹"]
        self.assertAlmostEqual(weight, PROFILE_MIN_WEIGHT, places=5)

    def test_confidence_ramp_at_threshold(self) -> None:
        """At exactly 3 trips, confidence = 1.0 (3/3)."""
        profile = ProfileRecord(
            saved_trip_count=3,
            saved_theme_counts={"sea_coast": 3},
        )
        result = compute_theme_weights(profile, ("바다·해안",))

        self.assertTrue(result.profile_active)
        self.assertEqual(result.audit["confidence"], 1.0)

    def test_confidence_capped_above_threshold(self) -> None:
        """Above threshold, confidence is capped at 1.0."""
        profile = ProfileRecord(
            saved_trip_count=10,
            saved_theme_counts={"sea_coast": 10},
        )
        result = compute_theme_weights(profile, ("바다·해안",))

        self.assertEqual(result.audit["confidence"], 1.0)


class TestActiveThemeFiltering(unittest.TestCase):
    """Test that only active_required_themes are included in output."""

    def test_only_active_themes_in_output(self) -> None:
        profile = ProfileRecord(
            saved_trip_count=5,
            saved_theme_counts={
                "sea_coast": 5,
                "nature_trekking": 3,
                "history_tradition": 1,
                "art_sense": 0,
                "healing_rest": 0,
            },
        )
        result = compute_theme_weights(profile, ("바다·해안", "역사·전통"))

        assert result.effective_theme_weights is not None
        self.assertIn("바다·해안", result.effective_theme_weights)
        self.assertIn("역사·전통", result.effective_theme_weights)
        self.assertNotIn("자연·트레킹", result.effective_theme_weights)
        self.assertNotIn("예술·감성", result.effective_theme_weights)
        self.assertNotIn("온천·휴양", result.effective_theme_weights)

    def test_no_active_themes_returns_none(self) -> None:
        """If active themes list is empty or no match → weights = None."""
        profile = ProfileRecord(
            saved_trip_count=5,
            saved_theme_counts={"sea_coast": 5},
        )
        result = compute_theme_weights(profile, ())

        self.assertTrue(result.profile_active)
        self.assertIsNone(result.effective_theme_weights)

    def test_unknown_active_theme_not_in_output(self) -> None:
        """Active theme that isn't in supported themes → not in weights."""
        profile = ProfileRecord(
            saved_trip_count=5,
            saved_theme_counts={"sea_coast": 5},
        )
        result = compute_theme_weights(profile, ("알 수 없는 테마",))

        self.assertTrue(result.profile_active)
        self.assertIsNone(result.effective_theme_weights)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases for robustness."""

    def test_zero_total_theme_count_uses_uniform(self) -> None:
        """When total_theme_count=0, observed_ratio defaults to uniform."""
        profile = ProfileRecord(
            saved_trip_count=3,
            saved_theme_counts={},
        )
        result = compute_theme_weights(profile, ("바다·해안",))

        self.assertTrue(result.profile_active)
        assert result.effective_theme_weights is not None
        # uniform ratio = 0.2, raw_weight = 1.0 + 1.5*(0.2-0.2) = 1.0
        self.assertAlmostEqual(
            result.effective_theme_weights["바다·해안"], 1.0, places=5,
        )

    def test_profile_record_validation(self) -> None:
        """ProfileRecord rejects invalid inputs."""
        with self.assertRaises(ValueError):
            ProfileRecord(saved_trip_count=-1, saved_theme_counts={})

    def test_weight_precision_six_decimals(self) -> None:
        """Weights are rounded to 6 decimal places."""
        profile = ProfileRecord(
            saved_trip_count=3,
            saved_theme_counts={"sea_coast": 1, "nature_trekking": 2},
        )
        result = compute_theme_weights(profile, ("바다·해안",))

        assert result.effective_theme_weights is not None
        weight = result.effective_theme_weights["바다·해안"]
        # Should be round(..., 6)
        decimal_str = str(weight).split(".")[-1] if "." in str(weight) else ""
        self.assertLessEqual(len(decimal_str), 6)

    def test_v2_24_example(self) -> None:
        """V2_24 spec example: sea_coast=3, saved_trip_count=3 → 바다·해안 = 1.3."""
        profile = ProfileRecord(
            saved_trip_count=3,
            saved_theme_counts={
                "sea_coast": 3,
                "nature_trekking": 0,
                "history_tradition": 0,
                "art_sense": 0,
                "healing_rest": 0,
            },
        )
        result = compute_theme_weights(profile, ("바다·해안", "역사·전통"))

        assert result.effective_theme_weights is not None
        self.assertAlmostEqual(
            result.effective_theme_weights["바다·해안"], 1.3, places=5,
        )


if __name__ == "__main__":
    unittest.main()
