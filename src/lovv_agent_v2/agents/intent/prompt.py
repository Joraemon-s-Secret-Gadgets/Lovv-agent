from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from lovv_agent_v2.infra.adapters.bedrock_converse import (
    RuntimeInvoker,
    build_structured_converse_request,
    invoke_structured_output,
)
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError

INTENT_PROMPT_SCHEMA_NAME: Final = "lovv_v2_intent_output"
_REQUIRED_FIELDS: Final = (
    "country",
    "travel_month",
    "travel_year",
    "trip_type",
    "active_required_themes",
    "include_festivals",
    "cleaned_raw_query",
    "soft_preference_query",
    "unsupported_conditions",
    "destination_id",
    "user_location",
    "execution_mode",
    "congestion_pref",
    "transport_pref",
    "preferred_theme_ids",
    "disliked_theme_ids",
    "preferred_region_ids",
    "disliked_region_ids",
    "preferred_region_names",
    "disliked_region_names",
    "needs_clarification",
    "clarifying_question",
    "contradiction_reasons",
)
_THEME_ID_ENUM: Final = (
    "sea_coast",
    "nature_trekking",
    "history_tradition",
    "art_sense",
    "healing_rest",
    "food_local",
)
_REGION_ID_ENUM: Final = (
    "gangwon",
    "gyeongbuk",
    "sokcho",
    "andong",
    "gyeongju",
    "gangneung",
    "samcheok",
    "yeongju",
    "uljin",
)
INTENT_PROMPT_TEXT: Final = """You are Lovv V2 Intent Agent.
Extract the user's travel intent from the API request and natural-language query.
Return only the JSON schema fields. Do not explain.

Rules:
- Preserve API-owned fields unless the user clearly asks to change them.
- Use active_required_themes as Korean labels such as 역사·전통, 자연·트레킹, 바다·해안.
- Fill preferred_theme_ids and disliked_theme_ids with canonical ids:
  sea_coast, nature_trekking, history_tradition, art_sense, healing_rest, food_local.
- Fill preferred_region_ids and disliked_region_ids with canonical ids:
  gangwon, gyeongbuk, sokcho, andong, gyeongju, gangneung, samcheok, yeongju, uljin.
- Use preferred_region_names and disliked_region_names as Korean names matching the region id arrays.
- For "A 말고 B" or "A 빼고 B", put A in disliked_* and B in preferred_*.
- For "A는 피하고 B에서 C 위주", put A in disliked_region_ids, B in preferred_region_ids, and C in preferred_theme_ids.
- Do not treat preferred words after "피하고/말고/빼고" as disliked when they appear
  after a new positive phrase such as "B에서", "B로", "B 위주".
- active_required_themes should mirror preferred_theme_ids as Korean labels.
- transport_pref must be walk, car, or unknown.
- congestion_pref must be quiet, vibrant, or neutral.
- Set transport_pref=walk for 뚜벅이, 도보, 걸어서, 차 없이, 대중교통 중심.
- Set transport_pref=car for 자차, 렌터카, 차로 이동, 운전.
- Keep transport_pref=unknown for vague low-burden requests such as 이동 부담 적게.
- Set congestion_pref=quiet for explicit crowd-avoidance signals: 조용한, 한적한, 사람 적은, 사람 많은 곳 피하기.
- Set congestion_pref=vibrant for 북적이는, 활기 있는, 생동감 있는, 축제/야간/도시 분위기.
- Do not infer congestion_pref from soft mood words alone such as 고즈넉한 or 차분한; keep those in soft_preference_query.
- Do not set congestion_pref from soft_preference_query alone; use neutral unless
  the main query has a crowd or liveliness signal.
- execution_mode must be city_discovery, anchored_place_search, or festival_seeded_city_discovery.
- soft_preference_query should keep the user's softer mood/style request.
- unsupported_conditions should list only impossible live guarantees."""

