# Lovv AgentCore Runtime Observability Specification

---
title: Lovv AgentCore Runtime Observability — 토큰·컨텍스트·레이턴시·I/O 트레이싱 스펙
project: Lovv (로브)
status: 설계 (Draft · 구현 전)
date: 2026-06-22
relates:
  - docs/specs/v2/LOVV_INTERACTIVE_ITINERARY_BUILDER_DESIGN_V1.md §13 (빌더 루프 전용 메트릭)
  - docs/specs/v2/LOVV_AGENTCORE_MEMORY_CHECKPOINTER_SPEC.md
  - ADR — 개인화·에이전트 상태 아키텍처 결정 기록 §5 (Observability 매핑)
note: 빌더 루프 전용 메트릭(루프 길이·폴백·정합성 게이트 등)은 빌더 설계 §13이 본 스펙을 확장한다.
---

이 문서는 `Lovv-agent`를 **AWS Bedrock AgentCore Runtime**으로 빌드 및 배포할 때, LangSmith와
유사한 수준의 **토큰 사용량, 컨텍스트 윈도우, 노드별 실행 시간(레이턴시), 입력/출력 트레이싱**을
수행하기 위한 모니터링 설계 규격을 정의합니다.

본 스펙은 OpenTelemetry(OTel) 표준 API와 AWS X-Ray 분산 추적, CloudWatch Structured JSON
Logs를 연계하여 성능 병목 파악과 모니터링 편의성을 최적화하는 것을 목표로 합니다.

---

## 1. 아키텍처 개요 (Observability Architecture)

전체 수집 흐름은 분산 추적(Distributed Tracing)과 구조화된 로깅(Structured Logging)의
투 트랙(Two-Track)으로 작동합니다.

```text
+------------------------------------------------------------------------+
|                      Lovv AgentCore Runtime (Lambda)                   |
|                                                                        |
|  [HTTP API Request] -> [main.py (Top Span)]                            |
|                           |                                            |
|                           v                                            |
|                  [harness.py (Node Spans)]                             |
|                     /         \                                        |
|                    v           v                                       |
|            [intent]             [candidate_evidence]                   |
|                                        |                               |
|                                        v                               |
|                               [bedrock_converse]                       |
+------------------------------------------------------------------------+
         |                                                 |
         | (OTel Spans via gRPC / OTLP)                    | (JSON Logs stdout)
         v                                                 v
  [ADOT Collector Daemon (localhost:4317)]         [CloudWatch Logs Agent]
         |                                                 |
         v (AWS X-Ray Protocol)                            v (JSON ingestion)
  [AWS X-Ray Service]                              [CloudWatch Log Group]
         |                                                 |
         +------------------------+------------------------+
                                  |
                                  v
                   [CloudWatch ServiceLens Console]
                 (Trace Map + Latency + Token Metrics)
```

1. **분산 추적 (OTel + AWS X-Ray)**: ADOT(AWS Distro for OpenTelemetry)로 워크플로우 각 단계의
   스팬(Span)을 수집해 AWS X-Ray로 내보내, 시각적 호출 그래프·구간별 소요 시간·예외를 모니터링.
2. **구조화된 로깅 (CloudWatch JSON Logs)**: 표준 출력(stdout)으로 JSON 한 줄 로그(JSON Lines)를
   내보내, CloudWatch Logs Insights에서 복잡한 파싱 없이 토큰 사용량·I/O 메타데이터를 검색.

---

## 2. 수집 지표 및 데이터 설계 (Metrics & Data Design)

### 2.1 토큰 사용량 및 컨텍스트 윈도우 (Token & Context Window)

AWS Bedrock Converse API 호출 결과(`usage` 블록)에서 실시간 토큰 사용량을 파싱해 기록한다.

- **수집 필드**: `llm.usage.input_tokens`, `llm.usage.output_tokens`, `llm.usage.total_tokens`,
  `llm.context_window`(모델별 최대 허용 컨텍스트 윈도우).
- **모델별 컨텍스트 윈도우 정적 매핑**: Converse 응답에 윈도우 총크기가 없으므로 어댑터 내부에
  정적 매핑을 두고 OTel Span 속성으로 함께 기록한다.
  - Claude 3.5 계열(`anthropic.claude-3-5-sonnet-*` 등): `200,000`
  - `amazon.titan-embed-text-v2:0`: `8,192`
  - 기타 등록 모델 기본값: `200,000`

