"""LangGraph composition root and local/live invocation harness.

This module is the application boundary for the Lovv recommendation workflow.
It converts the public API request into ``UnifiedAgentState``, injects model and
AWS-backed tools into graph nodes, invokes the compiled LangGraph, and returns
the public ``/recommendations`` response payload.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from lovv_agent.adapters.aws_clients import AwsClientFactory
from lovv_agent.adapters.aws_runtime import (
    AwsRuntimeAdapters,
    build_aws_runtime_adapters,
    require_agent_converse_runtime,
    require_embedding_adapter,
)
from lovv_agent.adapters.boto3_clients import create_boto3_client_factory
from lovv_agent.agents.candidate_evidence import CandidateEvidenceAgent
from lovv_agent.agents.festival_verifier import FestivalVerifierAgent
from lovv_agent.agents.intent import (
    IntentNormalizationResult,
    invoke_intent_structured_output,
    normalize_recommendation_request,
    resolve_execution_mode,
)
from lovv_agent.agents.planner import PlannerAgent
from lovv_agent.config import RuntimeConfig
from lovv_agent.graph import GraphNodeSet, build_langgraph, invoke_langgraph
from lovv_agent.models.schemas import CandidateEvidenceInput, GeoPoint, SchemaValidationError
from lovv_agent.prompts.registry import INTENT_NORMALIZATION_PROMPT_ID, prompt_text
from lovv_agent.state import IntentState, RequestState, UnifiedAgentState
from lovv_agent.telemetry import trace_invocation, trace_node

HARNESS_NAME = "LovvLangGraphHarness"


@dataclass(frozen=True, slots=True)
class LovvLangGraphHarness:
    """Compiled LangGraph plus its runtime-injected dependencies."""

    graph: Any
    config: RuntimeConfig
    adapters: AwsRuntimeAdapters

    def invoke(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str | None = None,
        graph_config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke the full graph from an API request and return public output."""

        final_state = self.invoke_state(
            payload,
            request_id=request_id,
            graph_config=graph_config,
        )
        if final_state.serving.response_payload is None:
            raise SchemaValidationError("graph completed without a response payload")
        return dict(final_state.serving.response_payload)

    def invoke_state(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str | None = None,
        graph_config: Mapping[str, Any] | None = None,
    ) -> UnifiedAgentState:
        """Invoke the full graph and return state for diagnostics/tests."""

        state = request_state_from_api(payload, request_id=request_id)
        return trace_invocation(
            state,
            lambda: invoke_langgraph(self.graph, state, config=graph_config),
        )


def build_live_harness(
    *,
    config: RuntimeConfig | None = None,
    client_factory: AwsClientFactory | None = None,
) -> LovvLangGraphHarness:
    """Build a live AWS-backed harness from injected or environment config."""

    # env config와 boto3 client를 함께 해석하는 유일한 live 경로다.
    resolved_config = RuntimeConfig.from_env() if config is None else config
    factory = client_factory or create_boto3_client_factory(
        profile_name=resolved_config.aws.profile_name,
    )
    adapters = build_aws_runtime_adapters(
        client_factory=factory,
        config=resolved_config,
    )
    return build_harness(config=resolved_config, adapters=adapters)