INTENT_PROMPT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_REQUIRED_FIELDS),
    "properties": {
        "country": {"type": "string"},
        "travel_month": {"type": "integer"},
        "travel_year": {"type": "integer"},
        "trip_type": {"type": "string"},
        "active_required_themes": {"type": "array", "items": {"type": "string"}},
        "include_festivals": {"type": "boolean"},
        "cleaned_raw_query": {"type": "string"},
        "soft_preference_query": {"type": "string"},
        "unsupported_conditions": {"type": "array", "items": {"type": "string"}},
        "destination_id": {"type": ["string", "null"]},
        "user_location": {"type": ["object", "null"]},
        "execution_mode": {
            "type": "string",
            "enum": [
                "city_discovery",
                "anchored_place_search",
                "festival_seeded_city_discovery",
            ],
        },
        "congestion_pref": {"type": "string", "enum": ["quiet", "vibrant", "neutral"]},
        "transport_pref": {"type": "string", "enum": ["walk", "car", "unknown"]},
        "preferred_theme_ids": {
            "type": "array",
            "items": {"type": "string", "enum": list(_THEME_ID_ENUM)},
        },
        "disliked_theme_ids": {
            "type": "array",
            "items": {"type": "string", "enum": list(_THEME_ID_ENUM)},
        },
        "preferred_region_ids": {
            "type": "array",
            "items": {"type": "string", "enum": list(_REGION_ID_ENUM)},
        },
        "disliked_region_ids": {
            "type": "array",
            "items": {"type": "string", "enum": list(_REGION_ID_ENUM)},
        },
        "preferred_region_names": {"type": "array", "items": {"type": "string"}},
        "disliked_region_names": {"type": "array", "items": {"type": "string"}},
        "needs_clarification": {"type": "boolean"},
        "clarifying_question": {"type": ["string", "null"]},
        "contradiction_reasons": {"type": "array", "items": {"type": "string"}},
    },
}

_TUPLE_FIELDS: Final = (
    "preferred_theme_ids",
    "disliked_theme_ids",
    "preferred_region_ids",
    "disliked_region_ids",
    "preferred_region_names",
    "disliked_region_names",
    "contradiction_reasons",
)
_CONGESTION_SIGNAL_KEYWORDS: Final = (
    "조용",
    "한적",
    "사람 적",
    "사람 많",
    "피하",
    "북적",
    "활기",
    "생동감",
    "축제",
    "야간",
)


@dataclass(frozen=True, slots=True)
class PromptIntentResult:
    city_select_input: dict[str, Any]
    intent_updates: dict[str, Any]


def prompt_intent_from_request(
    *,
    runtime: RuntimeInvoker,
    request: Mapping[str, Any],
    retry_limit: int,
) -> PromptIntentResult | None:
    converse_request = build_intent_prompt_request(request)
    result = invoke_structured_output(
        runtime=runtime,
        request=converse_request,
        retry_limit=retry_limit,
        validator=validate_intent_prompt_output,
    )
    return result.value if isinstance(result.value, PromptIntentResult) else None


def build_intent_prompt_request(request: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "task": "Extract Lovv V2 intent_output from this request.",
        "api_request": dict(request),
    }
    request_payload = build_structured_converse_request(
        messages=[
            {
                "role": "user",
                "content": [{"text": json.dumps(payload, ensure_ascii=False)}],
            },
        ],
        system=[{"text": INTENT_PROMPT_TEXT}],
        schema_name=INTENT_PROMPT_SCHEMA_NAME,
        schema=INTENT_PROMPT_OUTPUT_SCHEMA,
        schema_description="Lovv V2 prompt-based intent output",
        reasoning_effort="low",
    )
    request_payload["inferenceConfig"] = {"maxTokens": 512, "temperature": 0}
    return request_payload


def validate_intent_prompt_output(payload: Mapping[str, Any]) -> PromptIntentResult:
    normalized_payload = dict(payload)
    for field_name in ("destination_id", "clarifying_question"):
        value = normalized_payload.get(field_name)
        if isinstance(value, str) and not value.strip():
            normalized_payload[field_name] = None
    _normalize_soft_congestion(normalized_payload)
    city_input = CitySelectInput.from_mapping(normalized_payload).to_dict()
    city_input["active_required_themes"] = list(city_input["active_required_themes"])
    updates: dict[str, Any] = {
        "intent_output": dict(city_input),
        "intent_extraction_mode": "prompt_structured_output",
    }
    for field_name in _TUPLE_FIELDS:
        updates[field_name] = _string_tuple(
            normalized_payload.get(field_name, ()),
            field_name,
        )
    updates["needs_clarification"] = _bool(normalized_payload.get("needs_clarification"))
    updates["clarifying_question"] = _optional_text(
        normalized_payload.get("clarifying_question"),
    )
    return PromptIntentResult(city_select_input=city_input, intent_updates=updates)


def _normalize_soft_congestion(payload: dict[str, Any]) -> None:
    raw_query = payload.get("cleaned_raw_query")
    soft_query = payload.get("soft_preference_query")
    raw_text = raw_query if isinstance(raw_query, str) else ""
    soft_text = soft_query if isinstance(soft_query, str) else ""
    if (
        payload.get("congestion_pref") != "neutral"
        and not any(keyword in raw_text for keyword in _CONGESTION_SIGNAL_KEYWORDS)
        and any(keyword in soft_text for keyword in _CONGESTION_SIGNAL_KEYWORDS)
    ):
        payload["congestion_pref"] = "neutral"


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a list")
    return tuple(_required_text(item, field_name) for item in value)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must contain non-empty strings")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value, "clarifying_question")


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise SchemaValidationError("needs_clarification must be a boolean")
    return value