> 주의(신뢰도 중간): 정적 매핑은 모델 추가/교체 시 갱신이 필요하다. 하이브리드(OpenAI) 모델은
> 별도 윈도우 값을 매핑에 추가한다.

### 2.2 실행 시간 및 레이턴시 (Execution Latency)

- **최상위 스팬 (`LovvAgentInvocation`)**: HTTP 요청 핸들러 진입~리턴 전체 소요.
- **노드 스팬 (예: `node.intent_agent`, `node.planner_agent`)**: 에이전트 단위 연산 시간.
- **AWS 서비스 서브스팬 (예: `s3vectors.QueryVectors`, `dynamodb.GetItem`, `BedrockConverse`)**:
  외부 API 호출 지연.

### 2.3 입력 및 출력 추적 (I/O Tracing & Safety Rules)

각 노드·LLM의 입출력을 JSON으로 스팬 속성(`Attributes`)과 CloudWatch 로그에 기록하되,
보안 가이드 필터링을 준수한다.

- **기록 허용(Allowlist)**: 사용자 자연어 쿼리 길이·테마 필터, 노드 성공 여부
  (`status = success | error`), 최종 선정 도시·일정 요약, 검증 실패 오류 메시지 스펙.
- **기록 금지(Denylist)**: AWS 자격 증명·API Key, 대용량 raw RAG/Vector 결과 전체(대신 매칭 갯수·
  랭킹 점수 메타데이터만), PII(이름·전화번호 등).

> ADR `build_memory_safe_summary` 원칙과 일치: 원시 후보·PII·내부 패키지 미기록.

---

## 3. 구조화된 JSON 로그 규격 (Structured JSON Log Schema)

CloudWatch Logs Insights 쿼리 최적화를 위해 단일 라인 JSON으로 표준 출력한다.

```json
{
  "timestamp": "2026-06-22T15:20:00.123Z",
  "level": "INFO",
  "requestId": "rec-8fee0031-0e35-4806-872a-42c877e4b77f",
  "logType": "AGENT_NODE_METRIC",
  "nodeName": "candidate_evidence_agent",
  "durationMs": 1420,
  "status": "success",
  "llmMetrics": {
    "modelId": "openai.gpt-oss-120b-1:0",
    "inputTokens": 1450,
    "outputTokens": 320,
    "totalTokens": 1770,
    "contextWindow": 200000,
    "contextUsagePercent": 0.885
  },
  "inputSummary": { "themes": ["sea_coast", "nature_trekking"], "tripType": "2d1n" },
  "outputSummary": { "selectedCity": "KR-Gyeongju", "candidateCount": 5 }
}
```

---

## 4. 컴포넌트별 상세 설계 (Component Design)

> 파일 경로는 repo 기준 상대경로다.

### 4.1 의존성 정렬 (Dependencies)

- **`pyproject.toml` (root)**
  ```toml
  dependencies = [
      "boto3>=1.34,<2",
      "langgraph>=0.6,<2",
      "opentelemetry-api>=1.24.0",   # 로컬 import 안전용 경량 패키지
  ]
  ```
- **`app/LovvAgentV1/pyproject.toml`**
  ```toml
  dependencies = [
      "aws-opentelemetry-distro",       # ADOT 배포판
      "bedrock-agentcore>=1.8,<2",
      "boto3>=1.34,<2",
      "langgraph>=0.6,<2",
      "opentelemetry-api>=1.24.0",
      "opentelemetry-sdk>=1.24.0",
      "opentelemetry-exporter-otlp>=1.24.0",
  ]
  ```

### 4.2 LLM 호출 어댑터 계측 (Bedrock Converse Instrumentation)

`src/lovv_agent/adapters/bedrock_converse.py`의 LLM 호출 경로를 OTel API로 래핑한다.

```python
from opentelemetry import trace

tracer = trace.get_tracer("lovv_agent.adapters")

def instrumented_converse(client, model_id, **payload):
    with tracer.start_as_current_span("BedrockConverse") as span:
        span.set_attribute("llm.model_id", model_id)

        # 정적 컨텍스트 윈도우 매핑
        context_window = 200000  # Default
        if "claude" in model_id.lower():
            context_window = 200000
        elif "titan" in model_id.lower():
            context_window = 8192
        span.set_attribute("llm.context_window", context_window)

        try:
            response = client.converse(**payload)
            usage = response.get("usage", {})
            span.set_attribute("llm.usage.input_tokens", usage.get("inputTokens", 0))
            span.set_attribute("llm.usage.output_tokens", usage.get("outputTokens", 0))
            span.set_attribute("llm.usage.total_tokens", usage.get("totalTokens", 0))
            return response
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise
```