def build_harness(
    *,
    config: RuntimeConfig,
    adapters: AwsRuntimeAdapters,
) -> LovvLangGraphHarness:
    """Assemble real LangGraph nodes from injected runtime adapters."""

    # 추천 실행 중간이 아니라 harness 구성 단계에서 설정 오류를 드러낸다.
    embedding = require_embedding_adapter(adapters)
    # V1 routes model calls per agent while the Supervisor remains deterministic by default.
    intent_runtime = require_agent_converse_runtime(adapters, "intent")
    candidate_evidence_runtime = require_agent_converse_runtime(adapters, "candidate_evidence")
    planner_runtime = require_agent_converse_runtime(adapters, "planner")
    candidate_agent = CandidateEvidenceAgent(
        destination_search=adapters.tools.destination_search,
        dynamo_lookup=adapters.tools.dynamo_lookup,
        reason_claim_runtime=candidate_evidence_runtime,
        schema_retry_limit=config.retries.schema_retry_limit,
    )
    festival_agent = FestivalVerifierAgent()
    planner_agent = PlannerAgent(
        dynamo_lookup=adapters.tools.dynamo_lookup,
        explanation_runtime=planner_runtime,
        schema_retry_limit=config.retries.schema_retry_limit,
    )

    def intent_node(state: UnifiedAgentState) -> IntentState:
        # API가 소유한 field는 결정적 정규화 결과를 최종 기준으로 삼는다.
        api_payload = request_state_to_api(state.request)
        deterministic = normalize_recommendation_request(api_payload)
        if deterministic.needs_clarification:
            _apply_intent_clarification(state, deterministic)
            return _intent_state_from_result(deterministic)

        query = state.request.natural_language_query.strip()
        if len(query) < config.intent.min_natural_language_query_chars:
            state.trace.node_timings["intent_mode"] = "deterministic_short_query"
            return _intent_state_from_result(deterministic)

        llm_result = invoke_intent_structured_output(
            runtime=intent_runtime,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": json.dumps(
                                {
                                    "task": "API 입력을 Intent Agent 출력 계약으로 정규화하세요.",
                                    "api_structured_input": api_payload,
                                    "conversation_summary": (
                                        state.conversation.conversation_summary
                                    ),
                                    "messages": list(state.conversation.messages),
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                },
            ],
            structured_request=api_payload,
            retry_limit=config.retries.schema_retry_limit,
            system=[{"text": prompt_text(INTENT_NORMALIZATION_PROMPT_ID)}],
        )
        if _intent_llm_result_is_safe(llm_result, deterministic):
            state.trace.node_timings["intent_mode"] = "bedrock_structured_output"
            return _intent_state_from_result(
                _merge_llm_intent_enrichment(llm_result, deterministic),
                deterministic=deterministic,
            )

        # 자연어 보강은 선택 사항이다. 모델 계약이 실패하면 검증된 API core field를
        # 유지하고 결정적 경로로 계속 진행한다.
        state.trace.node_timings["intent_mode"] = "deterministic_llm_fallback"
        state.trace.node_timings["intent_llm_handoff_notes"] = list(
            llm_result.handoff_notes,
        )
        return _intent_state_from_result(deterministic)

    def candidate_node(state: UnifiedAgentState):
        candidate_input = state.intent.candidate_evidence_input
        if candidate_input is None:
            raise SchemaValidationError("candidate_evidence_input is required")
        # 주 embedding은 cleaned_raw_query(없으면 soft/themes)로 retrieval을 구동한다.
        query_text = _embedding_query(candidate_input)
        query_vector = embedding.embed_query(query_text)
        # soft preference가 별도로 있으면 두 번째 embedding으로 soft 검색 채널을 만든다.
        # ScoringTool이 soft_distance로 soft_similarity를 가산한다.
        soft_text = candidate_input.soft_preference_query.strip()
        soft_query_vector = (
            embedding.embed_query(soft_text)
            if soft_text and soft_text != query_text
            else None
        )
        return candidate_agent.run(
            candidate_input,
            query_vector=query_vector,
            soft_query_vector=soft_query_vector,
        )

    def festival_node(state: UnifiedAgentState):
        verifier_input = festival_agent.build_input(
            include_festivals=state.request.include_festivals,
            travel_year=state.request.travel_year,
            travel_month=state.request.travel_month,
            candidate_evidence_package=state.evidence.candidate_evidence_package,
        )
        return festival_agent.verify(verifier_input).verifications

    def planner_node(state: UnifiedAgentState):
        package = state.evidence.candidate_evidence_package
        if package is None:
            raise SchemaValidationError("candidate evidence package is required")
        return planner_agent.plan(
            package,
            trip_type=state.request.trip_type,
            include_festivals=state.request.include_festivals,
            festival_verifications=state.festival.festival_verifications,
        )

    graph = build_langgraph(
        GraphNodeSet(
            intent=trace_node("intent_agent", intent_node),
            candidate_evidence=trace_node("candidate_evidence_agent", candidate_node),
            festival_verifier=trace_node("festival_verifier_agent", festival_node),
            planner=trace_node("planner_agent", planner_node),
        ),
    )
    return LovvLangGraphHarness(graph=graph, config=config, adapters=adapters)


def request_state_from_api(
    payload: Mapping[str, Any],
    *,
    request_id: str | None = None,
) -> UnifiedAgentState:
    """Convert the public recommendations request into graph state."""

    if not isinstance(payload, Mapping):
        raise SchemaValidationError("recommendations payload must be a mapping")
    # harness smoke 실행을 위해 public camelCase와 내부 snake_case를 모두 허용한다.
    user_location = payload.get("userLocation", payload.get("user_location"))
    natural_query = payload.get("naturalLanguageQuery", "")
    if natural_query is None:
        natural_query = ""
    state = UnifiedAgentState(
        request=RequestState(
            request_id=(
                request_id
                or _optional_text(payload.get("requestId"))
                or f"rec-{uuid.uuid4()}"
            ),
            entry_type=_required_text(payload.get("entryType"), "entryType"),
            country=_required_text(payload.get("country"), "country"),
            travel_year=_required_int(payload.get("travelYear", 2026), "travelYear"),
            travel_month=_required_int(payload.get("travelMonth"), "travelMonth"),
            trip_type=_required_text(payload.get("tripType"), "tripType"),
            destination_id=_optional_text(payload.get("destinationId")),
            themes=_string_tuple(payload.get("themes"), "themes"),
            include_festivals=_required_bool(
                payload.get("includeFestivals"),
                "includeFestivals",
            ),
            natural_language_query=_free_text(natural_query, "naturalLanguageQuery"),
            user_location=(
                GeoPoint.from_mapping(user_location)
                if user_location is not None
                else None
            ),
        ),
    )
    state.trace.recommendation_request_id = state.request.request_id
    state.trace.agent_run_id = f"run-{uuid.uuid4()}"
    return state


