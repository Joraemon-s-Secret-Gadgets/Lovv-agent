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
from lovv_agent.tools.destination_search import AttractionCandidate, prune_cities


def candidate_input(
    *,
    destination_id: str | None = None,
    include_festivals: bool = False,
    trip_type: str = "daytrip",
    themes: tuple[str, ...] = ("바다·해안", "미식·노포"),
) -> CandidateEvidenceInput:
    """Return a valid Candidate Evidence input for orchestration tests."""

    return CandidateEvidenceInput(
        country="KR",
        travel_month=10,
        travel_year=2026,
        trip_type=trip_type,
        active_required_themes=themes,
        include_festivals=include_festivals,
        cleaned_raw_query="조용한 바다 산책",
        soft_preference_query="조용한 분위기",
        destination_id=destination_id,
        fixed_city_id=destination_id,
    )


def attraction(
    place_id: str,
    *,
    city_id: str = "KR-Sea",
    city_name_ko: str = "바다군",
    title: str | None = None,
    theme_tags: tuple[str, ...] = ("바다·해안",),
    distance: float = 0.1,
) -> AttractionCandidate:
    """Return one normalized attraction candidate for orchestration tests."""

    return AttractionCandidate(
        key=f"{place_id}#chunk#1",
        place_id=place_id,
        distance=distance,
        entity_type="attraction",
        city_id=city_id,
        city_name_ko=city_name_ko,
        title=title or place_id,
        theme_tags=theme_tags,
        latitude=37.0,
        longitude=128.0,
        ddb_pk=f"CITY#{city_id}",
        ddb_sk=f"ATTRACTION#{place_id}",
        metadata={
            "country": "KR",
            "city_id": city_id,
            "city_name_ko": city_name_ko,
            "place_id": place_id,
        },
    )


class FakeDestinationSearch:
    """Injected search tool that records calls and reuses real city pruning."""

    def __init__(self, candidates: tuple[AttractionCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls: list[dict[str, object]] = []

    def search_candidates(
        self,
        query_vector: tuple[float, ...],
        *,
        city_id: str | None = None,
        theme: str | None = None,
    ) -> tuple[AttractionCandidate, ...]:
        self.calls.append(
            {
                "query_vector": query_vector,
                "city_id": city_id,
                "theme": theme,
            },
        )
        return tuple(
            candidate
            for candidate in self.candidates
            if (theme is None or theme in candidate.theme_tags)
        )

    def prune_cities(
        self,
        candidates: tuple[AttractionCandidate, ...],
        searchable_place_themes: tuple[str, ...],
        *,
        allowed_city_ids: tuple[str, ...] | None = None,
    ):
        return prune_cities(
            candidates,
            searchable_place_themes,
            allowed_city_ids=allowed_city_ids,
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


class CandidateEvidenceOrchestrationTest(unittest.TestCase):
    """Validate non-festival Candidate Evidence package orchestration."""

    def test_city_discovery_retrieves_scores_selects_city_and_package_ok(self) -> None:
        candidates = tuple(
            attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군", distance=0.05)
            for index in range(6)
        ) + tuple(
            attraction(f"B-{index}", city_id="KR-B", city_name_ko="비군", distance=0.4)
            for index in range(6)
        )
        search = FakeDestinationSearch(candidates)
        agent = CandidateEvidenceAgent(destination_search=search)

        package = agent.run(
            candidate_input(themes=("바다·해안",), destination_id=None),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "ok")
        self.assertEqual(package.mode, CITY_DISCOVERY_MODE)
        self.assertIsNotNone(package.selected_city)
        self.assertEqual(package.selected_city.city_id, "KR-A")
        self.assertEqual(len(package.recommended_places), 6)
        self.assertTrue(all("details" not in place for place in package.recommended_places))
        self.assertEqual(search.calls[0]["theme"], "바다·해안")
        self.assertIsNone(search.calls[0]["city_id"])

    def test_anchored_search_applies_fixed_city_filter_and_never_mixes_cities(self) -> None:
        candidates = tuple(
            attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군", distance=0.05)
            for index in range(6)
        ) + tuple(
            attraction(f"B-{index}", city_id="KR-B", city_name_ko="비군", distance=0.01)
            for index in range(6)
        )
        search = FakeDestinationSearch(candidates)
        agent = CandidateEvidenceAgent(destination_search=search)

        package = agent.run(
            candidate_input(
                destination_id="KR-A",
                themes=("바다·해안",),
            ),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "ok")
        self.assertEqual(package.mode, ANCHORED_PLACE_SEARCH_MODE)
        self.assertEqual(package.selected_city.city_id, "KR-A")
        self.assertTrue(
            all(place["city_id"] == "KR-A" for place in package.recommended_places),
        )
        self.assertEqual(search.calls[0]["city_id"], "KR-A")
        self.assertEqual(package.retrieval_audit["fixed_city_id"], "KR-A")

    def test_city_discovery_package_validates_for_insufficient_candidates(self) -> None:
        search = FakeDestinationSearch(
            tuple(
                attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군")
                for index in range(2)
            ),
        )
        agent = CandidateEvidenceAgent(destination_search=search)

        package = agent.run(
            candidate_input(themes=("바다·해안",), destination_id=None),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "insufficient_candidates")
        self.assertFalse(package.needs_clarification)
        self.assertEqual(package.candidate_counts["recommended_places"], 2)
        self.assertEqual(package.coverage_audit["unfilled_primary_slots"], 4)

    def test_city_discovery_theme_gate_failure_returns_no_candidate_package(self) -> None:
        search = FakeDestinationSearch(
            (
                attraction("A-1", city_id="KR-A", theme_tags=("바다·해안",)),
                attraction("B-1", city_id="KR-B", theme_tags=("자연·트레킹",)),
            ),
        )
        agent = CandidateEvidenceAgent(destination_search=search)

        package = agent.run(
            candidate_input(themes=("바다·해안", "자연·트레킹")),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "no_candidate")
        self.assertTrue(package.needs_clarification)
        self.assertIn("no_city_after_theme_gate", package.failure_signals)


if __name__ == "__main__":
    unittest.main()
