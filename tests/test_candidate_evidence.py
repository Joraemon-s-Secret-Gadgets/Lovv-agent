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
    build_candidate_reason_claim_request,
    prepare_candidate_evidence_context,
    resolve_candidate_evidence_mode,
    split_candidate_themes,
    validate_candidate_reason_claim_output,
)
from lovv_agent.models.schemas import CandidateEvidenceInput, SchemaValidationError
from lovv_agent.tools.destination_search import AttractionCandidate, prune_cities
from lovv_agent.tools.dynamo_lookup import FestivalCandidate, FestivalSeedResult


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


def festival(
    festival_id: str,
    *,
    city_id: str = "KR-A",
    city_name: str = "에이군",
    month: int = 10,
    assigned_theme: str = "바다·해안",
) -> FestivalCandidate:
    """Return one normalized festival candidate for seed-gate tests."""

    return FestivalCandidate(
        festival_id=festival_id,
        name=f"축제 {festival_id}",
        country="KR",
        city_id=city_id,
        city_name=city_name,
        month=month,
        theme=None,
        theme_tags=(assigned_theme,),
        assigned_theme=assigned_theme,
        event_start_date="2026-10-10",
        event_end_date="2026-10-12",
        source="dynamodb",
        raw={},
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


class FakeDynamoLookup:
    """Injected Dynamo lookup tool for festival seed tests."""

    def __init__(self, result: FestivalSeedResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def search_festival_city_seeds(
        self,
        *,
        country: str,
        travel_month: int,
        theme_pool: tuple[str, ...],
        city_id: str | None = None,
    ) -> FestivalSeedResult:
        self.calls.append(
            {
                "country": country,
                "travel_month": travel_month,
                "theme_pool": theme_pool,
                "city_id": city_id,
            },
        )
        return self.result


class FakeStructuredRuntime:
    """Injected structured-output runtime for reason claim tests."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def __call__(self, request: dict[str, object]) -> object:
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


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


class CandidateEvidenceFestivalSeedTest(unittest.TestCase):
    """Validate festival seed and fixed-city festival lookup behavior."""

    def test_festival_seeded_city_discovery_excludes_non_seeded_cities_before_scoring(self) -> None:
        search = FakeDestinationSearch(
            tuple(
                attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군", distance=0.2)
                for index in range(6)
            )
            + tuple(
                attraction(f"B-{index}", city_id="KR-B", city_name_ko="비군", distance=0.01)
                for index in range(6)
            ),
        )
        dynamo = FakeDynamoLookup(
            FestivalSeedResult(status="ok", candidates=(festival("F-A"),)),
        )
        agent = CandidateEvidenceAgent(
            destination_search=search,
            dynamo_lookup=dynamo,
        )

        package = agent.run(
            candidate_input(
                include_festivals=True,
                themes=("바다·해안",),
            ),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "ok")
        self.assertEqual(package.mode, FESTIVAL_SEEDED_CITY_DISCOVERY_MODE)
        self.assertEqual(package.selected_city.city_id, "KR-A")
        self.assertTrue(all(place["city_id"] == "KR-A" for place in package.recommended_places))
        self.assertEqual(package.festival_seed_audit["seed_city_ids"], ["KR-A"])
        self.assertEqual(package.selected_festival_candidates[0]["city_id"], "KR-A")
        self.assertIsNone(search.calls[0]["city_id"])
        self.assertEqual(dynamo.calls[0]["theme_pool"], ("바다·해안",))

    def test_festival_seed_empty_theme_pool_returns_no_required_theme_signal(self) -> None:
        search = FakeDestinationSearch(())
        dynamo = FakeDynamoLookup(FestivalSeedResult(status="ok"))
        agent = CandidateEvidenceAgent(
            destination_search=search,
            dynamo_lookup=dynamo,
        )

        package = agent.run(
            candidate_input(
                include_festivals=True,
                themes=("festival_event", "축제·이벤트"),
            ),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "no_candidate")
        self.assertTrue(package.needs_clarification)
        self.assertIn("no_required_theme_for_festival_seed", package.failure_signals)
        self.assertEqual(search.calls, [])
        self.assertEqual(dynamo.calls, [])

    def test_festival_seed_empty_city_seed_prevents_attraction_retrieval(self) -> None:
        search = FakeDestinationSearch(())
        dynamo = FakeDynamoLookup(
            FestivalSeedResult(
                status="no_candidate",
                failure_signals=("no_festival_city_seed",),
                needs_clarification=True,
            ),
        )
        agent = CandidateEvidenceAgent(
            destination_search=search,
            dynamo_lookup=dynamo,
        )

        package = agent.run(
            candidate_input(include_festivals=True, themes=("자연·트레킹",)),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "no_candidate")
        self.assertTrue(package.needs_clarification)
        self.assertIn("no_festival_city_seed", package.failure_signals)
        self.assertFalse(package.fallback_audit["planner_consumable"])
        self.assertEqual(search.calls, [])

    def test_fixed_city_festival_lookup_failure_returns_anchor_signal(self) -> None:
        search = FakeDestinationSearch(())
        dynamo = FakeDynamoLookup(
            FestivalSeedResult(
                status="no_candidate",
                failure_signals=("no_festival_in_anchor_city",),
                needs_clarification=True,
            ),
        )
        agent = CandidateEvidenceAgent(
            destination_search=search,
            dynamo_lookup=dynamo,
        )

        package = agent.run(
            candidate_input(
                destination_id="KR-A",
                include_festivals=True,
                themes=("바다·해안",),
            ),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "no_candidate")
        self.assertTrue(package.needs_clarification)
        self.assertIn("no_festival_in_anchor_city", package.failure_signals)
        self.assertEqual(dynamo.calls[0]["city_id"], "KR-A")
        self.assertEqual(search.calls, [])

    def test_fixed_city_festival_success_keeps_selected_festivals_in_anchor_city(self) -> None:
        search = FakeDestinationSearch(
            tuple(
                attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군", distance=0.05)
                for index in range(6)
            ),
        )
        dynamo = FakeDynamoLookup(
            FestivalSeedResult(
                status="ok",
                candidates=(
                    festival("F-A", city_id="KR-A", city_name="에이군"),
                    festival("F-B", city_id="KR-B", city_name="비군"),
                ),
            ),
        )
        agent = CandidateEvidenceAgent(
            destination_search=search,
            dynamo_lookup=dynamo,
        )

        package = agent.run(
            candidate_input(
                destination_id="KR-A",
                include_festivals=True,
                themes=("바다·해안",),
            ),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "ok")
        self.assertEqual(package.mode, ANCHORED_PLACE_SEARCH_MODE)
        self.assertEqual(package.selected_city.city_id, "KR-A")
        self.assertEqual(
            [item["city_id"] for item in package.selected_festival_candidates],
            ["KR-A"],
        )
        self.assertEqual(search.calls[0]["city_id"], "KR-A")


class CandidateEvidencePackageAndReasonClaimTest(unittest.TestCase):
    """Validate package audit fields and compact reason claim candidates."""

    def test_package_adds_template_reason_claims_without_raw_score_text(self) -> None:
        search = FakeDestinationSearch(
            tuple(
                attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군")
                for index in range(6)
            ),
        )
        agent = CandidateEvidenceAgent(destination_search=search)

        package = agent.run(
            candidate_input(themes=("바다·해안",)),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "ok")
        self.assertGreaterEqual(len(package.candidate_reason_claims), 2)
        first_claim = package.candidate_reason_claims[0]
        self.assertEqual(first_claim.scope, "city_selection")
        self.assertIn("selected_city", first_claim.evidence_refs)
        rendered_claims = " ".join(claim.text_ko for claim in package.candidate_reason_claims)
        self.assertNotIn("place_score", rendered_claims)
        self.assertNotIn("score_components", rendered_claims)

    def test_build_reason_claim_request_hides_raw_score_audit(self) -> None:
        search = FakeDestinationSearch(
            tuple(
                attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군")
                for index in range(6)
            ),
        )
        agent = CandidateEvidenceAgent(destination_search=search)
        candidate = candidate_input(themes=("바다·해안",))
        context = agent.prepare_context(candidate)
        package = agent.run(candidate, query_vector=(0.1, 0.2))

        request = build_candidate_reason_claim_request(package, context=context)
        request_text = request["messages"][0]["content"][0]["text"]

        self.assertNotIn("score_audit", request_text)
        self.assertNotIn("place_score", request_text)
        self.assertNotIn("score_components", request_text)
        self.assertIn("candidate_reason_claim_output", str(request["outputConfig"]))

    def test_reason_claim_runtime_cannot_change_selected_city_or_status(self) -> None:
        runtime = FakeStructuredRuntime(
            [
                {
                    "structured_output": {
                        "status": "error",
                        "selected_city": {"city_id": "KR-B"},
                        "candidate_reason_claims": [
                            {
                                "claim_id": "bad_1",
                                "scope": "city_selection",
                                "text_ko": "다른 도시로 바꿉니다.",
                                "evidence_refs": ["selected_city"],
                                "required_place_ids": [],
                                "public_eligible": True,
                            },
                        ],
                    },
                },
            ],
        )
        search = FakeDestinationSearch(
            tuple(
                attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군")
                for index in range(6)
            ),
        )
        agent = CandidateEvidenceAgent(
            destination_search=search,
            reason_claim_runtime=runtime,
            schema_retry_limit=0,
        )

        package = agent.run(
            candidate_input(themes=("바다·해안",)),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(package.status, "ok")
        self.assertEqual(package.selected_city.city_id, "KR-A")
        self.assertIn("candidate_reason_claim_generation", package.warnings)
        self.assertFalse(package.candidate_reason_claims[0].public_eligible)

    def test_reason_claim_schema_failure_retries_and_records_warning(self) -> None:
        runtime = FakeStructuredRuntime(
            [
                {"structured_output": {"candidate_reason_claims": []}},
                {"structured_output": {"candidate_reason_claims": "still invalid"}},
            ],
        )
        search = FakeDestinationSearch(
            tuple(
                attraction(f"A-{index}", city_id="KR-A", city_name_ko="에이군")
                for index in range(6)
            ),
        )
        agent = CandidateEvidenceAgent(
            destination_search=search,
            reason_claim_runtime=runtime,
            schema_retry_limit=1,
        )

        package = agent.run(
            candidate_input(themes=("바다·해안",)),
            query_vector=(0.1, 0.2),
        )

        warning = package.warnings["candidate_reason_claim_generation"]
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(warning["status"], "schema_failure")
        self.assertEqual(warning["attempts"], 2)
        self.assertFalse(package.candidate_reason_claims[0].public_eligible)

    def test_no_candidate_and_error_packages_do_not_generate_reason_claims(self) -> None:
        runtime = FakeStructuredRuntime(
            [
                {
                    "structured_output": {
                        "candidate_reason_claims": [
                            {
                                "claim_id": "unused",
                                "scope": "fallback_notice",
                                "text_ko": "사용되지 않아야 합니다.",
                                "evidence_refs": ["fallback_audit"],
                                "required_place_ids": [],
                                "public_eligible": False,
                            },
                        ],
                    },
                },
            ],
        )
        search = FakeDestinationSearch(())
        agent = CandidateEvidenceAgent(
            destination_search=search,
            reason_claim_runtime=runtime,
        )

        no_candidate_package = agent.run(
            candidate_input(themes=("바다·해안",)),
            query_vector=(0.1, 0.2),
        )
        error_package = agent.run(
            candidate_input(include_festivals=True, themes=("바다·해안",)),
            query_vector=(0.1, 0.2),
        )

        self.assertEqual(no_candidate_package.status, "no_candidate")
        self.assertEqual(no_candidate_package.candidate_reason_claims, ())
        self.assertEqual(error_package.status, "error")
        self.assertEqual(error_package.candidate_reason_claims, ())
        self.assertEqual(runtime.calls, [])

    def test_reason_claim_validator_rejects_internal_score_tokens(self) -> None:
        with self.assertRaises(SchemaValidationError):
            validate_candidate_reason_claim_output(
                {
                    "candidate_reason_claims": [
                        {
                            "claim_id": "unsafe",
                            "scope": "city_selection",
                            "text_ko": "place_score 값을 보면 좋습니다.",
                            "evidence_refs": ["selected_city"],
                            "required_place_ids": [],
                            "public_eligible": True,
                        },
                    ],
                },
            )


if __name__ == "__main__":
    unittest.main()
