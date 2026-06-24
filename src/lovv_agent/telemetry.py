from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import time
from typing import Final, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from lovv_agent.state import UnifiedAgentState
from lovv_agent.telemetry_metrics import (
    JsonValue,
    LlmMetricPayload,
    LlmUsageMetric,
    aggregate_llm_metrics,
    context_window_for_model,
    llm_usage_count,
    metrics_since,
    record_llm_usage,
    reset_llm_usage,
    restore_llm_usage,
)
from lovv_agent.telemetry_safety import sanitize_text

type LogEntry = dict[str, JsonValue]
type GraphEnvelope = Mapping[str, UnifiedAgentState | str | None]

NodeInputT = TypeVar("NodeInputT")
NodeResultT = TypeVar("NodeResultT")

LOG_TYPE_AGENT_NODE_METRIC: Final = "AGENT_NODE_METRIC"
DEFAULT_SERVICE_NAME: Final = "LovvAgentV1"
MAX_ERROR_MESSAGE_CHARS: Final = 300

_TRACER = trace.get_tracer("lovv_agent.telemetry")
_TELEMETRY_INITIALIZED = False


def init_telemetry(service_name: str = DEFAULT_SERVICE_NAME) -> None:
    global _TELEMETRY_INITIALIZED
    if _TELEMETRY_INITIALIZED:
        return

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return

    resource = Resource.create({"service.name": service_name})
    provider = _build_tracer_provider(TracerProvider, resource)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    except ImportError:
        pass
    else:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    trace.set_tracer_provider(provider)
    _configure_xray_propagator()
    _TELEMETRY_INITIALIZED = True


def trace_invocation(
    state: UnifiedAgentState,
    operation: Callable[[], NodeResultT],
) -> NodeResultT:
    token = reset_llm_usage()
    request_id = _request_id(state)
    with _TRACER.start_as_current_span("LovvAgentInvocation") as span:
        span.set_attribute("request.id", request_id)
        span.set_attribute("agent.run_id", state.trace.agent_run_id or "unknown")
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - top span records and re-raises.
            _record_span_error(span, exc)
            raise
        finally:
            restore_llm_usage(token)


def trace_node(
    node_name: str,
    node_func: Callable[[UnifiedAgentState], NodeResultT],
) -> Callable[[UnifiedAgentState], NodeResultT]:
    return _trace_with_state(node_name, node_func, lambda state: state)


def trace_graph_envelope_node(
    node_name: str,
    node_func: Callable[[GraphEnvelope], GraphEnvelope],
) -> Callable[[GraphEnvelope], GraphEnvelope]:
    return _trace_with_state(node_name, node_func, _state_from_envelope)


def _trace_with_state(
    node_name: str,
    node_func: Callable[[NodeInputT], NodeResultT],
    state_resolver: Callable[[NodeInputT], UnifiedAgentState],
) -> Callable[[NodeInputT], NodeResultT]:
    def wrapper(node_input: NodeInputT) -> NodeResultT:
        state = state_resolver(node_input)
        request_id = _request_id(state)
        metric_start = llm_usage_count()
        started_at = time.perf_counter()
        with _TRACER.start_as_current_span(f"node.{node_name}") as span:
            _set_node_span_attributes(span, node_name, state, request_id)
            try:
                result = node_func(node_input)
            except Exception as exc:  # noqa: BLE001 - node span records and re-raises.
                duration_ms = _duration_ms(started_at)
                _record_span_error(span, exc)
                _emit_node_metric(
                    _node_log_entry(
                        state=state,
                        node_name=node_name,
                        request_id=request_id,
                        duration_ms=duration_ms,
                        status="error",
                        result=None,
                        error_message=sanitize_text(str(exc) or type(exc).__name__),
                        llm_metrics=metrics_since(metric_start),
                    ),
                )
                raise
            duration_ms = _duration_ms(started_at)
            span.set_attribute("node.duration_ms", duration_ms)
            span.set_attribute("node.status", "success")
            _emit_node_metric(
                _node_log_entry(
                    state=state,
                    node_name=node_name,
                    request_id=request_id,
                    duration_ms=duration_ms,
                    status="success",
                    result=result,
                    error_message=None,
                    llm_metrics=metrics_since(metric_start),
                ),
            )
            return result

    return wrapper


