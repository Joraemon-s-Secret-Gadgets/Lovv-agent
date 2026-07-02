from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.infra.adapters.bedrock_converse import RuntimeInvoker

DEFAULT_SCHEMA_RETRY_LIMIT: Final = 2


@dataclass(frozen=True, slots=True)
class IntentPromptRuntime:
    runtime: RuntimeInvoker | None = None
    schema_retry_limit: int = DEFAULT_SCHEMA_RETRY_LIMIT


def intent_prompt_runtime_from_state(state: Mapping[str, Any]) -> IntentPromptRuntime:
    direct = _runtime_from_value(state.get("intent_prompt_runtime"))
    if direct is not None:
        return direct
    bucket = _runtime_from_value(runtime_value(state, "intent_prompt_runtime"))
    return bucket or IntentPromptRuntime()


def _runtime_from_value(value: Any) -> IntentPromptRuntime | None:
    if isinstance(value, IntentPromptRuntime):
        return value
    if isinstance(value, Mapping):
        runtime = value.get("runtime")
        return IntentPromptRuntime(
            runtime=runtime if callable(runtime) else None,
            schema_retry_limit=_int(value.get("schema_retry_limit")),
        )
    return None


def _int(value: Any) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool)
        else DEFAULT_SCHEMA_RETRY_LIMIT
    )


__all__ = [
    "DEFAULT_SCHEMA_RETRY_LIMIT",
    "IntentPromptRuntime",
    "intent_prompt_runtime_from_state",
]