### 4.3 그래프 노드 계측 (Graph Node Decoration)

`src/lovv_agent/harness.py`에서 `GraphNodeSet`을 어셈블할 때 개별 노드 함수를 트레이싱 래퍼로
동적으로 래핑해 주입한다. 각 노드의 개별 소스 파일을 오염시키지 않는다.

```python
from opentelemetry import trace
import time, json, logging

logger = logging.getLogger("lovv_agent.telemetry")
tracer = trace.get_tracer("lovv_agent.nodes")

def trace_node(node_name: str, node_func):
    def wrapper(state):
        with tracer.start_as_current_span(f"node.{node_name}") as span:
            span.set_attribute("node.name", node_name)
            span.set_attribute("node.request_id", getattr(state.request, "request_id", "unknown"))
            start_time = time.perf_counter()
            try:
                result = node_func(state)
                duration = int((time.perf_counter() - start_time) * 1000)
                print(json.dumps({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "level": "INFO",
                    "requestId": getattr(state.request, "request_id", "unknown"),
                    "logType": "AGENT_NODE_METRIC",
                    "nodeName": node_name, "durationMs": duration, "status": "success",
                }, ensure_ascii=False))
                return result
            except Exception as exc:
                duration = int((time.perf_counter() - start_time) * 1000)
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                print(json.dumps({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "level": "ERROR",
                    "requestId": getattr(state.request, "request_id", "unknown"),
                    "logType": "AGENT_NODE_METRIC",
                    "nodeName": node_name, "durationMs": duration, "status": "error",
                    "errorMessage": str(exc),
                }, ensure_ascii=False))
                raise
    return wrapper
```

> 확인 필요(신뢰도 중간): `state.request`의 식별자 속성명. 현재 trace 계층은
> `recommendation_request_id` / `agent_run_id`를 갖는다(`state.py`). `getattr` 폴백이 있으나
> 실제 필드명에 맞춰 `state.trace.recommendation_request_id` 등으로 정렬하는 것이 정확하다.

### 4.4 배포 런타임 엔트리포인트 계측 (Runtime Initialization)

`app/LovvAgentV1/main.py` 구동 시 OTel SDK가 AWS X-Ray ID 생성과 Trace Context 전파기를
사용하도록 전역 설정한다.

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.extension.aws.propagator.awsxray import AwsXRayPropagator

# 1. AWS X-Ray 호환 트레이서 프로바이더
provider = TracerProvider(id_generator=AwsXRayIdGenerator())
# 2. ADOT 로컬 에이전트로 전송할 OTLP Exporter
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
# 3. AWS X-Ray 전용 Trace Context 전파기
set_global_textmap(AwsXRayPropagator())
```

---

## 5. 모니터링 분석 쿼리 예시 (CloudWatch Logs Insights)

특정 세션의 단계별 레이턴시·토큰 사용량 분석:

```sql
fields @timestamp, nodeName, durationMs, llmMetrics.modelId, llmMetrics.totalTokens, status
| filter logType = "AGENT_NODE_METRIC"
| sort @timestamp desc
| limit 100
```

전체 토큰 사용량 집계(모델별):

```sql
filter logType = "AGENT_NODE_METRIC" and ispresent(llmMetrics.totalTokens)
| stats sum(llmMetrics.inputTokens) as TotalInput,
        sum(llmMetrics.outputTokens) as TotalOutput,
        sum(llmMetrics.totalTokens) as TotalTokens
  by llmMetrics.modelId
```

---

## 6. 확인 필요 / 주의

- [ ] OTel/ADOT 패키지 버전 **pin** 및 AgentCore Runtime(Lambda) 호환성 검증.
- [ ] `state` 식별자 속성명 정렬(`recommendation_request_id`/`agent_run_id`).
- [ ] 컨텍스트 윈도우 정적 매핑에 하이브리드(OpenAI) 모델 값 추가.
- [ ] ADOT Collector 사이드카/데몬 구동 방식(AgentCore 배포 형태에 따른 OTLP 엔드포인트).
- [ ] 빌더 루프 전용 메트릭(루프 길이·폴백 사다리·정합성 게이트·체크포인트 rw 지연)은
      빌더 설계 §13에서 본 스펙의 `AGENT_NODE_METRIC` 스키마를 **확장**해 기록.
