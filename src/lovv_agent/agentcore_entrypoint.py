"""AgentCore Runtime entrypoint adapter for the Lovv LangGraph harness.

This module intentionally keeps AgentCore-specific request wrapping outside the
business workflow. The deployed runtime should still call the same
``build_live_harness().invoke(...)`` boundary used by local live smoke tests.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from lovv_agent.harness import LovvLangGraphHarness, build_live_harness
from lovv_agent.models.schemas import SchemaValidationError

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
def _cached_live_harness() -> LovvLangGraphHarness:
    """Build the live harness once per warm AgentCore runtime instance."""

    return build_live_harness()


def handle_invocation(event: Any, context: Any | None = None) -> dict[str, Any]:
    """Invoke the Lovv recommendation graph from an AgentCore payload."""

    payload = extract_recommendation_payload(event)
    request_id = extract_request_id(event)
    return _cached_live_harness().invoke(payload, request_id=request_id)


def extract_recommendation_payload(event: Any) -> dict[str, Any]:
    """Normalize supported AgentCore/HTTP wrappers into the API request object."""

    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        raise SchemaValidationError("AgentCore invocation payload must be an object")

    if _looks_like_recommendation_request(decoded):
        return dict(decoded)

    for key in ("payload", "input", "request", "body", "prompt"):
        if key not in decoded:
            continue
        nested = _decode_json_if_needed(decoded[key])
        if isinstance(nested, Mapping) and _looks_like_recommendation_request(nested):
            return dict(nested)

    raise SchemaValidationError(
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


def _decode_json_if_needed(value: Any) -> Any:
    """Decode JSON strings or bytes while leaving structured values intact."""

    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise SchemaValidationError("AgentCore invocation payload is empty")
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(
                "AgentCore invocation string must be JSON",
            ) from exc
    return value


def _looks_like_recommendation_request(payload: Mapping[str, Any]) -> bool:
    """Return whether a mapping has the public recommendation request fields."""

    return _REQUEST_FIELD_MARKERS.issubset(payload.keys())


# Common entrypoint aliases used by local runners and deployment adapters.
handler = handle_invocation
invoke = handle_invocation


__all__ = [
    "extract_recommendation_payload",
    "extract_request_id",
    "handle_invocation",
    "handler",
    "invoke",
]
