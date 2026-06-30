"""Tests for Intent Agent deterministic request normalization."""

from __future__ import annotations

import json
import unittest

from lovv_agent.agents.intent import (
    build_intent_structured_output_request,
    extract_natural_language_query,
    invoke_intent_structured_output,
    map_theme_ids,
    normalize_recommendation_request,
    resolve_execution_mode,
)
from lovv_agent.models.schemas import SchemaValidationError


def _base_request() -> dict[str, object]:
    """Return a valid MVP recommendation request sample."""

    return {
        "entryType": "chat",
        "destinationId": None,
        "country": "KR",
        "travelYear": 2026,
        "travelMonth": 10,
        "tripType": "2d1n",
        "themes": ["sea_coast", "food_local"],
        "includeFestivals": False,
        "naturalLanguageQuery": "일본 말고 조용한 바다도 보고 싶어요",
        "userLocation": {
            "latitude": 37.5665,
            "longitude": 126.978,
        },
    }


def _intent_structured_output_payload() -> dict[str, object]:
    """Return a valid model-like Intent structured output payload (6 NL fields)."""

    return {
        "needs_clarification": False,
        "clarifying_question": None,
        "cleaned_raw_query": "조용한 바다 산책",
        "soft_preference_query": "조용한 분위기",
        "unsupported_conditions": [],
        "handoff_notes": [],
    }


