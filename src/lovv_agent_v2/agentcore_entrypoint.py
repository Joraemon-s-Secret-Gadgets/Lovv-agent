"""AgentCore Runtime HTTP entrypoint for V2."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from langgraph.types import Command

from lovv_agent_v2.agentcore_io import (
    decode_json_if_needed as _decode_json_if_needed,
)
from lovv_agent_v2.agentcore_io import extract_resume_value, interrupt_response
from lovv_agent_v2.agents.profile.evidence import (
    InMemoryProfileEvidenceCache,
    ProfileEvidenceResolver,
)
from lovv_agent_v2.harness import LovvLangGraphV2Harness, build_live_harness


_REQUEST_FIELD_MARKERS = frozenset(
    {
        "entryType",
        "country",
        "travelMonth",
        "tripType",
        "themes",
        "includeFestivals",
    },
)


@lru_cache(maxsize=1)
def _cached_live_harness() -> LovvLangGraphV2Harness:
    """Build the live harness once per warm AgentCore runtime instance."""

    return build_live_harness()


@lru_cache(maxsize=1)
def _cached_profile_evidence_resolver() -> ProfileEvidenceResolver:
    return ProfileEvidenceResolver(
        cache=InMemoryProfileEvidenceCache(ttl_seconds=900),
        tool=None,
    )


def handle_v2_invocation(event: Any, context: Any | None = None) -> dict[str, Any]:
    """Invoke the V2 recommendation graph from an AgentCore payload."""

    session_id = extract_request_id(event)
    actor_id = extract_actor_id(event) or session_id
    resume_value = extract_resume_value(event)
    payload = (
        Command(resume=resume_value)
        if resume_value is not None
        else extract_graph_payload(event, request_id=session_id)
    )
    if resume_value is None:
        payload = _payload_with_profile_evidence(
            payload,
            actor_id=actor_id,
            thread_id=session_id,
        )

    # Requirement 2: thread_id and actor_id plumbing
    graph_config = {
        "configurable": {
            "thread_id": session_id,
            "actor_id": actor_id,
        }
    }
    result = _cached_live_harness().invoke(
        payload,
        request_id=session_id,
        graph_config=graph_config,
    )
    interrupted = interrupt_response(result)
    if interrupted is not None:
        return interrupted
    response = result.get("response") if isinstance(result, Mapping) else None
    if not isinstance(response, Mapping) or not isinstance(
        response.get("response_payload"),
        Mapping,
    ):
        raise ValueError("V2 graph did not produce response payload")
    return dict(response["response_payload"])


def _payload_with_profile_evidence(
    payload: dict[str, Any],
    *,
    actor_id: str | None,
    thread_id: str | None,
) -> dict[str, Any]:
    try:
        return _cached_profile_evidence_resolver().enrich_graph_payload(
            payload,
            actor_id=actor_id,
            thread_id=thread_id,
        )
    except Exception:  # noqa: BROAD_EXCEPT_OK
        enriched = dict(payload)
        profile_value = enriched.get("profile", {})
        profile = dict(profile_value) if isinstance(profile_value, Mapping) else {}
        profile["saved_itinerary_evidence_audit"] = {
            "cache_status": "bypassed",
            "fallback_reason": "resolver_failed",
        }
        enriched["profile"] = profile
        return enriched


def extract_graph_payload(event: Any, *, request_id: str | None = None) -> dict[str, Any]:
    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        raise ValueError("AgentCore invocation payload must be an object")
    direct = _graph_payload_from_mapping(decoded, request_id=request_id)
    if direct is not None:
        return direct

    for key in ("payload", "input", "request", "body", "prompt"):
        if key not in decoded:
            continue
        nested = _decode_json_if_needed(decoded[key])
        if not isinstance(nested, Mapping):
            continue
        payload = _graph_payload_from_mapping(nested, request_id=request_id)
        if payload is not None:
            return payload

    raise ValueError(
        "AgentCore invocation must contain a /recommendations request or V2 intent mock",
    )


def extract_recommendation_payload(event: Any) -> dict[str, Any]:
    """Normalize supported AgentCore/HTTP wrappers into the API request object."""

    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        raise ValueError("AgentCore invocation payload must be an object")

    if _looks_like_recommendation_request(decoded):
        return dict(decoded)

    for key in ("payload", "input", "request", "body", "prompt"):
        if key not in decoded:
            continue
        nested = _decode_json_if_needed(decoded[key])
        if isinstance(nested, Mapping) and _looks_like_recommendation_request(nested):
            return dict(nested)

    raise ValueError(
        "AgentCore invocation must contain a /recommendations request payload",
    )


def extract_request_id(event: Any) -> str | None:
    """Read an optional request id from common AgentCore/HTTP wrappers."""

    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        return None
    for key in ("requestId", "request_id", "invocationId", "sessionId"):
        value = decoded.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    headers = decoded.get("headers")
    if isinstance(headers, Mapping):
        for key in ("x-request-id", "X-Request-Id", "x-amzn-trace-id"):
            value = headers.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def extract_actor_id(event: Any) -> str | None:
    """Extract an optional pseudonymized actor_id from event."""

    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        return None
    for key in ("actorId", "actor_id", "userId"):
        value = decoded.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _looks_like_recommendation_request(payload: Mapping[str, Any]) -> bool:
    """Return whether a mapping has the public recommendation request fields."""

    return _REQUEST_FIELD_MARKERS.issubset(payload.keys())


def _graph_payload_from_mapping(
    payload: Mapping[str, Any],
    *,
    request_id: str | None,
) -> dict[str, Any] | None:
    intent_output = payload.get("intent_output")
    if isinstance(intent_output, Mapping):
        case_id = _text_or_none(payload.get("id"))
        return _state_from_intent_output(
            intent_output,
            request_id=request_id or case_id,
        )
    if _looks_like_recommendation_request(payload):
        return _state_from_recommendation_request(payload, request_id=request_id)
    return None


def _state_from_intent_output(
    intent_output: Mapping[str, Any],
    *,
    request_id: str | None,
) -> dict[str, Any]:
    resolved_request_id = request_id or "agentcore-v2-mock"
    return {
        "request": _request_from_intent_output(
            intent_output,
            request_id=resolved_request_id,
        ),
        "intent": {"intent_output": dict(intent_output)},
        "profile": {},
    }


def _state_from_recommendation_request(
    request: Mapping[str, Any],
    *,
    request_id: str | None,
) -> dict[str, Any]:
    resolved_request_id = request_id or _text_or_none(request.get("requestId")) or "agentcore-v2"
    normalized_request = _request_from_recommendation_request(
        request,
        request_id=resolved_request_id,
    )
    return {
        "request": normalized_request,
        "intent": {
            "city_select_input": _city_select_input_from_request(normalized_request),
        },
        "profile": {},
    }


def _request_from_intent_output(
    intent_output: Mapping[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "country": intent_output["country"],
        "travel_month": intent_output["travel_month"],
        "travel_year": intent_output.get("travel_year"),
        "trip_type": intent_output["trip_type"],
        "destination_id": intent_output.get("destination_id"),
        "include_festivals": intent_output["include_festivals"],
        "themes": tuple(intent_output["active_required_themes"]),
        "raw_query": intent_output["cleaned_raw_query"],
        "congestion_pref": intent_output.get("congestion_pref", "neutral"),
        "transport_pref": intent_output.get("transport_pref", "unknown"),
        "user_location": intent_output.get("user_location"),
    }


def _request_from_recommendation_request(
    request: Mapping[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "country": request["country"],
        "travel_month": request["travelMonth"],
        "travel_year": request.get("travelYear"),
        "trip_type": request["tripType"],
        "destination_id": request.get("destinationId"),
        "include_festivals": request["includeFestivals"],
        "themes": tuple(request["themes"]),
        "raw_query": request.get("rawQuery", request.get("naturalLanguageQuery", "")),
        "soft_preference_query": request.get("softPreferenceQuery", ""),
        "congestion_pref": request.get("congestionPref", "neutral"),
        "transport_pref": request.get("transportPref", "unknown"),
        "user_location": request.get("userLocation"),
    }


def _city_select_input_from_request(request: Mapping[str, Any]) -> dict[str, Any]:
    destination_id = request.get("destination_id")
    include_festivals = bool(request["include_festivals"])
    execution_mode = _execution_mode(
        destination_id=destination_id,
        include_festivals=include_festivals,
    )
    return {
        "country": request["country"],
        "travel_month": request["travel_month"],
        "travel_year": request.get("travel_year"),
        "trip_type": request["trip_type"],
        "active_required_themes": tuple(request["themes"]),
        "include_festivals": include_festivals,
        "cleaned_raw_query": request["raw_query"],
        "soft_preference_query": request.get("soft_preference_query", ""),
        "unsupported_conditions": (),
        "destination_id": destination_id,
        "user_location": request.get("user_location"),
        "execution_mode": execution_mode,
        "congestion_pref": request.get("congestion_pref", "neutral"),
        "transport_pref": request.get("transport_pref", "unknown"),
    }


def _execution_mode(*, destination_id: Any, include_festivals: bool) -> str:
    if isinstance(destination_id, str) and destination_id.strip():
        return "anchored_place_search"
    if include_festivals:
        return "festival_seeded_city_discovery"
    return "city_discovery"


def _text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


# Aliases
handler = handle_v2_invocation
invoke = handle_v2_invocation


__all__ = [
    "extract_graph_payload",
    "extract_recommendation_payload",
    "extract_request_id",
    "extract_actor_id",
    "handle_v2_invocation",
    "handler",
    "invoke",
]

