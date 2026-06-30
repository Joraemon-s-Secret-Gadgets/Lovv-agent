from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from lovv_agent_v2.agents.response_packager.explain_itinerary import (
    ItineraryExplanationRuntime,
    explain_itinerary_node,
)
from lovv_agent_v2.agents.response_packager.planner_copy_composer import (
    validate_planner_copy_explanation_output,
)
from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.models.schemas import PlannerOutput


class PlannerCopyRuntime:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        return self.response


class RecordingDynamoLookup:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def enrich_final_places(self, final_places: tuple[Any, ...]) -> Any:
        self.calls.append(final_places)
        enriched = tuple(
            replace(
                place,
                details={"overview": f"{place.title} 공개 개요입니다."},
            )
            for place in final_places
        )
        return DetailResult(enriched)


class DetailResult:
    def __init__(self, places: tuple[Any, ...]) -> None:
        self.places = places
        self.warnings: tuple[Any, ...] = ()


def _planner_output() -> dict[str, Any]:
    return PlannerOutput(
        itinerary=(
            {
                "day": 1,
                "slot": "morning",
                "item_type": "attraction",
                "placeId": "P-1",
                "title": "해변",
                "body": "바다·해안 조건과 도시 내 동선을 함께 고려한 방문지입니다.",
                "reason": "요청 분위기와 테마가 함께 맞아 작업셋에 포함했습니다.",
                "moveMinutes": 0,
                "latitude": 38.2,
                "longitude": 128.6,
                "city_id": "KR-SOKCHO",
                "city_name_ko": "속초",
                "theme_tags": ("바다·해안",),
                "source": "s3_vector",
                "ddb_pk": "CITY#SOKCHO",
                "ddb_sk": "PLACE#P-1",
                "reason_code": "soft_theme_gate",
                "evidence": {"themes": ("바다·해안",)},
            },
        ),
        recommendation_reasons=("속초 안에서 바다·해안 균형을 우선했습니다.",),
        itinerary_flow_reason="도시 내 후보를 1개 일자 클러스터로 나누었습니다.",
        external_links={},
        confidence=0.76,
        user_notice=(),
        validation_result={"planner_status_gate": "ok"},
        alternative_itinerary=(),
    ).to_dict()


def _state(runtime: ItineraryExplanationRuntime) -> dict[str, Any]:
    return {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "속초 바다 산책",
                "soft_preference_query": "조용한 해안",
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-SOKCHO",
                    "city_name_ko": "속초",
                    "country": "KR",
                    "selection_reason_code": ("theme_city_match",),
                },
            },
        },
        "planner": {"planner_output": _planner_output(), "audit": {"subgraph": "planner"}},
        "itinerary_explanation_runtime": runtime,
    }


def test_explain_itinerary_node_uses_v1_composer_with_enriched_v2_items() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:0",
                        "title": "잔잔한 속초 해변",
                        "body": "해변 공개 개요를 바탕으로 오전 산책에 맞췄습니다.",
                        "reason": "조용한 해안 선호와 직접 맞습니다.",
                    },
                ],
                "recommendation_reasons": ["속초의 해안 산책 요청에 맞춰 구성했습니다."],
                "itinerary_flow_reason": "오전 해변 산책으로 시작하는 흐름입니다.",
            },
        },
    )
    dynamo_lookup = RecordingDynamoLookup()

    result = explain_itinerary_node(
        _state(
            ItineraryExplanationRuntime(
                explanation_runtime=runtime,
                dynamo_lookup=dynamo_lookup,
                schema_retry_limit=0,
            ),
        ),
    )

    output = result["planner"]["planner_output"]
    item = output["itinerary"][0]
    assert item["title"] == "잔잔한 속초 해변"
    assert item["copy_source"] == "llm_planner_copy"
    assert output["recommendation_reasons"] == ("속초의 해안 산책 요청에 맞춰 구성했습니다.",)
    assert output["validation_result"]["planner_copy_generation_used_llm"] is True
    assert "해변 공개 개요입니다." in runtime.requests[0]["messages"][0]["content"][0]["text"]
    system_prompt = json.loads(runtime.requests[0]["system"][0]["text"])
    assert system_prompt["artifact"] == "planner_copy_explanation"
    assert system_prompt["grounding_policy"]["itinerary_scope"] == "final_itinerary_only"
    assert dynamo_lookup.calls[0][0].ddb_pk == "CITY#SOKCHO"


def test_explain_itinerary_node_falls_back_when_v1_composer_rejects_copy() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:0",
                        "title": "top_k 점수 추천",
                        "body": "점수 기준입니다.",
                        "reason": "top_k 때문입니다.",
                    },
                ],
                "recommendation_reasons": ["내부 점수 기준입니다."],
                "itinerary_flow_reason": "점수 기준입니다.",
            },
        },
    )

    result = explain_itinerary_node(
        _state(ItineraryExplanationRuntime(explanation_runtime=runtime, schema_retry_limit=0)),
    )

    output = result["planner"]["planner_output"]
    item = output["itinerary"][0]
    assert item["title"] == "해변"
    assert output["recommendation_reasons"] == ("속초 안에서 바다·해안 균형을 우선했습니다.",)
    assert output["validation_result"]["planner_copy_generation_used_llm"] is False
    assert "schema_failure" in output["explanation_audit"]["hidden_internal_notes"][-1]


def test_planner_copy_rejects_internal_seed_cluster_and_relevance_terms() -> None:
    payload = {
        "item_copies": [
            {
                "item_ref": "item:0",
                "title": "해변",
                "body": "seed 장소라 추천합니다.",
                "reason": "cluster와 relevance 기준입니다.",
            },
        ],
        "recommendation_reasons": ["seed 보존을 우선했습니다."],
        "itinerary_flow_reason": "cluster 기준으로 묶었습니다.",
    }

    try:
        validate_planner_copy_explanation_output(payload, allowed_item_refs=("item:0",))
    except SchemaValidationError:
        return
    raise AssertionError("internal planner terms must be rejected")
