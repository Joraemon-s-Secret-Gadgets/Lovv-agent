"""Tests for Task 1.3 state and handoff schemas."""

from __future__ import annotations

import unittest

from lovv_agent.models.schemas import (
    CANDIDATE_EVIDENCE_STATUSES,
    CandidateEvidenceInput,
    CandidateEvidencePackage,
    ExplanationFacts,
    PlannerExplanationAudit,
    FestivalVerification,
    PlannerOutput,
    SchemaValidationError,
    WorkerOutputState,
)
from lovv_agent.state import (
    STATE_GROUPS,
    FULFILLED_MATRIX_STATUSES,
    RequestState,
    RoutingState,
    UnifiedAgentState,
)


class SchemaContractTest(unittest.TestCase):
    """Validate local schema contracts before node logic is implemented."""

    def test_unified_state_contains_required_groups(self) -> None:
        state = UnifiedAgentState(
            request=RequestState(
                request_id="REQ-1",
                entry_type="city_discovery",
                country="KR",
                travel_year=2026,
                travel_month=6,
                trip_type="2d1n",
                destination_id=None,
                themes=("sea", "local_food"),
                include_festivals=False,
            ),
        )

        self.assertEqual(
            STATE_GROUPS,
            (
                "request",
                "conversation",
                "trace",
                "intent",
                "routing",
                "evidence",
                "festival",
                "planning",
                "serving",
            ),
        )
        self.assertEqual(set(state.to_dict()), set(STATE_GROUPS))
        self.assertEqual(
            state.routing.fulfilled_matrix,
            {"evidence": "X", "festival": "X", "planning": "X"},
        )

    def test_routing_matrix_rejects_unknown_status(self) -> None:
        self.assertEqual(FULFILLED_MATRIX_STATUSES, ("X", "O", "△", "N/A"))

        with self.assertRaises(SchemaValidationError):
            RoutingState(fulfilled_matrix={"evidence": "DONE", "festival": "X", "planning": "X"})

    def test_candidate_evidence_input_validates_spec_sample(self) -> None:
        payload = {
            "country": "KR",
            "travelMonth": 6,
            "travelYear": 2026,
            "tripType": "2d1n",
            "destinationId": None,
            "active_required_themes": ["sea_coast", "local_food"],
            "cleaned_raw_query": "quiet coast and local food",
            "soft_preference_query": "not too crowded",
            "unsupported_conditions": [],
            "user_location": {"latitude": 37.5665, "longitude": 126.978},
            "includeFestivals": False,
        }

        schema = CandidateEvidenceInput.from_mapping(payload)

        self.assertEqual(schema.travel_month, 6)
        self.assertEqual(schema.travel_year, 2026)
        self.assertEqual(schema.active_required_themes, ("sea_coast", "local_food"))
        self.assertFalse(schema.include_festivals)
        self.assertIsNotNone(schema.user_location)

    def test_candidate_evidence_statuses_are_limited(self) -> None:
        self.assertEqual(
            CANDIDATE_EVIDENCE_STATUSES,
            ("ok", "insufficient_candidates", "no_candidate", "error"),
        )

        for status in CANDIDATE_EVIDENCE_STATUSES:
            package = CandidateEvidencePackage(status=status)
            self.assertEqual(package.status, status)

        with self.assertRaises(SchemaValidationError):
            CandidateEvidencePackage(status="partial")

    def test_clarification_requires_question_across_worker_outputs(self) -> None:
        with self.assertRaises(SchemaValidationError):
            CandidateEvidencePackage(status="no_candidate", needs_clarification=True)

        with self.assertRaises(SchemaValidationError):
            WorkerOutputState(status="no_candidate", needs_clarification=True)

        package = CandidateEvidencePackage(
            status="no_candidate",
            needs_clarification=True,
            clarifying_question="Continue without festivals?",
        )
        self.assertTrue(package.needs_clarification)

    def test_candidate_evidence_package_sample_validates(self) -> None:
        package = CandidateEvidencePackage.from_mapping(
            {
                "status": "ok",
                "failure_signals": [],
                "needs_clarification": False,
                "clarifying_question": None,
                "mode": "city_discovery",
                "selected_city": {
                    "city_id": "city-1",
                    "city_name_ko": "Sample City",
                    "country": "KR",
                    "selection_reason_code": [
                        "theme_coverage",
                        "candidate_sufficiency",
                    ],
                },
                "city_rankings": [],
                "recommended_places": [{"place_id": "P-1", "title": "Beach"}],
                "reserve_places": [],
                "festival_candidates": [],
                "selected_festival_candidates": [],
                "festival_seed_audit": {},
                "coverage_audit": {},
                "retrieval_audit": {},
                "candidate_counts": {},
                "warnings": {},
                "fallback_audit": {},
            },
        )

        self.assertEqual(package.status, "ok")
        self.assertEqual(package.selected_city.city_id, "city-1")
        self.assertEqual(package.recommended_places[0]["place_id"], "P-1")

    def test_explanation_facts_ground_query_and_place_overview(self) -> None:
        package = CandidateEvidencePackage.from_mapping(
            {
                "status": "ok",
                "mode": "city_discovery",
                "selected_city": {
                    "city_id": "city-1",
                    "city_name_ko": "Sample City",
                    "country": "KR",
                },
                "recommended_places": [
                    {
                        "place_id": "P-1",
                        "title": "Quiet Coast",
                        "overview": "A calm seaside walking area with sunset views.",
                    },
                ],
                "explanation_facts": {
                    "query_context": {
                        "cleaned_raw_query": "바다 산책을 하고 싶다",
                        "soft_preference_query": "너무 붐비지 않는 분위기",
                    },
                    "city_choice": {
                        "city_id": "city-1",
                        "city_name_ko": "Sample City",
                        "reason_codes": ["theme_coverage", "candidate_sufficiency"],
                        "representative_place_ids": ["P-1"],
                        "summary": "바다 산책 후보가 충분한 도시입니다.",
                    },
                    "place_alignment": [
                        {
                            "place_id": "P-1",
                            "title": "Quiet Coast",
                            "overview": "A calm seaside walking area with sunset views.",
                            "matched_themes": ["바다·해안"],
                            "raw_query_alignment": "바다 산책 요청과 직접 연결됩니다.",
                            "soft_query_alignment": "조용한 분위기 선호와 맞습니다.",
                            "reason_codes": [
                                "raw_query_match",
                                "overview_theme_match",
                            ],
                        },
                    ],
                    "festival_anchor": {
                        "used": False,
                        "matched_month": None,
                        "matched_themes": [],
                        "selected_festival_ids": [],
                    },
                    "limitations": [],
                },
            },
        )

        self.assertIsInstance(package.explanation_facts, ExplanationFacts)
        self.assertEqual(
            package.explanation_facts.query_context.soft_preference_query,
            "너무 붐비지 않는 분위기",
        )
        self.assertEqual(
            package.explanation_facts.place_alignment[0].overview,
            "A calm seaside walking area with sunset views.",
        )

    def test_festival_and_planner_payload_samples_validate(self) -> None:
        verification = FestivalVerification.from_mapping(
            {
                "festival_id": "FEST-123",
                "name": "Sample Festival",
                "date_status": "confirmed",
                "start_date": "2026-06-10",
                "end_date": "2026-06-12",
                "is_applicable_to_trip": True,
                "planner_policy": "placeable",
                "source_type": "dynamodb_detail",
                "confidence": 0.8,
                "evidence_summary": "Start date year matches the travel year.",
            },
        )
        planner_output = PlannerOutput.from_mapping(
            {
                "itinerary": [{"day": 1, "items": []}],
                "alternativeItinerary": [],
                "recommendationReasons": ["theme coverage"],
                "itineraryFlowReason": "compact city route",
                "externalLinks": {"foodSearch": "https://example.test/search"},
                "confidence": 0.7,
                "user_notice": [],
                "validation_result": {"ok": True},
                "explanation_audit": {
                    "reason_refs": [
                        {
                            "reason_id": "recommendationReasons[0]",
                            "reason_text": "Selected city matches the coastal walk request.",
                            "evidence_refs": ["place:P-1"],
                            "reason_codes": ["raw_query_match"],
                        },
                    ],
                    "itinerary_flow_refs": ["place:P-1"],
                    "hidden_internal_notes": ["score values are not public"],
                },
            },
        )

        self.assertEqual(verification.date_status, "confirmed")
        self.assertEqual(planner_output.recommendation_reasons, ("theme coverage",))
        self.assertEqual(planner_output.validation_result["ok"], True)
        self.assertIsInstance(planner_output.explanation_audit, PlannerExplanationAudit)
        self.assertEqual(
            planner_output.explanation_audit.reason_refs[0].evidence_refs,
            ("place:P-1",),
        )


if __name__ == "__main__":
    unittest.main()
