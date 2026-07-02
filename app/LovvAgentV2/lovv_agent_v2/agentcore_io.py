from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def decode_json_if_needed(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("AgentCore invocation payload is empty")
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "AgentCore invocation string must be JSON",
            ) from exc
    return value


def extract_resume_value(event: Any) -> Any | None:
    decoded = decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        return None
    if "resume" in decoded:
        return decoded["resume"]
    if "resumeValue" in decoded:
        return decoded["resumeValue"]
    return None


def interrupt_response(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, Mapping):
        return None
    interrupts = result.get("__interrupt__")
    if not isinstance(interrupts, (list, tuple)) or not interrupts:
        return None
    first_interrupt = interrupts[0]
    value = getattr(first_interrupt, "value", None)
    return dict(value) if isinstance(value, Mapping) else None
