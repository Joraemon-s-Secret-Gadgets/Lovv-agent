from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from lovv_agent_v2.agents.response_packager.planner_copy_composer import RuntimeInvoker

DEFAULT_SCHEMA_RETRY_LIMIT: Final = 2


@dataclass(frozen=True, slots=True)
class ItineraryExplanationRuntime:
    explanation_runtime: RuntimeInvoker | None = None
    dynamo_lookup: Any | None = None
    schema_retry_limit: int = DEFAULT_SCHEMA_RETRY_LIMIT


def itinerary_explanation_runtime_from_state(
    state: Mapping[str, object],
) -> ItineraryExplanationRuntime:
    runtime = state.get("itinerary_explanation_runtime")
    if isinstance(runtime, ItineraryExplanationRuntime):
        return runtime
    if isinstance(runtime, Mapping):
        return ItineraryExplanationRuntime(
            explanation_runtime=runtime.get("explanation_runtime"),
            dynamo_lookup=runtime.get("dynamo_lookup"),
            schema_retry_limit=_int(runtime.get("schema_retry_limit")),
        )
    return ItineraryExplanationRuntime()


def _int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool)
        else DEFAULT_SCHEMA_RETRY_LIMIT
    )


__all__ = [
    "DEFAULT_SCHEMA_RETRY_LIMIT",
    "ItineraryExplanationRuntime",
    "itinerary_explanation_runtime_from_state",
]
