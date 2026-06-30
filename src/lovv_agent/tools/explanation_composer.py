"""Prompt-backed Planner copy and explanation composer.

This tool owns the structured LLM contract for user-facing Planner copy. It
receives only public-safe final itinerary summaries and approved reason claims,
then returns schema-validated copy. If the LLM output is malformed or unsafe,
callers can keep deterministic fallback copy without changing selected evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent.adapters.bedrock_converse import (
    RuntimeInvoker,
    build_structured_converse_request,
    invoke_structured_output,
)
from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    ExplanationReasonRef,
    PlannerExplanationAudit,
    SchemaValidationError,
)
from lovv_agent.prompts.registry import (
    PLANNER_COPY_EXPLANATION_PROMPT_ID,
    prompt_text,
)

TOOL_NAME = "PlannerExplanationComposer"

RESPONSIBILITY = "Generate schema-validated Planner copy from safe final summaries."

PLANNER_COPY_EXPLANATION_SCHEMA_NAME = "planner_copy_explanation_output"

# LLM은 이 제한된 schema 안에서만 문구를 개선할 수 있다.
PLANNER_COPY_EXPLANATION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["item_copies", "recommendation_reasons", "itinerary_flow_reason"],
    "properties": {
        "item_copies": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item_ref", "title", "body", "reason"],
                "properties": {
                    "item_ref": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "recommendation_reasons": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {"type": "string"},
        },
        "itinerary_flow_reason": {"type": "string"},
    },
}

INTERNAL_EXPLANATION_TERMS = (
    # audit 용어는 내부적으로만 유용하며 사용자에게 노출되면 안 된다.
    "top k",
    "top_k",
    "topk",
    "점수",
    "스코어",
    "랭킹 공식",
    "ranking formula",
    "raw retrieval",
    "score audit",
    "dynamodb",
    "s3 vector",
)


@dataclass(frozen=True, slots=True)
class PlannerCopyExplanation:
    """Validated Planner copy/explanation result."""

    itinerary: tuple[dict[str, Any], ...]
    recommendation_reasons: tuple[str, ...]
    itinerary_flow_reason: str
    explanation_audit: PlannerExplanationAudit
    used_llm: bool


def build_planner_copy_explanation_request(
    package: CandidateEvidencePackage,
    *,
    itinerary: Sequence[Mapping[str, Any]],
    validation_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the schema-enforced Planner copy/explanation request."""

    safe_summary = build_planner_copy_safe_summary(
        package,
        itinerary=itinerary,
        validation_result=validation_result,
    )
    return build_structured_converse_request(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": json.dumps(safe_summary, ensure_ascii=False),
                    },
                ],
            },
        ],
        system=[
            {
                "text": prompt_text(PLANNER_COPY_EXPLANATION_PROMPT_ID),
            },
        ],
        schema_name=PLANNER_COPY_EXPLANATION_SCHEMA_NAME,
        schema=PLANNER_COPY_EXPLANATION_OUTPUT_SCHEMA,
        schema_description="Lovv Planner Korean copy and explanation output",
        reasoning_effort="low",
    )


