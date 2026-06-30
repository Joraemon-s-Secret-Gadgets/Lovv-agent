"""Profile Agent — theme weight calculation from stored user preferences.

The Profile Agent is a read-side agent that converts stored long-term
preferences (saved trip theme counts) into per-theme weights for the current
recommendation request. It does not use LLM calls — pure deterministic
computation only.

Responsibility:
- Read profile record (saved_trip_count + saved_theme_counts)
- Compute effective_theme_weights for active_required_themes
- Inject weights into city_select_input.theme_weights

Out of scope:
- raw query reinterpretation
- active_required_themes modification
- festival lookup
- city ranking
- itinerary generation
- profile write (handled by separate event-driven writer)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants (V2_24 §4.3)
# ---------------------------------------------------------------------------

PROFILE_ACTIVATION_SAVED_TRIP_COUNT: int = 3
"""Minimum saved trips before profile becomes active."""

PROFILE_ALPHA: float = 1.5
"""Amplification factor for observed ratio deviation from uniform."""

PROFILE_MIN_WEIGHT: float = 0.8
"""Lower clamp for learned weight."""

PROFILE_MAX_WEIGHT: float = 1.3
"""Upper clamp for learned weight."""

PROFILE_SCORE_CAP: float = 0.05
"""Downstream scoring-side cap (not used in weight calculation itself)."""

SUPPORTED_THEME_COUNT: int = 5
"""Number of supported themes. Used to derive uniform baseline ratio."""

# ---------------------------------------------------------------------------
# Theme ID → Label mapping (V2_24 §4.4)
# ---------------------------------------------------------------------------

THEME_ID_TO_LABEL: dict[str, str] = {
    "sea_coast": "바다·해안",
    "nature_trekking": "자연·트레킹",
    "history_tradition": "역사·전통",
    "art_sense": "예술·감성",
    "healing_rest": "온천·휴양",
}

THEME_LABEL_TO_ID: dict[str, str] = {v: k for k, v in THEME_ID_TO_LABEL.items()}

# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    """Stored user profile from DynamoDB LovvUserProfile table.

    Matches V2_24 §4.2 ProfileRecord / LovvUserProfile contract.
    """

    saved_trip_count: int
    saved_theme_counts: dict[str, int]

    def __post_init__(self) -> None:
        if not isinstance(self.saved_trip_count, int) or self.saved_trip_count < 0:
            raise ValueError("saved_trip_count must be a non-negative integer")
        if not isinstance(self.saved_theme_counts, dict):
            raise ValueError("saved_theme_counts must be a dict")


@dataclass(frozen=True, slots=True)
class ProfileResult:
    """Output of Profile Agent theme weight computation."""

    profile_active: bool
    effective_theme_weights: dict[str, float] | None
    audit: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core computation (V2_24 §4.4)
# ---------------------------------------------------------------------------


def compute_theme_weights(
    profile: ProfileRecord,
    active_required_themes: tuple[str, ...],
) -> ProfileResult:
    """Compute effective theme weights from stored profile.

    Implements the canonical formula from V2_24 §4.4:
    - If saved_trip_count < PROFILE_ACTIVATION_SAVED_TRIP_COUNT → inactive
    - Otherwise compute observed_ratio → raw_weight → learned_weight → effective_weight
    - Only themes present in active_required_themes are included in output

    The function is pure (no IO) and fully unit-testable.
    """

    if profile.saved_trip_count < PROFILE_ACTIVATION_SAVED_TRIP_COUNT:
        return ProfileResult(
            profile_active=False,
            effective_theme_weights=None,
            audit={
                "reason": "below_activation_threshold",
                "saved_trip_count": profile.saved_trip_count,
                "threshold": PROFILE_ACTIVATION_SAVED_TRIP_COUNT,
            },
        )

    # Uniform baseline: 1 / supported_theme_count (not hardcoded 0.2)
    uniform_ratio = 1.0 / SUPPORTED_THEME_COUNT

    total_theme_count = sum(profile.saved_theme_counts.values())

    # Confidence ramp (capped at 1.0)
    confidence = min(
        profile.saved_trip_count / PROFILE_ACTIVATION_SAVED_TRIP_COUNT,
        1.0,
    )

    # Compute per-theme weights for ALL supported themes
    all_weights: dict[str, float] = {}
    audit_details: dict[str, Any] = {}

    for theme_id, label in THEME_ID_TO_LABEL.items():
        theme_count = profile.saved_theme_counts.get(theme_id, 0)

        if total_theme_count > 0:
            observed_ratio = theme_count / total_theme_count
        else:
            observed_ratio = uniform_ratio

        raw_weight = 1.0 + PROFILE_ALPHA * (observed_ratio - uniform_ratio)
        learned_weight = max(PROFILE_MIN_WEIGHT, min(raw_weight, PROFILE_MAX_WEIGHT))
        effective_weight = round(1.0 + confidence * (learned_weight - 1.0), 6)

        all_weights[label] = effective_weight
        audit_details[theme_id] = {
            "label": label,
            "theme_count": theme_count,
            "observed_ratio": round(observed_ratio, 6),
            "raw_weight": round(raw_weight, 6),
            "learned_weight": round(learned_weight, 6),
            "effective_weight": effective_weight,
        }

    # Filter to only active_required_themes
    filtered_weights: dict[str, float] = {
        label: weight
        for label, weight in all_weights.items()
        if label in active_required_themes
    }

    return ProfileResult(
        profile_active=True,
        effective_theme_weights=filtered_weights if filtered_weights else None,
        audit={
            "saved_trip_count": profile.saved_trip_count,
            "total_theme_count": total_theme_count,
            "confidence": confidence,
            "uniform_ratio": uniform_ratio,
            "active_required_themes": list(active_required_themes),
            "all_computed_weights": {k: v for k, v in all_weights.items()},
            "filtered_weights": filtered_weights,
            "details": audit_details,
            "profile_score_cap": PROFILE_SCORE_CAP,
        },
    )


__all__ = [
    "PROFILE_ACTIVATION_SAVED_TRIP_COUNT",
    "PROFILE_ALPHA",
    "PROFILE_MAX_WEIGHT",
    "PROFILE_MIN_WEIGHT",
    "PROFILE_SCORE_CAP",
    "SUPPORTED_THEME_COUNT",
    "THEME_ID_TO_LABEL",
    "THEME_LABEL_TO_ID",
    "ProfileRecord",
    "ProfileResult",
    "compute_theme_weights",
]