class FakeStructuredRuntime:
    """Small injected runtime for retry and response-shape tests."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def __call__(self, request: dict[str, object]) -> object:
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


class IntentNormalizationTest(unittest.TestCase):
    """Validate Task 2.1 structured input and theme mapping behavior."""

    def test_normalization_preserves_api_core_fields(self) -> None:
        result = normalize_recommendation_request(_base_request())

        self.assertFalse(result.needs_clarification)
        self.assertIsNone(result.clarifying_question)
        self.assertIsNotNone(result.candidate_evidence_input)

        candidate_input = result.candidate_evidence_input
        assert candidate_input is not None
        self.assertEqual(candidate_input.country, "KR")
        self.assertEqual(candidate_input.travel_year, 2026)
        self.assertEqual(candidate_input.travel_month, 10)
        self.assertEqual(candidate_input.trip_type, "2d1n")
        self.assertIsNone(candidate_input.destination_id)
        self.assertFalse(candidate_input.include_festivals)
        self.assertIn("바다", candidate_input.cleaned_raw_query)
        self.assertIn("조용", candidate_input.soft_preference_query)
        self.assertEqual(candidate_input.unsupported_conditions, ())
        self.assertEqual(candidate_input.user_location.latitude, 37.5665)

    def test_theme_mapping_splits_searchable_and_external_link_labels(self) -> None:
        result = normalize_recommendation_request(_base_request())

        self.assertEqual(result.active_required_themes, ("바다·해안", "미식·노포"))
        self.assertEqual(result.searchable_place_themes, ("바다·해안",))
        self.assertEqual(result.external_link_themes, ("미식·노포",))
        self.assertEqual(
            result.candidate_evidence_input.active_required_themes,
            ("바다·해안", "미식·노포"),
        )

    def test_include_festivals_controls_mode_not_theme_labels(self) -> None:
        request = _base_request()
        request["themes"] = ["history_tradition"]
        request["includeFestivals"] = True

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.active_required_themes, ("역사·전통",))
        self.assertEqual(result.fulfilled_matrix["festival"], "X")
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "festival_seeded_city_discovery",
        )
        self.assertTrue(result.candidate_evidence_input.include_festivals)

    def test_destination_id_sets_anchored_mode_and_preserves_festival_choice(self) -> None:
        request = _base_request()
        request["entryType"] = "map_marker"
        request["destinationId"] = "city-123"
        request["includeFestivals"] = True

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "anchored_place_search",
        )
        self.assertEqual(result.candidate_evidence_input.fixed_city_id, "city-123")
        self.assertTrue(result.candidate_evidence_input.include_festivals)

    def test_user_location_accepts_snake_case_boundary_input(self) -> None:
        request = _base_request()
        request.pop("userLocation")
        request["user_location"] = {
            "latitude": 35.1796,
            "longitude": 129.0756,
        }

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.candidate_evidence_input.user_location.latitude, 35.1796)
        self.assertEqual(
            result.extracted_inputs["user_location"],
            {"latitude": 35.1796, "longitude": 129.0756},
        )

    def test_legacy_festival_theme_is_not_an_active_required_theme(self) -> None:
        request = _base_request()
        request["themes"] = ["festival_event", "sea_coast"]
        request["includeFestivals"] = False

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertTrue(result.candidate_evidence_input.include_festivals)
        self.assertEqual(result.active_required_themes, ("바다·해안",))
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "festival_seeded_city_discovery",
        )
        self.assertIn("legacy festival theme", result.handoff_notes[0])

    def test_legacy_festival_theme_alone_requires_travel_theme(self) -> None:
        request = _base_request()
        request["themes"] = ["festival_event"]

        result = normalize_recommendation_request(request)

        self.assertTrue(result.needs_clarification)
        self.assertIsNone(result.candidate_evidence_input)
        self.assertIn("at least one canonical travel theme", result.clarifying_question)

    def test_map_marker_without_destination_needs_clarification(self) -> None:
        request = _base_request()
        request["entryType"] = "map_marker"
        request["destinationId"] = None

        result = normalize_recommendation_request(request)

        self.assertTrue(result.needs_clarification)
        self.assertIn("destinationId is required", result.clarifying_question)

    def test_unknown_theme_needs_clarification(self) -> None:
        request = _base_request()
        request["themes"] = ["sea_coast", "unknown_theme"]

        result = normalize_recommendation_request(request)

        self.assertTrue(result.needs_clarification)
        self.assertIn("unsupported canonical theme", result.clarifying_question)

    def test_theme_mapping_rejects_non_boolean_festival_flag(self) -> None:
        with self.assertRaises(SchemaValidationError):
            map_theme_ids(["sea_coast"], include_festivals="false")

    def test_execution_mode_resolution(self) -> None:
        self.assertEqual(resolve_execution_mode(None, False), "city_discovery")
        self.assertEqual(
            resolve_execution_mode(None, True),
            "festival_seeded_city_discovery",
        )
        self.assertEqual(
            resolve_execution_mode("city-1", False),
            "anchored_place_search",
        )

    def test_raw_soft_query_extraction_preserves_searchable_intent(self) -> None:
        request = _base_request()
        request["naturalLanguageQuery"] = (
            "바다를 보면서 산책하고 싶어요. 조용하고 덜 붐비는 분위기가 좋아요."
        )

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertIn("바다", result.cleaned_raw_query)
        self.assertIn("산책", result.cleaned_raw_query)
        self.assertIn("조용", result.soft_preference_query)
        self.assertIn("덜 붐비", result.soft_preference_query)
        self.assertEqual(result.candidate_evidence_input.cleaned_raw_query, result.cleaned_raw_query)
        self.assertEqual(
            result.candidate_evidence_input.soft_preference_query,
            result.soft_preference_query,
        )

    def test_unsupported_conditions_are_separated_from_raw_query(self) -> None:
        request = _base_request()
        request["naturalLanguageQuery"] = (
            "바다 산책을 하고 싶어요. 실시간 혼잡도랑 숙소 가격도 알려주세요."
        )

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertIn("바다 산책", result.cleaned_raw_query)
        self.assertNotIn("실시간 혼잡도", result.cleaned_raw_query)
        self.assertIn("실시간 혼잡도", result.unsupported_conditions)
        self.assertIn("숙소 가격/예약 가능 여부", result.unsupported_conditions)

    def test_raw_soft_short_natural_language_query_skips_extraction(self) -> None:
        request = _base_request()
        request["naturalLanguageQuery"] = "바다"

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.cleaned_raw_query, "")
        self.assertEqual(result.soft_preference_query, "")
        self.assertEqual(result.unsupported_conditions, ())
        self.assertEqual(result.candidate_evidence_input.cleaned_raw_query, "")

    def test_conflict_signals_are_recorded_without_overriding_core_fields(self) -> None:
        request = _base_request()
        request["country"] = "KR"
        request["travelMonth"] = 10
        request["tripType"] = "2d1n"
        request["includeFestivals"] = False
        request["naturalLanguageQuery"] = "일본으로 바꿔줘. 11월 당일치기로 축제도 포함해줘."

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.candidate_evidence_input.country, "KR")
        self.assertEqual(result.candidate_evidence_input.travel_month, 10)
        self.assertEqual(result.candidate_evidence_input.trip_type, "2d1n")
        self.assertFalse(result.candidate_evidence_input.include_festivals)
        self.assertIn("country change to JP", " ".join(result.handoff_notes))
        self.assertIn("travelMonth different", " ".join(result.handoff_notes))
        self.assertIn("tripType different", " ".join(result.handoff_notes))
        self.assertIn("festival inclusion", " ".join(result.handoff_notes))

    def test_extractor_uses_configurable_short_query_threshold(self) -> None:
        extraction = extract_natural_language_query(
            "바다 산책",
            structured_request={
                "country": "KR",
                "travelMonth": 10,
                "tripType": "2d1n",
                "includeFestivals": False,
            },
            min_natural_language_query_chars=10,
        )

        self.assertTrue(extraction.skipped)
        self.assertEqual(extraction.cleaned_raw_query, "")

    def test_structured_output_request_uses_json_schema_text_format(self) -> None:
        request = build_intent_structured_output_request(
            messages=[{"role": "user", "content": [{"text": "정규화해줘"}]}],
        )

        text_format = request["outputConfig"]["textFormat"]
        self.assertEqual(text_format["type"], "json_schema")
        self.assertEqual(
            text_format["structure"]["jsonSchema"]["name"],
            "intent_agent_output",
        )
        schema_text = text_format["structure"]["jsonSchema"]["schema"]
        self.assertIsInstance(schema_text, str)
        self.assertEqual(json.loads(schema_text)["type"], "object")

    def test_structured_output_adapter_accepts_tool_output_style(self) -> None:
        payload = _intent_structured_output_payload()
        runtime = FakeStructuredRuntime(
            [
                {
                    "output": {
                        "message": {
                            "content": [
                                {
                                    "toolUse": {
                                        "name": "emit_intent_agent_output",
                                        "input": payload,
                                    },
                                },
                            ],
                        },
                    },
                },
            ],
        )

        result = invoke_intent_structured_output(
            runtime=runtime,
            messages=[{"role": "user", "content": [{"text": "정규화해줘"}]}],
            structured_request=_base_request(),
            retry_limit=0,
        )

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.cleaned_raw_query, "조용한 바다 산책")

    def test_structured_output_adapter_recovers_valid_inner_json_object(self) -> None:
        payload = _intent_structured_output_payload()
        malformed_wrapper = '{\n  "{\n' + json.dumps(payload, ensure_ascii=False) + "\n}"
        runtime = FakeStructuredRuntime(
            [{"output": {"message": {"content": [{"text": malformed_wrapper}]}}}],
        )

        result = invoke_intent_structured_output(
            runtime=runtime,
            messages=[{"role": "user", "content": [{"text": "정규화해줘"}]}],
            structured_request=_base_request(),
            retry_limit=0,
        )

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.cleaned_raw_query, "조용한 바다 산책")

    def test_structured_output_retry_accepts_second_valid_payload(self) -> None:
        payload = _intent_structured_output_payload()
        runtime = FakeStructuredRuntime(
            [
                "not valid json",
                {"structured_output": payload},
            ],
        )

        result = invoke_intent_structured_output(
            runtime=runtime,
            messages=[{"role": "user", "content": [{"text": "정규화해줘"}]}],
            structured_request=_base_request(),
            retry_limit=1,
        )

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.cleaned_raw_query, "조용한 바다 산책")
        self.assertEqual(len(runtime.calls), 2)

    def test_schema_failure_returns_safe_fallback_after_retries(self) -> None:
        runtime = FakeStructuredRuntime(
            [
                {"structured_output": {"needs_clarification": "no"}},
                {"structured_output": {"needs_clarification": "still no"}},
            ],
        )

        result = invoke_intent_structured_output(
            runtime=runtime,
            messages=[{"role": "user", "content": [{"text": "정규화해줘"}]}],
            structured_request=_base_request(),
            retry_limit=1,
        )

        self.assertTrue(result.needs_clarification)
        self.assertIsNone(result.candidate_evidence_input)
        self.assertIn("intent_structured_output_schema_failure", result.handoff_notes)
        self.assertEqual(len(runtime.calls), 2)

    def test_fixture_like_autumn_festival_chat_case(self) -> None:
        """Translate the legacy chatbot fixture into the current API contract."""

        request = {
            "entryType": "chat",
            "destinationId": None,
            "country": "KR",
            "travelMonth": 10,
            "travelYear": 2026,
            "themes": ["nature_trekking"],
            "tripType": "2d1n",
            "includeFestivals": True,
            "naturalLanguageQuery": "가을에 단풍 구경하기 좋은 조용한 경상북도 소도시 추천해줘",
            "userLocation": {"latitude": 36.5760, "longitude": 128.5056},
        }

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.active_required_themes, ("자연·트레킹",))
        self.assertEqual(result.searchable_place_themes, ("자연·트레킹",))
        self.assertEqual(result.external_link_themes, ())
        self.assertEqual(result.fulfilled_matrix["festival"], "X")
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "festival_seeded_city_discovery",
        )
        self.assertIn("단풍", result.cleaned_raw_query)
        self.assertIn("조용", result.soft_preference_query)

    def test_fixture_like_anchored_map_marker_case(self) -> None:
        """Translate the legacy map marker fixture into anchored_place_search."""

        request = {
            "entryType": "map_marker",
            "destinationId": "KR-Cheongsong",
            "country": "KR",
            "travelMonth": 11,
            "travelYear": 2026,
            "themes": ["nature_trekking", "healing_rest"],
            "tripType": "3d2n",
            "includeFestivals": False,
            "naturalLanguageQuery": "",
            "userLocation": None,
        }

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(
            result.active_required_themes,
            ("자연·트레킹", "온천·휴양"),
        )
        self.assertEqual(
            result.searchable_place_themes,
            ("자연·트레킹", "온천·휴양"),
        )
        self.assertEqual(result.fulfilled_matrix["festival"], "N/A")
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "anchored_place_search",
        )
        self.assertEqual(result.candidate_evidence_input.fixed_city_id, "KR-Cheongsong")
        self.assertEqual(result.cleaned_raw_query, "")
        self.assertEqual(result.soft_preference_query, "")

    def test_fixture_like_gourmet_healing_festival_case(self) -> None:
        """Translate the legacy personalized fixture into current theme IDs."""

        request = {
            "entryType": "chat",
            "destinationId": None,
            "country": "KR",
            "travelMonth": 12,
            "travelYear": 2026,
            "themes": ["healing_rest", "food_local"],
            "tripType": "2d1n",
            "includeFestivals": True,
            "naturalLanguageQuery": "온천할 수 있고 맛있는 음식 먹을 수 있는 곳으로 추천해줘",
            "userLocation": {"latitude": 37.5665, "longitude": 126.9780},
        }

        result = normalize_recommendation_request(request)

        self.assertFalse(result.needs_clarification)
        self.assertEqual(
            result.active_required_themes,
            ("온천·휴양", "미식·노포"),
        )
        self.assertEqual(result.searchable_place_themes, ("온천·휴양",))
        self.assertEqual(result.external_link_themes, ("미식·노포",))
        self.assertTrue(result.candidate_evidence_input.include_festivals)
        self.assertEqual(
            result.candidate_evidence_input.execution_mode,
            "festival_seeded_city_discovery",
        )
        self.assertIn("온천", result.cleaned_raw_query)
        self.assertIn("맛있는 음식", result.cleaned_raw_query)


if __name__ == "__main__":
    unittest.main()