def request_state_to_api(request: RequestState) -> dict[str, Any]:
    """Return the API-shaped request used by Intent normalization."""

    return {
        "entryType": request.entry_type,
        "destinationId": request.destination_id,
        "country": request.country,
        "travelYear": request.travel_year,
        "travelMonth": request.travel_month,
        "tripType": request.trip_type,
        "themes": list(request.themes),
        "includeFestivals": request.include_festivals,
        "naturalLanguageQuery": request.natural_language_query,
        "userLocation": (
            None
            if request.user_location is None
            else {
                "latitude": request.user_location.latitude,
                "longitude": request.user_location.longitude,
            }
        ),
    }


def _intent_state_from_result(
    result: IntentNormalizationResult,
    *,
    deterministic: IntentNormalizationResult | None = None,
) -> IntentState:
    """Convert Intent normalization output into the canonical state group."""

    base = deterministic or result
    return IntentState(
        extracted_inputs=result.extracted_inputs,
        active_required_themes=result.active_required_themes,
        searchable_place_themes=base.searchable_place_themes,
        external_link_themes=base.external_link_themes,
        cleaned_raw_query=result.cleaned_raw_query,
        soft_preference_query=result.soft_preference_query,
        unsupported_conditions=result.unsupported_conditions,
        candidate_evidence_input=result.candidate_evidence_input,
    )


def _apply_intent_clarification(
    state: UnifiedAgentState,
    result: IntentNormalizationResult,
) -> None:
    """Copy deterministic Intent clarification into Supervisor routing state."""

    state.routing.needs_clarification = result.needs_clarification
    state.routing.clarifying_question = result.clarifying_question


def _merge_llm_intent_enrichment(
    llm_result: IntentNormalizationResult,
    deterministic: IntentNormalizationResult,
) -> IntentNormalizationResult:
    """Merge only model-derived natural-language signals into trusted core input."""

    trusted_candidate = deterministic.candidate_evidence_input
    if trusted_candidate is None:
        return deterministic
    mode = resolve_execution_mode(
        trusted_candidate.destination_id,
        trusted_candidate.include_festivals,
    )
    # 모델은 이제 NL 신호만 top-level로 반환한다. deterministic을 기반으로 그 3개만 덮는다.
    merged_candidate = replace(
        trusted_candidate,
        cleaned_raw_query=llm_result.cleaned_raw_query,
        soft_preference_query=llm_result.soft_preference_query,
        unsupported_conditions=llm_result.unsupported_conditions,
        execution_mode=mode,
        fixed_city_id=(
            trusted_candidate.destination_id
            if mode == "anchored_place_search"
            else None
        ),
    )
    return replace(
        deterministic,
        candidate_evidence_input=merged_candidate,
        cleaned_raw_query=merged_candidate.cleaned_raw_query,
        soft_preference_query=merged_candidate.soft_preference_query,
        unsupported_conditions=merged_candidate.unsupported_conditions,
        handoff_notes=deterministic.handoff_notes + llm_result.handoff_notes,
    )


def _intent_llm_result_is_safe(
    llm_result: IntentNormalizationResult,
    deterministic: IntentNormalizationResult,
) -> bool:
    """Accept LLM enrichment only when it preserves deterministic core fields."""

    # 모델이 더 이상 core 필드를 내보내지 않으므로 override가 구조적으로 불가능하다.
    # 안전성은 "clarification 요청이 아니고 deterministic candidate가 있다"로 충분하다.
    if llm_result.needs_clarification:
        return False
    return deterministic.candidate_evidence_input is not None


def _embedding_query(candidate_input: CandidateEvidenceInput) -> str:
    """Build one non-empty query text for live embedding generation."""

    for value in (
        candidate_input.cleaned_raw_query,
        candidate_input.soft_preference_query,
        " ".join(candidate_input.active_required_themes),
    ):
        if value.strip():
            return value.strip()
    raise SchemaValidationError("embedding query cannot be empty")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError("optional text must be a string or null")
    return value.strip() or None


def _free_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    return value.strip()


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    return value


def _required_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a boolean")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    return tuple(_required_text(item, field_name) for item in value)


__all__ = [
    "HARNESS_NAME",
    "LovvLangGraphHarness",
    "build_harness",
    "build_live_harness",
    "request_state_from_api",
    "request_state_to_api",
]
