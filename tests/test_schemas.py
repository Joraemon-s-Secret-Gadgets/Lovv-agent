"""Tests for Task 1.3 state and handoff schemas."""

from __future__ import annotations

import unittest

from lovv_agent.models.schemas import (
    CANDIDATE_EVIDENCE_STATUSES,
    CandidateEvidenceInput,
    CandidateEvidencePackage,
    CandidateReasonClaim,
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

    def test_candidate_reason_claims_keep_evidence_refs(self) -> None:
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
                        "evidence_reason_code": ["raw_query_match", "theme_match"],
                    },
                ],
                "candidate_reason_claims": [
                    {
                        "claim_id": "city_reason_1",
                        "scope": "city_selection",
                        "text_ko": "선택 도시는 바다·해안 테마 후보가 충분합니다.",
                        "evidence_refs": ["selected_city", "coverage_audit"],
                        "required_place_ids": [],
                        "public_eligible": True,
                    },
                    {
                        "claim_id": "place_pool_1",
                        "scope": "place_pool",
                        "text_ko": "대표 후보들은 사용자의 바다 산책 요청과 연결됩니다.",
                        "evidence_refs": ["recommended_places:P-1"],
                        "required_place_ids": ["P-1"],
                        "public_eligible": True,
                    },
                ],
            },
        )

        self.assertIsInstance(package.candidate_reason_claims[0], CandidateReasonClaim)
        self.assertEqual(
            package.candidate_reason_claims[0].scope,
            "city_selection",
        )
        self.assertEqual(
            package.candidate_reason_claims[1].required_place_ids,
            ("P-1",),
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
