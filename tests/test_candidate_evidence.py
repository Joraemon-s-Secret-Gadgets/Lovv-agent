"""Tests for Candidate Evidence Agent orchestration.

The tests keep each Task 6 subtask focused. Task 6.1 covers deterministic entry
context preparation only: execution mode resolution and theme split behavior.
Retrieval, scoring, festival seeding, package building, and claim generation are
covered by later tests in this file.
"""

from __future__ import annotations

import unittest

from lovv_agent.agents.candidate_evidence import (
    ANCHORED_PLACE_SEARCH_MODE,
    CITY_DISCOVERY_MODE,
    FESTIVAL_SEEDED_CITY_DISCOVERY_MODE,
    CandidateEvidenceAgent,
    prepare_candidate_evidence_context,
    resolve_candidate_evidence_mode,
    split_candidate_themes,
)
from lovv_agent.models.schemas import CandidateEvidenceInput, SchemaValidationError


def candidate_input(
    *,
    destination_id: str | None = None,
    include_festivals: bool = False,
    themes: tuple[str, ...] = ("바다·해안", "미식·노포"),
) -> CandidateEvidenceInput:
    """Return a valid Candidate Evidence input for orchestration tests."""

    return CandidateEvidenceInput(
        country="KR",
        travel_month=10,
        travel_year=2026,
        trip_type="2d1n",
        active_required_themes=themes,
        include_festivals=include_festivals,
        cleaned_raw_query="조용한 바다 산책",
        soft_preference_query="조용한 분위기",
        destination_id=destination_id,
        fixed_city_id=destination_id,
    )


class CandidateEvidenceModeTest(unittest.TestCase):
    """Validate Candidate Evidence mode resolution before retrieval runs."""

    def test_mode_city_discovery_without_anchor_or_festival(self) -> None:
        result = resolve_candidate_evidence_mode(candidate_input())

        self.assertEqual(result, CITY_DISCOVERY_MODE)

    def test_mode_festival_seeded_city_discovery_without_anchor(self) -> None:
        result = resolve_candidate_evidence_mode(candidate_input(include_festivals=True))

        self.assertEqual(result, FESTIVAL_SEEDED_CITY_DISCOVERY_MODE)

    def test_mode_anchored_search_wins_when_destination_id_exists(self) -> None:
        result = resolve_candidate_evidence_mode(
            candidate_input(destination_id="KR-Gangneung"),
        )

        self.assertEqual(result, ANCHORED_PLACE_SEARCH_MODE)

    def test_mode_anchored_search_preserves_festival_choice(self) -> None:
        context = prepare_candidate_evidence_context(
            candidate_input(
                destination_id="KR-Gangneung",
                include_festivals=True,
            ),
        )

        self.assertEqual(context.mode, ANCHORED_PLACE_SEARCH_MODE)
        self.assertTrue(context.include_festivals)
        self.assertEqual(context.fixed_city_id, "KR-Gangneung")

    def test_prepare_context_accepts_mapping_input(self) -> None:
        context = CandidateEvidenceAgent().prepare_context(
            {
                "country": "KR",
                "travelMonth": 10,
                "travelYear": 2026,
                "tripType": "2d1n",
                "destinationId": None,
                "active_required_themes": ["자연·트레킹"],
                "cleaned_raw_query": "",
                "soft_preference_query": "",
                "unsupported_conditions": [],
                "user_location": None,
                "includeFestivals": False,
            },
        )

        self.assertEqual(context.mode, CITY_DISCOVERY_MODE)
        self.assertEqual(context.theme_split.searchable_place_themes, ("자연·트레킹",))


class CandidateEvidenceThemeSplitTest(unittest.TestCase):
    """Validate searchable and external-link theme routing."""

    def test_theme_split_places_gourmet_in_external_link_group(self) -> None:
        result = split_candidate_themes(("바다·해안", "미식·노포"))

        self.assertEqual(result.active_required_themes, ("바다·해안", "미식·노포"))
        self.assertEqual(result.searchable_place_themes, ("바다·해안",))
        self.assertEqual(result.external_link_themes, ("미식·노포",))

    def test_theme_split_deduplicates_without_reordering_unique_values(self) -> None:
        result = split_candidate_themes(("자연·트레킹", "미식·노포", "자연·트레킹"))

        self.assertEqual(result.active_required_themes, ("자연·트레킹", "미식·노포"))
        self.assertEqual(result.searchable_place_themes, ("자연·트레킹",))
        self.assertEqual(result.external_link_themes, ("미식·노포",))

    def test_theme_split_ignores_legacy_festival_markers(self) -> None:
        result = split_candidate_themes(("festival_event", "축제·이벤트", "역사·전통"))

        self.assertEqual(result.active_required_themes, ("역사·전통",))
        self.assertEqual(result.searchable_place_themes, ("역사·전통",))
        self.assertEqual(result.ignored_theme_markers, ("festival_event", "축제·이벤트"))

    def test_theme_split_rejects_blank_theme_labels(self) -> None:
        with self.assertRaises(SchemaValidationError):
            split_candidate_themes(("자연·트레킹", " "))

    def test_prepare_context_exposes_same_theme_split(self) -> None:
        context = prepare_candidate_evidence_context(
            candidate_input(themes=("온천·휴양", "미식·노포")),
        )

        self.assertEqual(context.theme_split.searchable_place_themes, ("온천·휴양",))
        self.assertEqual(context.theme_split.external_link_themes, ("미식·노포",))


if __name__ == "__main__":
    unittest.main()