def build_planner_copy_safe_summary(
    package: CandidateEvidencePackage,
    *,
    itinerary: Sequence[Mapping[str, Any]],
    validation_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the public-safe prompt input for Planner copy generation."""

    if package.selected_city is None:
        raise SchemaValidationError("selected_city is required for Planner copy prompt")
    return {
        "selected_city": {
            "city_id": package.selected_city.city_id,
            "city_name_ko": package.selected_city.city_name_ko,
            "country": package.selected_city.country,
            "selection_reason_code": list(package.selected_city.selection_reason_code),
        },
        "query": _query_summary(package),
        "final_itinerary_items": [
            _item_prompt_summary(index, item) for index, item in enumerate(itinerary)
        ],
        "candidate_reason_claims": [
            {
                "claim_id": claim.claim_id,
                "scope": claim.scope,
                "text_ko": claim.text_ko,
                "evidence_refs": list(claim.evidence_refs),
                "required_place_ids": list(claim.required_place_ids),
                "public_eligible": claim.public_eligible,
            }
            for claim in package.candidate_reason_claims
            if claim.public_eligible
        ],
        "verified_festivals": [
            _festival_prompt_summary(item)
            for item in itinerary
            if item.get("item_type") == "festival"
        ],
        "validation_result": _validation_prompt_summary(validation_result),
        "copy_rules": {
            "do_not_create_new_places": True,
            "do_not_create_named_restaurants": True,
            "do_not_expose_internal_scores": True,
        },
    }


def compose_planner_copy_explanation(
    package: CandidateEvidencePackage,
    *,
    itinerary: Sequence[Mapping[str, Any]],
    validation_result: Mapping[str, Any],
    runtime: RuntimeInvoker,
    retry_limit: int,
    fallback_recommendation_reasons: Sequence[str],
    fallback_itinerary_flow_reason: str,
    fallback_explanation_audit: PlannerExplanationAudit,
) -> PlannerCopyExplanation:
    """Invoke an LLM composer and return validated copy or fallback copy."""

    item_refs = _itinerary_item_refs(itinerary)
    request = build_planner_copy_explanation_request(
        package,
        itinerary=itinerary,
        validation_result=validation_result,
    )
    result = invoke_structured_output(
        runtime=runtime,
        request=request,
        retry_limit=retry_limit,
        validator=lambda payload: validate_planner_copy_explanation_output(
            payload,
            allowed_item_refs=item_refs,
        ),
    )
    if not result.ok:
        return PlannerCopyExplanation(
            itinerary=tuple(dict(item) for item in itinerary),
            recommendation_reasons=tuple(fallback_recommendation_reasons),
            itinerary_flow_reason=fallback_itinerary_flow_reason,
            explanation_audit=_append_hidden_note(
                fallback_explanation_audit,
                f"planner_copy_generation:schema_failure:{result.attempts}",
            ),
            used_llm=False,
        )

    generated = result.value
    updated_itinerary = _apply_item_copies(itinerary, generated["item_copies"])
    audit = _generated_explanation_audit(
        package,
        itinerary=updated_itinerary,
        recommendation_reasons=generated["recommendation_reasons"],
        base_audit=fallback_explanation_audit,
    )
    return PlannerCopyExplanation(
        itinerary=updated_itinerary,
        recommendation_reasons=tuple(generated["recommendation_reasons"]),
        itinerary_flow_reason=generated["itinerary_flow_reason"],
        explanation_audit=audit,
        used_llm=True,
    )


def validate_planner_copy_explanation_output(
    payload: Mapping[str, Any],
    *,
    allowed_item_refs: Sequence[str],
) -> dict[str, Any]:
    """Validate model-produced Planner copy before it enters graph state."""

    if not isinstance(payload, Mapping):
        raise SchemaValidationError("planner copy output must be an object")
    if set(payload) != {"item_copies", "recommendation_reasons", "itinerary_flow_reason"}:
        raise SchemaValidationError("planner copy output contains unsupported fields")

    allowed_refs = set(allowed_item_refs)
    raw_item_copies = payload["item_copies"]
    if not isinstance(raw_item_copies, (list, tuple)):
        raise SchemaValidationError("item_copies must be a list")
    item_copies = tuple(_validate_item_copy(item, allowed_refs) for item in raw_item_copies)

    raw_reasons = payload["recommendation_reasons"]
    if not isinstance(raw_reasons, (list, tuple)) or not raw_reasons:
        raise SchemaValidationError("recommendation_reasons must be a non-empty list")
    if len(raw_reasons) > 3:
        raise SchemaValidationError("recommendation_reasons must contain at most 3 items")
    reasons = tuple(_safe_public_text(item, "recommendation_reasons") for item in raw_reasons)

    flow_reason = _safe_public_text(payload["itinerary_flow_reason"], "itinerary_flow_reason")
    return {
        "item_copies": item_copies,
        "recommendation_reasons": reasons,
        "itinerary_flow_reason": flow_reason,
    }


def _validate_item_copy(item: Any, allowed_refs: set[str]) -> dict[str, str]:
    """Validate one generated itinerary item copy block."""

    if not isinstance(item, Mapping):
        raise SchemaValidationError("item_copies item must be an object")
    if set(item) != {"item_ref", "title", "body", "reason"}:
        raise SchemaValidationError("item_copies item contains unsupported fields")
    item_ref = _safe_public_text(item["item_ref"], "item_ref")
    if item_ref not in allowed_refs:
        raise SchemaValidationError(f"unknown item_ref: {item_ref}")
    return {
        "item_ref": item_ref,
        "title": _safe_public_text(item["title"], "title"),
        "body": _safe_public_text(item["body"], "body"),
        "reason": _safe_public_text(item["reason"], "reason"),
    }


def _apply_item_copies(
    itinerary: Sequence[Mapping[str, Any]],
    item_copies: Sequence[Mapping[str, str]],
) -> tuple[dict[str, Any], ...]:
    """Apply generated title/body/reason copy to matching final items."""

    copies_by_ref = {copy["item_ref"]: copy for copy in item_copies}
    updated: list[dict[str, Any]] = []
    for index, item in enumerate(itinerary):
        item_ref = _item_ref(index)
        copied = dict(item)
        if item_ref in copies_by_ref:
            copy = copies_by_ref[item_ref]
            copied["title"] = copy["title"]
            copied["body"] = copy["body"]
            copied["reason"] = copy["reason"]
            copied["copy_source"] = "llm_planner_copy"
        updated.append(copied)
    return tuple(updated)


def _item_prompt_summary(index: int, item: Mapping[str, Any]) -> dict[str, Any]:
    """Return one final itinerary item summary for prompt input."""

    details = item.get("details")
    overview = None
    if isinstance(details, Mapping):
        overview = details.get("overview") or details.get("overview_ko")
    return {
        "item_ref": _item_ref(index),
        "item_type": item.get("item_type"),
        "placeId": item.get("placeId"),
        "festivalId": item.get("festivalId"),
        "title": item.get("title"),
        "city_id": item.get("city_id"),
        "city_name_ko": item.get("city_name_ko"),
        "theme_tags": list(item.get("theme_tags", ())),
        "source": item.get("source"),
        "overview": overview,
        "date_status": item.get("date_status"),
        "start_date": item.get("start_date"),
        "end_date": item.get("end_date"),
    }


def _festival_prompt_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    """Return one verified festival summary for prompt input."""

    return {
        "festivalId": item.get("festivalId"),
        "title": item.get("title"),
        "date_status": item.get("date_status"),
        "start_date": item.get("start_date"),
        "end_date": item.get("end_date"),
        "source": item.get("source"),
    }


def _validation_prompt_summary(validation_result: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only public-safe validation signals to the prompt."""

    return {
        "status": validation_result.get("status"),
        "festival_placed_count": validation_result.get("festival_placed_count"),
        "festival_skipped_count": validation_result.get("festival_skipped_count"),
        "planner_status_gate": validation_result.get("planner_status_gate"),
    }


def _query_summary(package: CandidateEvidencePackage) -> dict[str, str]:
    """Best-effort query summary from package audit fields."""

    query_source = {}
    for candidate in (package.retrieval_audit, package.coverage_audit, package.fallback_audit):
        if isinstance(candidate, Mapping):
            query_source = candidate
            break
    return {
        "cleaned_raw_query": _optional_string(query_source.get("cleaned_raw_query")),
        "soft_preference_query": _optional_string(query_source.get("soft_preference_query")),
    }


def _generated_explanation_audit(
    package: CandidateEvidencePackage,
    *,
    itinerary: Sequence[Mapping[str, Any]],
    recommendation_reasons: Sequence[str],
    base_audit: PlannerExplanationAudit,
) -> PlannerExplanationAudit:
    """Build internal audit refs for generated public reasons."""

    evidence_refs = tuple(_itinerary_evidence_refs(itinerary)) or ("selected_city",)
    reason_refs = tuple(
        ExplanationReasonRef(
            reason_id=f"recommendationReasons[{index}]",
            evidence_refs=evidence_refs,
            reason_codes=("llm_grounded_copy",),
            reason_text=reason,
        )
        for index, reason in enumerate(recommendation_reasons)
    )
    hidden_notes = tuple(base_audit.hidden_internal_notes) + (
        f"planner_copy_generation:llm_used:{package.status}",
    )
    return PlannerExplanationAudit(
        reason_refs=reason_refs,
        itinerary_flow_refs=tuple(_itinerary_evidence_refs(itinerary)),
        hidden_internal_notes=hidden_notes,
    )


def _append_hidden_note(
    audit: PlannerExplanationAudit,
    note: str,
) -> PlannerExplanationAudit:
    """Return an audit copy with one additional internal note."""

    return PlannerExplanationAudit(
        reason_refs=audit.reason_refs,
        itinerary_flow_refs=audit.itinerary_flow_refs,
        hidden_internal_notes=tuple(audit.hidden_internal_notes) + (note,),
    )


def _itinerary_item_refs(itinerary: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return stable item refs for all final itinerary items."""

    return tuple(_item_ref(index) for index, _ in enumerate(itinerary))


def _itinerary_evidence_refs(itinerary: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return evidence refs for generated explanation audit."""

    refs: list[str] = []
    for item in itinerary:
        if item.get("item_type") == "attraction" and isinstance(item.get("placeId"), str):
            refs.append(f"place:{item['placeId']}")
        if item.get("item_type") == "festival" and isinstance(item.get("festivalId"), str):
            refs.append(f"festival:{item['festivalId']}")
    return tuple(refs)


def _item_ref(index: int) -> str:
    """Return the stable prompt item ref for a final itinerary index."""

    return f"item:{index}"


def _safe_public_text(value: Any, field_name: str) -> str:
    """Validate non-empty public text and block internal implementation terms."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    lowered = normalized.lower()
    if any(term in lowered for term in INTERNAL_EXPLANATION_TERMS):
        raise SchemaValidationError(f"{field_name} contains an internal term")
    return normalized


def _optional_string(value: Any) -> str:
    """Return a stripped string or empty text for optional prompt fields."""

    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "PLANNER_COPY_EXPLANATION_OUTPUT_SCHEMA",
    "PLANNER_COPY_EXPLANATION_SCHEMA_NAME",
    "RESPONSIBILITY",
    "TOOL_NAME",
    "PlannerCopyExplanation",
    "build_planner_copy_explanation_request",
    "build_planner_copy_safe_summary",
    "compose_planner_copy_explanation",
    "validate_planner_copy_explanation_output",
]
