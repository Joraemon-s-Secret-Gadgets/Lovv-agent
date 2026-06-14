"""Bedrock Converse structured-output adapter boundary.

The adapter is intentionally provider-SDK free. Runtime callers inject a
Converse-compatible callable so unit tests, local harnesses, and future
AgentCore entrypoints can share the same schema/retry behavior without
initializing AWS clients at import time.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ADAPTER_NAME = "BedrockConverseAdapter"

RESPONSIBILITY = "Provide schema-oriented LLM calls through an injected runtime."

STRUCTURED_OUTPUT_TEXT_FORMAT = "json_schema"

RuntimeInvoker = Callable[[Mapping[str, Any]], Mapping[str, Any] | str]
OutputValidator = Callable[[Mapping[str, Any]], Any]


class StructuredOutputError(RuntimeError):
    """Raised when a structured LLM response cannot be extracted or validated."""


@dataclass(frozen=True, slots=True)
class StructuredOutputResult:
    """Result from a bounded structured-output invocation."""

    ok: bool
    value: Any | None = None
    attempts: int = 0
    validation_errors: tuple[str, ...] = ()
    raw_response: Mapping[str, Any] | str | None = None


def build_json_schema_text_format(
    *,
    name: str,
    schema: Mapping[str, Any],
    description: str,
) -> dict[str, Any]:
    """Build a Bedrock Converse ``outputConfig.textFormat`` schema block."""

    return {
        "type": STRUCTURED_OUTPUT_TEXT_FORMAT,
        "structure": {
            "jsonSchema": {
                "name": _required_text(name, "name"),
                "description": _required_text(description, "description"),
                "schema": dict(schema),
            },
        },
    }


def build_structured_converse_request(
    *,
    messages: Sequence[Mapping[str, Any]],
    schema_name: str,
    schema: Mapping[str, Any],
    schema_description: str,
    system: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a provider-neutral Converse request with JSON Schema output."""

    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
        raise StructuredOutputError("messages must be a sequence of message mappings")
    request: dict[str, Any] = {
        "messages": [dict(message) for message in messages],
        "outputConfig": {
            "textFormat": build_json_schema_text_format(
                name=schema_name,
                schema=schema,
                description=schema_description,
            ),
        },
    }
    if system is not None:
        request["system"] = [dict(item) for item in system]
    return request


def invoke_structured_output(
    *,
    runtime: RuntimeInvoker,
    request: Mapping[str, Any],
    validator: OutputValidator,
    retry_limit: int,
) -> StructuredOutputResult:
    """Invoke an injected runtime and validate structured output with retries."""

    if retry_limit < 0:
        raise StructuredOutputError("retry_limit must be zero or positive")

    errors: list[str] = []
    raw_response: Mapping[str, Any] | str | None = None
    for attempt in range(1, retry_limit + 2):
        try:
            raw_response = runtime(request)
            structured_payload = extract_structured_output(raw_response)
            value = validator(structured_payload)
            return StructuredOutputResult(
                ok=True,
                value=value,
                attempts=attempt,
                validation_errors=tuple(errors),
                raw_response=raw_response,
            )
        except Exception as exc:  # noqa: BLE001 - boundary records all provider/schema failures.
            errors.append(str(exc))

    return StructuredOutputResult(
        ok=False,
        attempts=retry_limit + 1,
        validation_errors=tuple(errors),
        raw_response=raw_response,
    )


def extract_structured_output(response: Mapping[str, Any] | str) -> Mapping[str, Any]:
    """Extract a structured object from JSON Schema or tool-output style responses."""

    if isinstance(response, str):
        return _json_object(response)
    if not isinstance(response, Mapping):
        raise StructuredOutputError("structured response must be a mapping or JSON string")

    direct = _first_mapping_value(
        response,
        ("structured_output", "structuredOutput", "json", "outputJson"),
    )
    if direct is not None:
        return direct

    output = response.get("output")
    if isinstance(output, Mapping):
        direct_output = _first_mapping_value(
            output,
            ("structured_output", "structuredOutput", "json", "outputJson"),
        )
        if direct_output is not None:
            return direct_output
        message = output.get("message")
        if isinstance(message, Mapping):
            content = message.get("content")
            extracted = _extract_from_content_blocks(content)
            if extracted is not None:
                return extracted

    content = response.get("content")
    extracted = _extract_from_content_blocks(content)
    if extracted is not None:
        return extracted

    text = response.get("text")
    if isinstance(text, str):
        return _json_object(text)

    raise StructuredOutputError("no structured output object found")


def _extract_from_content_blocks(content: Any) -> Mapping[str, Any] | None:
    """Extract structured JSON from Converse content blocks."""

    if isinstance(content, Mapping):
        content = (content,)
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return None

    for block in content:
        if not isinstance(block, Mapping):
            continue
        direct = _first_mapping_value(block, ("json", "structured_output", "structuredOutput"))
        if direct is not None:
            return direct
        tool_use = block.get("toolUse") or block.get("tool_use")
        if isinstance(tool_use, Mapping):
            tool_input = tool_use.get("input")
            if isinstance(tool_input, Mapping):
                return tool_input
            if isinstance(tool_input, str):
                return _json_object(tool_input)
        text = block.get("text")
        if isinstance(text, str):
            return _json_object(text)
    return None


def _first_mapping_value(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Mapping[str, Any] | None:
    """Return the first mapping value under any key."""

    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            return _json_object(value)
    return None


def _json_object(text: str) -> Mapping[str, Any]:
    """Parse a JSON object string."""

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError("structured output text is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise StructuredOutputError("structured output JSON must be an object")
    return value


def _required_text(value: Any, field_name: str) -> str:
    """Validate non-empty request metadata."""

    if not isinstance(value, str):
        raise StructuredOutputError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise StructuredOutputError(f"{field_name} must be a non-empty string")
    return normalized


__all__ = [
    "ADAPTER_NAME",
    "RESPONSIBILITY",
    "STRUCTURED_OUTPUT_TEXT_FORMAT",
    "OutputValidator",
    "RuntimeInvoker",
    "StructuredOutputError",
    "StructuredOutputResult",
    "build_json_schema_text_format",
    "build_structured_converse_request",
    "extract_structured_output",
    "invoke_structured_output",
]
