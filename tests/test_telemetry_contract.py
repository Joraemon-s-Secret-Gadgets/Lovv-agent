from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass, field
import io
import json
import re
import unittest
from unittest.mock import patch

from lovv_agent.adapters import bedrock_converse
from lovv_agent.adapters.aws_runtime import build_aws_runtime_adapters
from lovv_agent.config import EmbeddingSettings, LlmSettings, RuntimeConfig
from lovv_agent.harness import build_harness
from lovv_agent.repositories import dynamodb, s3_vectors
from lovv_agent import telemetry
from tests.test_harness import RecordingAwsFactory


@dataclass(slots=True)
class CapturedSpan:
    name: str
    parent_name: str | None
    attributes: dict[str, str | int | float | bool | list[str]] = field(default_factory=dict)
    exceptions: list[str] = field(default_factory=list)
    status: str | None = None

    def set_attribute(self, key: str, value) -> None:
        self.attributes[key] = value

    def record_exception(self, exc: Exception) -> None:
        self.exceptions.append(type(exc).__name__)

    def set_status(self, status) -> None:
        self.status = str(status)


@dataclass(slots=True)
class SpanScope:
    tracer: "RecordingTracer"
    span: CapturedSpan

    def __enter__(self) -> CapturedSpan:
        self.tracer.stack.append(self.span)
        return self.span

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.tracer.stack.pop()
        return False


@dataclass(slots=True)
class RecordingTracer:
    spans: list[CapturedSpan] = field(default_factory=list)
    stack: list[CapturedSpan] = field(default_factory=list)

    def start_as_current_span(self, name: str) -> SpanScope:
        parent_name = self.stack[-1].name if self.stack else None
        span = CapturedSpan(name=name, parent_name=parent_name)
        self.spans.append(span)
        return SpanScope(tracer=self, span=span)


def _payload() -> dict[str, object]:
    return {
        "entryType": "chat",
        "destinationId": None,
        "country": "KR",
        "travelYear": 2026,
        "travelMonth": 10,
        "tripType": "daytrip",
        "themes": ["sea_coast"],
        "includeFestivals": False,
        "naturalLanguageQuery": "조용하고 덜 붐비는 바다 산책을 하고 싶어요.",
        "userLocation": None,
    }


def _run_harness_with_tracer(tracer: RecordingTracer):
    factory = RecordingAwsFactory()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(model_id="amazon.titan-embed-text-v2:0"),
        llm=LlmSettings(model_id="openai.gpt-oss-120b-1:0"),
    )
    adapters = build_aws_runtime_adapters(client_factory=factory, config=config)
    harness = build_harness(config=config, adapters=adapters)
    output = io.StringIO()
    with (
        patch.object(telemetry, "_TRACER", tracer),
        patch.object(bedrock_converse, "_TRACER", tracer),
        patch.object(s3_vectors, "_TRACER", tracer),
        patch.object(dynamodb, "_TRACER", tracer),
        redirect_stdout(output),
    ):
        state = harness.invoke_state(_payload(), request_id="REQ-TELEMETRY-1")
    log_entries = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if line.strip().startswith("{")
    ]
    return state, log_entries


class TelemetryContractTest(unittest.TestCase):
    def test_agent_node_metric_logs_match_fixed_schema(self) -> None:
        tracer = RecordingTracer()

        state, log_entries = _run_harness_with_tracer(tracer)

        metric_entries = [
            entry for entry in log_entries if entry.get("logType") == "AGENT_NODE_METRIC"
        ]
        self.assertGreaterEqual(len(metric_entries), 5)
        self.assertEqual(state.trace.recommendation_request_id, "REQ-TELEMETRY-1")
        for entry in metric_entries:
            self.assertEqual(entry["requestId"], "REQ-TELEMETRY-1")
            self.assertEqual(
                {
                    "timestamp",
                    "level",
                    "requestId",
                    "logType",
                    "nodeName",
                    "durationMs",
                    "status",
                }
                <= set(entry),
                True,
            )
            self.assertIsInstance(entry["durationMs"], int)
            self.assertIn(entry["status"], {"success", "error"})
        llm_entries = [entry for entry in metric_entries if "llmMetrics" in entry]
        self.assertTrue(llm_entries)
        for entry in llm_entries:
            metrics = entry["llmMetrics"]
            self.assertIsInstance(metrics["modelId"], str)
            self.assertIsInstance(metrics["inputTokens"], int)
            self.assertIsInstance(metrics["outputTokens"], int)
            self.assertIsInstance(metrics["totalTokens"], int)
            self.assertIsInstance(metrics["contextWindow"], int)
            self.assertIsInstance(metrics["contextUsagePercent"], float)

    def test_spans_include_nodes_and_aws_subspans(self) -> None:
        tracer = RecordingTracer()

        _run_harness_with_tracer(tracer)

        span_names = [span.name for span in tracer.spans]
        self.assertIn("LovvAgentInvocation", span_names)
        for name in (
            "node.intent_agent",
            "node.supervisor_router",
            "node.candidate_evidence_agent",
            "node.planner_agent",
            "node.response_packager",
            "BedrockConverse",
            "s3vectors.QueryVectors",
            "dynamodb.GetItem",
        ):
            self.assertIn(name, span_names)
        node_spans = [span for span in tracer.spans if span.name.startswith("node.")]
        self.assertTrue(all("node.name" in span.attributes for span in node_spans))
        service_spans = {
            span.name: span
            for span in tracer.spans
            if span.name in {"BedrockConverse", "s3vectors.QueryVectors", "dynamodb.GetItem"}
        }
        self.assertIn("llm.model_id", service_spans["BedrockConverse"].attributes)
        self.assertIn("s3vectors.result_count", service_spans["s3vectors.QueryVectors"].attributes)
        self.assertIn("dynamodb.table", service_spans["dynamodb.GetItem"].attributes)

    def test_logs_and_spans_do_not_expose_denylisted_values(self) -> None:
        tracer = RecordingTracer()

        _, log_entries = _run_harness_with_tracer(tracer)

        serialized = json.dumps(log_entries, ensure_ascii=False) + json.dumps(
            [
                {"name": span.name, "attributes": span.attributes}
                for span in tracer.spans
            ],
            ensure_ascii=False,
        )
        denied_patterns = (
            r"AKIA[A-Z0-9]{16}",
            r"aws_secret",
            r"aws_session_token",
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            r"\b\d{2,3}[- .]\d{3,4}[- .]\d{4}\b",
            r"테스트 해변 6",
            r"검증된 상세 설명입니다",
        )
        for pattern in denied_patterns:
            self.assertIsNone(re.search(pattern, serialized))


if __name__ == "__main__":
    unittest.main()
