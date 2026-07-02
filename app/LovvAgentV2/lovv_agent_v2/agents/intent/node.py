"""Intent Node definition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.intent.prompt import PromptIntentResult, prompt_intent_from_request
from lovv_agent_v2.agents.intent.tools import intent_prompt_runtime_from_state
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.models.city_identity import enrich_city_select_identity
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError


def intent_node(state: UnifiedAgentState) -> dict[str, Any]:
    """Interpret query and determine if modification is requested."""
    intent = _intent_payload(state)
    request = state.get("request")
    existing_input = _existing_city_select_input(intent)
    prompt_result = _prompt_result(state, request) if existing_input is None else None
    city_input = (
        prompt_result.city_select_input
        if prompt_result is not None
        else _city_select_input(intent, request)
    )
    enriched_input = enrich_city_select_identity(city_input)
    normalized_input = CitySelectInput.from_mapping(enriched_input).to_dict()
    normalized_input["active_required_themes"] = list(
        normalized_input["active_required_themes"],
    )
    next_intent = dict(intent)
    if prompt_result is not None:
        next_intent.update(prompt_result.intent_updates)
    next_intent["city_select_input"] = normalized_input
    next_intent.setdefault("cleaned_raw_query", normalized_input["cleaned_raw_query"])
    next_intent.setdefault(
        "soft_preference_query",
        normalized_input["soft_preference_query"],
    )
    next_intent.setdefault(
        "unsupported_conditions",
        normalized_input["unsupported_conditions"],
    )
    next_intent.setdefault(
        "intent_extraction_mode",
        "provided" if existing_input is not None else "code_parser",
    )
    return {"intent": next_intent}


def _intent_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        return dict(intent)
    return {}


def _city_select_input(
    intent: Mapping[str, Any],
    request: Any,
) -> Mapping[str, Any]:
    value = _existing_city_select_input(intent)
    if value is not None:
        return value
    if isinstance(request, Mapping):
        return _city_select_input_from_request(request)
    raise SchemaValidationError("intent.city_select_input or state.request is required")


def _existing_city_select_input(intent: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = intent.get("city_select_input")
    if value is None:
        value = intent.get("intent_output")
    return value if isinstance(value, Mapping) else None


def _prompt_result(
    state: Mapping[str, Any],
    request: Any,
) -> PromptIntentResult | None:
    if not isinstance(request, Mapping):
        return None
    prompt_runtime = intent_prompt_runtime_from_state(state)
    if prompt_runtime.runtime is None:
        return None
    return prompt_intent_from_request(
        runtime=prompt_runtime.runtime,
        request=request,
        retry_limit=prompt_runtime.schema_retry_limit,
    )


def _city_select_input_from_request(request: Mapping[str, Any]) -> dict[str, Any]:
    themes = request.get("themes", request.get("active_required_themes", ()))
    return {
        "country": _first_present(request, "country"),
        "travel_month": _first_present(request, "travel_month", "travelMonth"),
        "travel_year": _first_present(request, "travel_year", "travelYear"),
        "trip_type": _first_present(request, "trip_type", "tripType"),
        "active_required_themes": themes,
        "include_festivals": _first_present(
            request,
            "include_festivals",
            "includeFestivals",
        ),
        "cleaned_raw_query": request.get(
            "raw_query",
            request.get("rawQuery", request.get("naturalLanguageQuery", "")),
        ),
        "soft_preference_query": request.get(
            "soft_preference_query",
            request.get("softPreferenceQuery", request.get("soft_query", "")),
        ),
        "unsupported_conditions": request.get("unsupported_conditions", ()),
        "destination_id": request.get("destination_id", request.get("destinationId")),
        "city_key": request.get("city_key", request.get("cityKey")),
        "ddb_pk": request.get("ddb_pk", request.get("ddbPk")),
        "user_location": request.get("user_location", request.get("userLocation")),
        "execution_mode": request.get("execution_mode", "city_discovery"),
        "congestion_pref": request.get("congestion_pref", "neutral"),
        "transport_pref": request.get("transport_pref", "unknown"),
    }


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    raise SchemaValidationError(f"missing required request field: {keys[0]}")
