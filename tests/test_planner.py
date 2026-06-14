"""Tests for Planner Agent behavior."""

from __future__ import annotations

from dataclasses import replace
import unittest

from lovv_agent.agents.planner import PlannerAgent, TRIP_SLOT_TEMPLATES
from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    CandidateReasonClaim,
    FestivalVerification,
    PlannerExplanationAudit,
    SelectedCity,
)
from lovv_agent.tools.dynamo_lookup import DetailEnrichmentResult
from lovv_agent.tools.validation import validate_planner_output


class PlannerCopyRuntime:
    """Fake structured-output runtime for Planner copy tests."""

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def __call__(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(dict(request))
        return self.response


class RecordingDynamoLookup:
    """Fake Dynamo lookup that enriches only final placed candidates."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def enrich_final_places(self, final_places: tuple[object, ...]) -> DetailEnrichmentResult:
        self.calls.append(tuple(final_places))
        return DetailEnrichmentResult(
            places=tuple(
                replace(
                    place,
                    details={
                        "overview": f"{place.title}의 Dynamo 상세 설명입니다.",
                        "latitude": 36.2,
                        "longitude": 128.3,
                    },
                )
                for place in final_places
            ),
        )


def place(
    place_id: str,
    *,
    title: str | None = None,
    details: dict[str, object] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, object]:
    """Return one lightweight Candidate Evidence place payload."""

    return {
        "place_id": place_id,
        "title": title or f"장소 {place_id}",
        "city_id": "KR-A",
        "city_name_ko": "에이군",
        "theme_tags": ["바다·해안"],
        "ddb_pk": f"CITY#KR-A",
        "ddb_sk": f"ATTRACTION#{place_id}",
        "details": details,
        "latitude": latitude,
        "longitude": longitude,
    }


def evidence_package(
    *,
    status: str = "ok",
    recommended_count: int = 6,
    selected_city: SelectedCity | None = None,
    failure_signals: tuple[str, ...] = (),
) -> CandidateEvidencePackage:
    """Build a Candidate Evidence package for Planner tests."""

    return CandidateEvidencePackage(
        status=status,
        failure_signals=failure_signals,
        mode="city_discovery",
        selected_city=selected_city
        or SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=tuple(place(f"P-{index}") for index in range(recommended_count)),
        reserve_places=tuple(place(f"R-{index}") for index in range(2)),
        coverage_audit={"candidate_sufficiency": "sufficient"},
        candidate_counts={"recommended_places": recommended_count},
    )


def festival_package(*, mode: str = "festival_seeded_city_discovery") -> CandidateEvidencePackage:
    """Build a Candidate Evidence package with a selected festival candidate."""

    return CandidateEvidencePackage(
        status="ok",
        mode=mode,
        selected_city=SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=tuple(place(f"P-{index}") for index in range(4)),
        selected_festival_candidates=(
            {
                "festival_id": "F-A",
                "name": "에이 축제",
                "city_id": "KR-A",
                "city_name": "에이군",
                "month": 10,
            },
        ),
    )


def gourmet_package() -> CandidateEvidencePackage:
    """Build a package whose gourmet theme must become an external link."""

    return CandidateEvidencePackage(
        status="ok",
        mode="city_discovery",
        selected_city=SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=tuple(place(f"P-{index}") for index in range(4)),
        coverage_audit={"external_link_themes": ["미식·노포"]},
    )


def reason_claim_package(
    *,
    claim_required_ids: tuple[str, ...] = ("P-0",),
    public_eligible: bool = True,
    claim_text: str = "조용한 바다 산책 요청과 대표 후보가 잘 맞습니다.",
) -> CandidateEvidencePackage:
    """Build a package with Candidate Evidence reason claims."""

    return CandidateEvidencePackage(
        status="ok",
        mode="city_discovery",
        selected_city=SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=(
            place(
                "P-0",
                details={"overview": "조용한 해안 산책로가 있는 대표 관광지입니다."},
            ),
            place("P-1"),
            place("P-2"),
        ),
        candidate_reason_claims=(
            CandidateReasonClaim(
                claim_id="claim-1",
                scope="place_pool",
                text_ko=claim_text,
                evidence_refs=("recommended_places:P-0",),
                required_place_ids=claim_required_ids,
                public_eligible=public_eligible,
            ),
        ),
    )


def festival_verification(
    *,
    festival_id: str = "F-A",
    date_status: str = "confirmed",
    applicable: bool = True,
    planner_policy: str = "placeable",
) -> FestivalVerification:
    """Return one Festival Verifier output for Planner tests."""

    return FestivalVerification(
        festival_id=festival_id,
        name="에이 축제",
        date_status=date_status,
        start_date="2026-10-10",
        end_date="2026-10-12",
        is_applicable_to_trip=applicable,
        planner_policy=planner_policy,
        source_type="dynamodb_detail",
        confidence=0.8,
        evidence_summary="verified",
    )


class PlannerStatusAndSlotTest(unittest.TestCase):
    """Validate Task 8.1 Planner status gates and slot templates."""

    def test_ok_status_creates_itinerary_from_grounded_candidates(self) -> None:
        output = PlannerAgent().plan(evidence_package(), trip_type="daytrip")

        self.assertEqual(len(output.itinerary), len(TRIP_SLOT_TEMPLATES["daytrip"]))
        self.assertEqual(output.itinerary[0]["item_type"], "attraction")
        self.assertEqual(output.itinerary[0]["placeId"], "P-0")
        self.assertEqual(output.validation_result["planner_status_gate"], "ok")

    def test_insufficient_candidates_creates_reduced_itinerary_when_safe(self) -> None:
        output = PlannerAgent().plan(
            evidence_package(status="insufficient_candidates", recommended_count=2),
            trip_type="daytrip",
        )

        self.assertEqual(len(output.itinerary), 2)
        self.assertEqual(output.validation_result["planner_status_gate"], "insufficient_candidates")
        self.assertTrue(output.user_notice)
        self.assertLess(output.confidence, 0.72)

    def test_no_candidate_does_not_create_normal_itinerary(self) -> None:
        output = PlannerAgent().plan(
            CandidateEvidencePackage(
                status="no_candidate",
                failure_signals=("no_city_after_theme_gate",),
                mode="city_discovery",
            ),
            trip_type="daytrip",
        )

        self.assertEqual(output.itinerary, ())
        self.assertEqual(output.validation_result["status"], "blocked")
        self.assertEqual(output.confidence, 0.0)

    def test_error_does_not_create_normal_itinerary(self) -> None:
        output = PlannerAgent().plan(
            CandidateEvidencePackage(
                status="error",
                failure_signals=("s3_vector_failure",),
                mode="city_discovery",
            ),
            trip_type="2d1n",
        )

        self.assertEqual(output.itinerary, ())
        self.assertEqual(output.validation_result["planner_status_gate"], "error")

    def test_trip_type_slot_template_controls_slot_count(self) -> None:
        output = PlannerAgent().plan(
            evidence_package(recommended_count=10),
            trip_type="2d1n",
        )

        self.assertEqual(len(output.itinerary), len(TRIP_SLOT_TEMPLATES["2d1n"]))
        self.assertEqual(
            [(slot["day"], slot["slot"]) for slot in output.itinerary],
            list(TRIP_SLOT_TEMPLATES["2d1n"]),
        )


class PlannerFestivalOverlayTest(unittest.TestCase):
    """Validate Task 8.2 festival overlay policy."""

    def test_festival_overlay_places_only_confirmed_applicable_festival(self) -> None:
        output = PlannerAgent().plan(
            festival_package(),
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(festival_verification(),),
        )

        festival_items = [
            item for item in output.itinerary if item["item_type"] == "festival"
        ]
        self.assertEqual(len(festival_items), 1)
        self.assertEqual(festival_items[0]["festivalId"], "F-A")
        self.assertEqual(festival_items[0]["source"], "festival_verifier")
        self.assertEqual(output.validation_result["festival_placed_count"], 1)

    def test_festival_overlay_skips_unconfirmed_or_inapplicable_festivals(self) -> None:
        output = PlannerAgent().plan(
            festival_package(),
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(
                festival_verification(date_status="tentative", planner_policy="not_placeable"),
                festival_verification(date_status="unknown", planner_policy="not_placeable"),
                festival_verification(date_status="outdated", planner_policy="not_placeable"),
                festival_verification(applicable=False, planner_policy="not_placeable"),
            ),
        )

        self.assertFalse(any(item["item_type"] == "festival" for item in output.itinerary))
        self.assertEqual(output.validation_result["festival_placed_count"], 0)
        self.assertEqual(output.validation_result["festival_skipped_count"], 4)
        self.assertTrue(output.user_notice)

    def test_festival_overlay_requires_selected_city_provenance(self) -> None:
        output = PlannerAgent().plan(
            festival_package(),
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(festival_verification(festival_id="F-B"),),
        )

        self.assertFalse(any(item["item_type"] == "festival" for item in output.itinerary))
        self.assertEqual(output.validation_result["festival_placed_count"], 0)

    def test_anchored_mode_keeps_anchored_city(self) -> None:
        output = PlannerAgent().plan(
            festival_package(mode="anchored_place_search"),
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(festival_verification(),),
        )

        attraction_cities = {
            item["city_id"]
            for item in output.itinerary
            if item["item_type"] == "attraction"
        }
        self.assertEqual(attraction_cities, {"KR-A"})
        self.assertTrue(any(item["item_type"] == "festival" for item in output.itinerary))


class PlannerGourmetPolicyTest(unittest.TestCase):
    """Validate Task 8.3 gourmet link and placeholder policy."""

    def test_gourmet_theme_adds_food_search_link_and_placeholder(self) -> None:
        output = PlannerAgent().plan(gourmet_package(), trip_type="daytrip")

        self.assertIn("foodSearch", output.external_links)
        self.assertEqual(output.external_links["foodSearch"]["type"], "foodSearch")
        self.assertEqual(output.external_links["foodSearch"]["query"], "에이군 맛집")
        self.assertEqual(
            output.validation_result["food_search_link_required"],
            True,
        )

        placeholders = [
            item for item in output.itinerary if item["item_type"] == "meal_placeholder"
        ]
        self.assertEqual(len(placeholders), 1)
        self.assertIsNone(placeholders[0]["placeId"])
        self.assertEqual(placeholders[0]["source"], "placeholder")
        self.assertEqual(placeholders[0]["linkRef"], "foodSearch")

    def test_gourmet_theme_does_not_generate_named_restaurant_items(self) -> None:
        output = PlannerAgent().plan(gourmet_package(), trip_type="daytrip")

        restaurant_items = [
            item for item in output.itinerary if item["item_type"] == "restaurant"
        ]
        self.assertEqual(restaurant_items, [])
        self.assertFalse(
            any(
                item.get("placeId")
                for item in output.itinerary
                if item["item_type"] == "meal_placeholder"
            ),
        )

    def test_non_gourmet_package_still_has_default_links_without_placeholder(self) -> None:
        output = PlannerAgent().plan(evidence_package(), trip_type="daytrip")

        self.assertIn("map", output.external_links)
        self.assertIn("staySearch", output.external_links)
        self.assertIn("foodSearch", output.external_links)
        self.assertFalse(
            any(item["item_type"] == "meal_placeholder" for item in output.itinerary),
        )

    def test_attraction_slot_preserves_candidate_coordinates(self) -> None:
        package = CandidateEvidencePackage(
            status="ok",
            mode="city_discovery",
            selected_city=SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
            recommended_places=(
                place("P-0", latitude=37.5, longitude=127.1),
                place("P-1"),
            ),
        )

        output = PlannerAgent().plan(package, trip_type="daytrip")

        self.assertEqual(output.itinerary[0]["latitude"], 37.5)
        self.assertEqual(output.itinerary[0]["longitude"], 127.1)


class PlannerValidationTest(unittest.TestCase):
    """Validate Task 8.4 minimal Planner validation helper."""

    def test_validation_passes_grounded_planner_output(self) -> None:
        output = PlannerAgent().plan(evidence_package(), trip_type="daytrip")

        self.assertEqual(output.validation_result["status"], "valid")
        self.assertTrue(output.validation_result["is_valid"])
        self.assertEqual(output.validation_result["errors"], ())

    def test_validation_rejects_ungrounded_attraction(self) -> None:
        result = validate_planner_output(
            (
                {
                    "item_type": "attraction",
                    "placeId": "UNKNOWN",
                    "title": "근거 없는 장소",
                },
            ),
            package=evidence_package(),
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"][0]["code"], "ungrounded_attraction")
        self.assertEqual(result["retry_action"], "remove_or_rewrite_offending_items")

    def test_validation_rejects_named_restaurant_from_model_knowledge(self) -> None:
        result = validate_planner_output(
            (
                {
                    "item_type": "restaurant",
                    "placeId": "restaurant#model",
                    "title": "모델이 만든 식당명",
                    "source": "model_knowledge",
                },
            ),
            package=evidence_package(),
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"][0]["code"], "named_restaurant_not_allowed")

    def test_validation_rejects_unconfirmed_festival_placement(self) -> None:
        result = validate_planner_output(
            (
                {
                    "item_type": "festival",
                    "festivalId": "F-A",
                    "title": "에이 축제",
                    "source": "festival_verifier",
                },
            ),
            package=festival_package(),
            festival_verifications=(
                festival_verification(date_status="tentative", planner_policy="not_placeable"),
            ),
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"][0]["code"], "unconfirmed_festival")


class PlannerExplanationTest(unittest.TestCase):
    """Validate Task 8.5 grounded explanation generation."""

    def test_recommendation_reason_uses_verified_claim_and_overview(self) -> None:
        output = PlannerAgent().plan(reason_claim_package(), trip_type="daytrip")

        self.assertIn("조용한 바다 산책", output.recommendation_reasons[0])
        self.assertIn("조용한 해안 산책로", output.recommendation_reasons[0])
        self.assertIsInstance(output.explanation_audit, PlannerExplanationAudit)
        self.assertEqual(
            output.explanation_audit.reason_refs[0].evidence_refs,
            ("recommended_places:P-0",),
        )
        self.assertEqual(
            output.explanation_audit.reason_refs[0].reason_codes,
            ("place_pool",),
        )

    def test_recommendation_reason_skips_claim_when_required_place_is_not_placed(self) -> None:
        output = PlannerAgent().plan(
            reason_claim_package(claim_required_ids=("P-9",)),
            trip_type="daytrip",
        )

        self.assertIn("확인 가능한 정보만", output.recommendation_reasons[0])
        self.assertIn(
            "skipped_missing_place_ids:claim-1",
            output.explanation_audit.hidden_internal_notes,
        )

    def test_recommendation_reason_skips_internal_score_terms(self) -> None:
        output = PlannerAgent().plan(
            reason_claim_package(claim_text="내부 점수와 top_k 기준으로 높은 후보입니다."),
            trip_type="daytrip",
        )

        self.assertNotIn("top_k", output.recommendation_reasons[0])
        self.assertIn(
            "skipped_internal_term:claim-1",
            output.explanation_audit.hidden_internal_notes,
        )

    def test_itinerary_flow_reason_stays_public_safe(self) -> None:
        output = PlannerAgent().plan(reason_claim_package(), trip_type="daytrip")

        self.assertIn("tripType 기본 시간대", output.itinerary_flow_reason)
        self.assertNotIn("top", output.itinerary_flow_reason.lower())
        self.assertNotIn("점수", output.itinerary_flow_reason)

    def test_planner_llm_composer_updates_item_copy_and_reasons(self) -> None:
        runtime = PlannerCopyRuntime(
            {
                "structured_output": {
                    "item_copies": [
                        {
                            "item_ref": "item:0",
                            "title": "잔잔한 해안 산책",
                            "body": "조용한 해안 산책로 설명을 바탕으로 오전에 걷기 좋게 배치했습니다.",
                            "reason": "사용자의 조용한 바다 산책 선호와 직접 맞닿아 있습니다.",
                        },
                    ],
                    "recommendation_reasons": [
                        "에이군은 조용한 바다 산책 요청과 배치된 대표 장소가 잘 맞습니다.",
                    ],
                    "itinerary_flow_reason": "오전 산책 후 같은 도시 안에서 가볍게 이어지는 흐름입니다.",
                },
            },
        )

        output = PlannerAgent(explanation_runtime=runtime, schema_retry_limit=0).plan(
            reason_claim_package(),
            trip_type="daytrip",
        )

        self.assertEqual(output.itinerary[0]["title"], "잔잔한 해안 산책")
        self.assertEqual(
            output.itinerary[0]["reason"],
            "사용자의 조용한 바다 산책 선호와 직접 맞닿아 있습니다.",
        )
        self.assertEqual(
            output.recommendation_reasons[0],
            "에이군은 조용한 바다 산책 요청과 배치된 대표 장소가 잘 맞습니다.",
        )
        self.assertEqual(
            output.itinerary_flow_reason,
            "오전 산책 후 같은 도시 안에서 가볍게 이어지는 흐름입니다.",
        )
        self.assertIn(
            "planner_copy_generation:llm_used:ok",
            output.explanation_audit.hidden_internal_notes,
        )
        self.assertIn("Planner Agent", runtime.requests[0]["system"][0]["text"])

    def test_planner_llm_composer_schema_failure_uses_deterministic_fallback(self) -> None:
        runtime = PlannerCopyRuntime(
            {
                "structured_output": {
                    "item_copies": [
                        {
                            "item_ref": "item:0",
                            "title": "내부 top_k 점수 추천",
                            "body": "점수 기준입니다.",
                            "reason": "top_k 때문입니다.",
                        },
                    ],
                    "recommendation_reasons": ["내부 점수와 top_k 기준입니다."],
                    "itinerary_flow_reason": "점수 기준입니다.",
                },
            },
        )

        output = PlannerAgent(explanation_runtime=runtime, schema_retry_limit=0).plan(
            reason_claim_package(),
            trip_type="daytrip",
        )

        self.assertNotIn("top_k", output.recommendation_reasons[0])
        self.assertEqual(output.itinerary[0]["title"], "장소 P-0")
        self.assertIn(
            "planner_copy_generation:schema_failure:1",
            output.explanation_audit.hidden_internal_notes,
        )

    def test_planner_enriches_only_final_placed_attractions_before_explanation(self) -> None:
        dynamo_lookup = RecordingDynamoLookup()
        package = reason_claim_package()

        output = PlannerAgent(dynamo_lookup=dynamo_lookup).plan(
            package,
            trip_type="daytrip",
        )

        self.assertEqual(len(dynamo_lookup.calls), 1)
        enriched_candidates = dynamo_lookup.calls[0]
        self.assertEqual(
            [candidate.place_id for candidate in enriched_candidates],
            ["P-0", "P-1", "P-2"],
        )
        self.assertEqual(output.itinerary[0]["details"]["latitude"], 36.2)
        self.assertEqual(output.itinerary[0]["details"]["longitude"], 128.3)
        self.assertIn(
            "Dynamo 상세 설명",
            output.recommendation_reasons[0],
        )
        self.assertEqual(output.validation_result["detail_enrichment_warning_count"], 0)

    def test_planner_composer_receives_dynamo_enriched_final_items(self) -> None:
        dynamo_lookup = RecordingDynamoLookup()
        runtime = PlannerCopyRuntime(
            {
                "structured_output": {
                    "item_copies": [
                        {
                            "item_ref": "item:0",
                            "title": "Dynamo 보강 산책지",
                            "body": "Dynamo 상세 설명을 바탕으로 작성한 본문입니다.",
                            "reason": "보강된 장소 설명이 요청과 맞습니다.",
                        },
                    ],
                    "recommendation_reasons": ["보강된 최종 배치 항목을 기준으로 추천했습니다."],
                    "itinerary_flow_reason": "보강된 최종 항목만 사용해 일정 흐름을 정리했습니다.",
                },
            },
        )

        output = PlannerAgent(
            dynamo_lookup=dynamo_lookup,
            explanation_runtime=runtime,
            schema_retry_limit=0,
        ).plan(reason_claim_package(), trip_type="daytrip")

        prompt_text = runtime.requests[0]["messages"][0]["content"][0]["text"]
        self.assertIn("Dynamo 상세 설명", prompt_text)
        self.assertEqual(output.itinerary[0]["title"], "Dynamo 보강 산책지")
        self.assertTrue(output.validation_result["planner_copy_generation_used_llm"])


if __name__ == "__main__":
    unittest.main()