def _build_tracer_provider(provider_type, resource):
    try:
        from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
    except ImportError:
        return provider_type(resource=resource)
    return provider_type(resource=resource, id_generator=AwsXRayIdGenerator())


def _configure_xray_propagator() -> None:
    try:
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.sdk.extension.aws.propagator.awsxray import AwsXRayPropagator
    except ImportError:
        return
    set_global_textmap(AwsXRayPropagator())


def _state_from_envelope(envelope: GraphEnvelope) -> UnifiedAgentState:
    state = envelope.get("state")
    if not isinstance(state, UnifiedAgentState):
        raise TypeError("LangGraph envelope.state must be UnifiedAgentState")
    return state


def _set_node_span_attributes(
    span,
    node_name: str,
    state: UnifiedAgentState,
    request_id: str,
) -> None:
    span.set_attribute("node.name", node_name)
    span.set_attribute("node.request_id", request_id)
    span.set_attribute("request.theme_count", len(state.request.themes))
    span.set_attribute("request.include_festivals", state.request.include_festivals)
    span.set_attribute("request.trip_type", state.request.trip_type)
    span.set_attribute(
        "request.natural_language_query_length",
        len(state.request.natural_language_query),
    )


def _node_log_entry(
    *,
    state: UnifiedAgentState,
    node_name: str,
    request_id: str,
    duration_ms: int,
    status: str,
    result: NodeResultT | None,
    error_message: str | None,
    llm_metrics: tuple[LlmUsageMetric, ...],
) -> LogEntry:
    entry: LogEntry = {
        "timestamp": _timestamp(),
        "level": "ERROR" if status == "error" else "INFO",
        "requestId": request_id,
        "logType": LOG_TYPE_AGENT_NODE_METRIC,
        "nodeName": node_name,
        "durationMs": duration_ms,
        "status": status,
        "inputSummary": _input_summary(state),
        "outputSummary": _output_summary(state, result),
    }
    metrics = aggregate_llm_metrics(llm_metrics)
    if metrics is not None:
        entry["llmMetrics"] = metrics
    if error_message is not None:
        entry["errorMessage"] = error_message[:MAX_ERROR_MESSAGE_CHARS]
    return entry


def _emit_node_metric(entry: LogEntry) -> None:
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


def _input_summary(state: UnifiedAgentState) -> dict[str, JsonValue]:
    return {
        "themes": list(state.request.themes),
        "themeCount": len(state.request.themes),
        "tripType": state.request.trip_type,
        "includeFestivals": state.request.include_festivals,
        "queryLength": len(state.request.natural_language_query),
    }


def _output_summary(state: UnifiedAgentState, result: NodeResultT | None) -> dict[str, JsonValue]:
    summary: dict[str, JsonValue] = {}
    selected_city = getattr(result, "selected_city", None)
    if selected_city is None and state.evidence.candidate_evidence_package is not None:
        selected_city = state.evidence.candidate_evidence_package.selected_city
    if selected_city is not None:
        summary["selectedCity"] = getattr(selected_city, "city_id", None)

    recommended_places = getattr(result, "recommended_places", None)
    if isinstance(recommended_places, (list, tuple)):
        summary["candidateCount"] = len(recommended_places)

    if state.planning.planner_output is not None:
        summary["itineraryItemCount"] = len(state.planning.planner_output.itinerary)
    if state.serving.response_status is not None:
        summary["responseStatus"] = state.serving.response_status
    return summary


def _request_id(state: UnifiedAgentState) -> str:
    return state.trace.recommendation_request_id or state.request.request_id or "unknown"


def _record_span_error(span, exc: Exception) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)))


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "LOG_TYPE_AGENT_NODE_METRIC",
    "LlmUsageMetric",
    "context_window_for_model",
    "init_telemetry",
    "record_llm_usage",
    "sanitize_text",
    "trace_graph_envelope_node",
    "trace_invocation",
    "trace_node",
]
