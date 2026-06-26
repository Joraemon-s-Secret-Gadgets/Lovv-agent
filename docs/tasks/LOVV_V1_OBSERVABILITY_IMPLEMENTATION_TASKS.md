# LovvAgentV1 Observability 계측 + CI/CD 게이트 준비 구현 태스크

---
title: Phase A — OTel 계측 구현 + CI/CD 적용 직전 게이트 정리
project: Lovv (로브)
status: 완료
date: 2026-06-24
runtime: LovvAgentV1 (단일 AgentCore Runtime · us-east-1)
source_spec:
  - docs/specs/v1/LOVV_AGENTCORE_OBSERVABILITY_SPEC.md (설계 전체)
  - docs/specs/v1/LOVV_V1_OBSERVABILITY_CICD_SPEC.md §3, §5 (고정 계약, 게이트 정의)
output_verification:
  - docs/tasks/results/LOVV_V1_OBSERVABILITY_IMPLEMENTATION_RESULT.md
---

## 목적

LovvAgentV1에 OTel 기반 Observability 계측을 구현하고, CI/CD 파이프라인에서 사용할
게이트 코드(테스트)를 준비한다. **실제 CI/CD 파이프라인 자동화(yaml 설정 등)는 범위 밖**이며,
각 게이트를 수동 또는 스크립트로 실행할 수 있는 상태까지 만든다.

## 범위

- ✅ OTel SDK 초기화 (X-Ray ID Generator, OTLP Exporter)
- ✅ 그래프 노드 스팬 래핑 (trace_node)
- ✅ AWS 서비스 서브스팬 추가 (BedrockConverse, S3Vectors, DynamoDB)
- ✅ AGENT_NODE_METRIC JSON 로그 출력
- ✅ Telemetry contract 테스트 (스키마 검증 + denylist 누출 검증)
- ✅ Parity check 자동화
- ✅ AgentCore validate / dry-run 게이트 스크립트
- ✅ 정본→사본 parity sync
- ❌ CI/CD yaml 파일 작성 (GitHub Actions 등)
- ❌ 자동 배포 차단/롤백 설정
- ❌ 추천 품질 평가 (AgentCore Evaluations)

## 선행 조건 — 반드시 읽어야 할 문서

아래 문서를 **순서대로** 읽은 후 작업을 시작한다.

### 아키텍처 이해

| 순서 | 파일 | 핵심 파악 내용 |
|------|------|---------------|
| 1 | `agentcore/agentcore.json` | 런타임 이름, 환경변수, 모델 ID |
| 2 | `src/lovv_agent/config.py` | RuntimeConfig 파싱, 노드별 모델 설정 |
| 3 | `src/lovv_agent/harness.py` | 그래프 조립, 노드 주입 (래핑 삽입 지점) |
| 4 | `src/lovv_agent/graph.py` | LangGraph 노드 등록명, 라우팅 순서 |
| 5 | `src/lovv_agent/state.py` | `TraceState`, `recommendation_request_id` |
| 6 | `src/lovv_agent/adapters/aws_runtime.py` | Bedrock/S3Vectors/DynamoDB 어댑터 (서브스팬 래핑 대상) |
| 7 | `app/LovvAgentV1/main.py` | 엔트리포인트 (OTel 초기화 삽입 위치) |

### 설계 참조

| 순서 | 파일 | 핵심 참조 내용 |
|------|------|---------------|
| 8 | `docs/specs/v1/LOVV_AGENTCORE_OBSERVABILITY_SPEC.md` | §4 전체 (코드 설계), §3 (JSON 로그 스키마), §2 (지표) |
| 9 | `docs/specs/v1/LOVV_V1_OBSERVABILITY_CICD_SPEC.md` §3 | V1 고정 계약: 스팬 이름, 필수 지표, 로그 필드 |
| 10 | `docs/specs/v1/LOVV_V1_OBSERVABILITY_CICD_SPEC.md` §5 | CI/CD step 1~8 정의 |

### 기존 테스트 패턴

| 순서 | 파일 | 참조 이유 |
|------|------|-----------|
| 11 | `tests/test_harness.py` | 모킹 구조, RecordingBedrockRuntimeClient 등 |
| 12 | `tests/test_aws_smoke.py` | opt-in 라이브 smoke 패턴 |

---

## 불변 규칙 (구현 시 절대 위반 금지)

1. 추천 로직 변경 금지 — 노드 내부 비즈니스 로직은 건드리지 않는다.
2. `/recommendations` 요청·응답 스키마 변경 금지.
3. 단일 `LovvAgentV1` 런타임 유지 — 노드를 별도 Runtime으로 쪼개지 않는다.
4. `src/lovv_agent`가 정본 — 변경은 정본에서 먼저, 이후 `app/LovvAgentV1/lovv_agent`에 sync.
5. Denylist 절대 미기록: AWS 자격증명, API Key, raw RAG/Vector 전체, PII.
6. `state.trace.recommendation_request_id`를 requestId로 사용 (CICD SPEC §3.3 확정).

---

## 태스크 목록

### Task 1: OTel 의존성 추가

**목적:** OTel SDK 패키지를 프로젝트 의존성에 추가한다.

**구현:**
- `pyproject.toml` (root): `opentelemetry-api>=1.24.0` 추가
- `app/LovvAgentV1/pyproject.toml`: 아래 추가
  ```
  opentelemetry-api>=1.24.0
  opentelemetry-sdk>=1.24.0
  opentelemetry-exporter-otlp>=1.24.0
  aws-opentelemetry-distro
  ```

**검증:**
```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run python -c "import opentelemetry; print(opentelemetry.__version__)"
```

**참조:** OBSERVABILITY SPEC §4.1

---

### Task 2: OTel SDK 초기화 (엔트리포인트)

**목적:** AgentCore Runtime 시작 시 OTel TracerProvider가 AWS X-Ray 호환으로 설정되도록 한다.

**구현 위치:** `src/lovv_agent/telemetry.py` (신규 파일)

**구현 내용:**
```python
# src/lovv_agent/telemetry.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource

def init_telemetry(service_name: str = "LovvAgentV1") -> None:
    """OTel TracerProvider 전역 초기화. 한 번만 호출."""
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # OTLP exporter (ADOT collector가 있을 때만 실제 전송)
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
        provider = TracerProvider(
            resource=resource,
            id_generator=AwsXRayIdGenerator(),
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    except ImportError:
        pass  # 로컬 개발 시 OTel SDK만 있으면 NoOp으로 동작

    trace.set_tracer_provider(provider)
```

**호출 위치:** `app/LovvAgentV1/main.py`의 최상단에서 `init_telemetry()` 호출.

**검증:**
```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run python -c "from lovv_agent.telemetry import init_telemetry; init_telemetry(); print('OK')"
```

**참조:** OBSERVABILITY SPEC §4.4

---

### Task 3: 그래프 노드 스팬 래핑 (trace_node)

**목적:** 각 LangGraph 노드 실행을 OTel 스팬 + AGENT_NODE_METRIC JSON 로그로 계측한다.

**구현 위치:** `src/lovv_agent/telemetry.py`에 `trace_node()` 함수 추가

**노드 함수 시그니처 (현재 코드 기준):**
- `intent_node(state: UnifiedAgentState) -> IntentState`
- `candidate_node(state: UnifiedAgentState) -> CandidateEvidencePackage`
- `festival_node(state: UnifiedAgentState) -> tuple[FestivalVerification, ...]`
- `planner_node(state: UnifiedAgentState) -> PlannerOutput`

따라서 `trace_node()` 래퍼의 시그니처는:
```python
def trace_node(node_name: str, node_func: Callable[[UnifiedAgentState], Any]):
    def wrapper(state: UnifiedAgentState) -> Any:
        # state.trace.recommendation_request_id로 requestId 획득
        request_id = state.trace.recommendation_request_id or "unknown"
        ...
    return wrapper
```

**적용 위치:** `src/lovv_agent/harness.py`의 `build_harness()` 내에서 `GraphNodeSet` 구성 시:
```python
graph = build_langgraph(
    GraphNodeSet(
        intent=trace_node("intent_agent", intent_node),
        candidate_evidence=trace_node("candidate_evidence_agent", candidate_node),
        festival_verifier=trace_node("festival_verifier_agent", festival_node),
        planner=trace_node("planner_agent", planner_node),
    ),
)
```
**주의:** `response_packager`와 `supervisor_router`는 `graph.py`의 `LocalGraphRuntime.invoke()` 내부에서 직접 호출된다.
Supervisor는 `_route_next()`/`_route_completed()`에서 호출되므로, 별도 래핑 방식이 필요:
- 옵션 A: `graph.py`의 `_record_visit()` 호출 시점에 스팬을 열고, 라우팅 완료 후 닫기
- 옵션 B: `LocalGraphRuntime`에 선택적 telemetry 콜백 주입
- **권장:** 옵션 A가 최소 변경. `_record_visit()` 시점에서 스팬 시작, 다음 `_record_visit()` 또는 return 시 종료.

**스팬 이름 규칙:** `node.{graph.py 등록명}`
- `node.intent_agent`
- `node.candidate_evidence_agent`
- `node.festival_verifier_agent`
- `node.planner_agent`
- `node.response_packager`
- `node.supervisor_router`

**JSON 로그 필드 (필수):**
```json
{
  "timestamp": "ISO8601Z",
  "level": "INFO|ERROR",
  "requestId": "state.trace.recommendation_request_id",
  "logType": "AGENT_NODE_METRIC",
  "nodeName": "node_name",
  "durationMs": 1234,
  "status": "success|error",
  "errorMessage": "(error인 경우만)"
}
```

**검증:**
```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_harness.py -q
```

**참조:** OBSERVABILITY SPEC §4.3, CICD SPEC §3.1, §3.3

---

### Task 4: AWS 서비스 서브스팬 추가

**목적:** Bedrock Converse, S3Vectors QueryVectors, DynamoDB GetItem 호출에 서브스팬을 추가한다.

**서브스팬 삽입 위치 (코드 분석 결과):**

| 서비스 | 호출 경로 | 래핑 대상 |
|--------|-----------|-----------|
| Bedrock Converse | `BedrockConverseRuntime.__call__()` in `adapters/bedrock_converse.py` | `self.client.converse(**payload)` 호출 전후 |
| S3Vectors | `S3VectorRepository.query_vectors()` in `repositories/s3_vectors.py` | `self.client.query_vectors(**payload)` 호출 전후 |
| DynamoDB | `DynamoDbRepository.get_item()` / `.get_detail_item()` / `.query_items()` in `repositories/dynamodb.py` | `self.client.get_item(...)` / `self.client.query(...)` 호출 전후 |

**구현 방식:**
각 Repository/Runtime 클래스의 메서드 내부에 직접 스팬을 추가하거나,
데코레이터 패턴으로 계측 버전을 만든다. 권장은 **메서드 내부에 직접 추가**
(클래스가 이미 thin pass-through이므로 복잡도 증가 최소).

예시 — `BedrockConverseRuntime.__call__()`:
```python
from opentelemetry import trace

_tracer = trace.get_tracer("lovv_agent.adapters")

def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
    with _tracer.start_as_current_span("BedrockConverse") as span:
        model_id = _required_text(self.model_id, "model_id")
        span.set_attribute("llm.model_id", model_id)
        payload = dict(request)
        payload.setdefault("modelId", model_id)
        try:
            response = self.client.converse(**payload)
            usage = response.get("usage", {})
            span.set_attribute("llm.usage.input_tokens", usage.get("inputTokens", 0))
            span.set_attribute("llm.usage.output_tokens", usage.get("outputTokens", 0))
            span.set_attribute("llm.usage.total_tokens", usage.get("totalTokens", 0))
            return dict(response)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise
```

예시 — `S3VectorRepository.query_vectors()`:
```python
def query_vectors(self, request: Mapping[str, Any]) -> dict[str, Any]:
    with _tracer.start_as_current_span("s3vectors.QueryVectors") as span:
        span.set_attribute("s3vectors.bucket", self.settings.bucket_name)
        span.set_attribute("s3vectors.index", self.settings.index_name)
        # ... existing logic ...
        response = self.client.query_vectors(**payload)
        vectors = response.get("vectors", [])
        span.set_attribute("s3vectors.result_count", len(vectors))
        if vectors:
            distances = [v.get("distance", 0) for v in vectors if isinstance(v, Mapping)]
            span.set_attribute("s3vectors.top_distance", min(distances) if distances else 0)
            span.set_attribute("s3vectors.bottom_distance", max(distances) if distances else 0)
            city_ids = list({v.get("metadata", {}).get("city_id") for v in vectors if isinstance(v, Mapping)} - {None})
            span.set_attribute("s3vectors.city_ids", city_ids)
        return dict(response)
```

**스팬 이름 및 속성:**

- `BedrockConverse`
  - `llm.model_id`, `llm.usage.input_tokens`, `llm.usage.output_tokens`, `llm.usage.total_tokens`, `llm.context_window`

- `s3vectors.QueryVectors` (요약 수준 기록)
  - `aws.service=s3vectors`
  - `s3vectors.bucket`, `s3vectors.index`
  - `s3vectors.result_count` — 반환된 벡터 수
  - `s3vectors.top_distance` — 가장 가까운 거리값
  - `s3vectors.bottom_distance` — 가장 먼 거리값
  - `s3vectors.city_ids` — 반환된 도시 ID 목록 (예: `["KR-Gyeongju", "KR-Pohang"]`)
  - `s3vectors.theme_tags_sample` — 상위 결과의 theme_tags (최대 5개)

- `dynamodb.GetItem` (요약 수준 기록)
  - `aws.service=dynamodb`
  - `dynamodb.table`, `dynamodb.operation`
  - `dynamodb.pk`, `dynamodb.sk` (비PII 키만)
  - `dynamodb.found` — 결과 존재 여부 (true/false)
  - `dynamodb.content_length` — overview 텍스트 길이 (자수)

**Denylist 확인 (절대 미기록):**
- raw vector 결과 전체 (개별 attraction의 full metadata)
- DynamoDB overview 텍스트 원문
- AWS 자격증명/토큰
- PII (이름, 전화번호, 이메일)

**검증:**
```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_harness.py -q
```

**참조:** OBSERVABILITY SPEC §4.2, CICD SPEC §3.1

---

### Task 5: 노드별 llmMetrics 확장 로그

**목적:** LLM을 호출하는 노드(Intent, Candidate Evidence, Planner)에서 토큰 사용량을
AGENT_NODE_METRIC 로그에 포함한다.

**구현 설계 (코드 분석 결과):**

토큰 정보 흐름:
```
BedrockConverseRuntime.__call__() → response["usage"] → 스팬 속성에 기록
                                                      ↓
trace_node() 래퍼가 BedrockConverse 서브스팬에서 읽을 수 없음 (parent-child 관계일 뿐)
```

**해결 방안 (권장: thread-local context 또는 state 기록):**

옵션 A — `state.trace.node_timings`에 LLM 메트릭 누적:
```python
# BedrockConverseRuntime.__call__() 내부에서:
response = self.client.converse(**payload)
usage = response.get("usage", {})
# 현재 활성 스팬의 parent context에 접근하는 대신,
# 간단히 response에 usage를 그대로 남기고 (이미 있음),
# trace_node() 래퍼가 노드 반환값에서 usage를 찾는다.
```

옵션 B (더 간단) — `trace_node()`가 **OTel SpanProcessor** 또는 **InMemorySpanExporter**를 통해
자식 스팬의 속성을 읽어 로그에 병합.

**권장 구현 (옵션 C — 가장 실용적):**
`BedrockConverseRuntime.__call__()`에서 response를 반환할 때 `usage` 블록이 이미 포함되어 있음.
각 노드 함수가 이 response를 처리하는 코드를 이미 가지고 있으므로,
**`trace_node()` 래퍼에 후처리 hook을 두어** 노드 실행 완료 후 `state`에서 마지막 LLM usage를 가져온다:

```python
def trace_node(node_name: str, node_func, *, llm_node: bool = False):
    def wrapper(state: UnifiedAgentState) -> Any:
        ...
        result = node_func(state)
        if llm_node:
            # 노드 실행 중 BedrockConverse 스팬이 기록한 usage를
            # state.trace.node_timings에서 읽거나,
            # InMemorySpanExporter에서 마지막 BedrockConverse 스팬을 가져온다.
            llm_metrics = _extract_last_converse_metrics()
            log_entry["llmMetrics"] = llm_metrics
        ...
    return wrapper
```

또는 가장 간단하게: **`BedrockConverseRuntime`이 마지막 usage를 인스턴스 변수에 저장**하고,
`trace_node()`이 해당 runtime 인스턴스에서 직접 읽는다:
```python
class BedrockConverseRuntime:
    last_usage: dict[str, int] | None = None

    def __call__(self, request):
        response = self.client.converse(**payload)
        self.last_usage = response.get("usage", {})
        ...
```

→ 구현 에이전트는 코드 구조에 가장 자연스러운 방식을 선택하되,
**최종 결과로 AGENT_NODE_METRIC 로그에 llmMetrics가 포함**되면 됨.

**확장 로그 예시:**
```json
{
  "logType": "AGENT_NODE_METRIC",
  "nodeName": "intent_agent",
  "durationMs": 890,
  "status": "success",
  "llmMetrics": {
    "modelId": "openai.gpt-oss-120b-1:0",
    "inputTokens": 1200,
    "outputTokens": 280,
    "totalTokens": 1480,
    "contextWindow": 200000,
    "contextUsagePercent": 0.6
  }
}
```

**LLM 미사용 노드 (Supervisor, Response Packager, Festival Verifier):**
llmMetrics 필드 자체를 생략한다 (null이 아닌 부재).

**참조:** OBSERVABILITY SPEC §3, CICD SPEC §3.3

---

### Task 6: Telemetry Contract 테스트

**목적:** 계측이 스키마를 정확히 준수하는지, denylist 필드가 절대 새지 않는지 단위 테스트로 강제한다.

**구현 위치:** `tests/test_telemetry_contract.py` (신규)

**테스트 케이스:**

1. **스키마 정합 테스트:**
   - AGENT_NODE_METRIC JSON 출력에 필수 필드(`timestamp`, `level`, `requestId`, `logType`, `nodeName`, `durationMs`, `status`) 전체 존재
   - `llmMetrics` 포함 시 하위 필드 타입 검증 (숫자, 문자열)
   - 알 수 없는 필드가 추가되어도 기존 필드는 유지

2. **스팬 계층 테스트:**
   - 모킹 트레이서로 전체 harness 실행 후:
     - `LovvAgentInvocation` 최상위 스팬 존재
     - 모든 노드 스팬(`node.*`) 존재
     - 서비스 서브스팬(`BedrockConverse`, `s3vectors.QueryVectors`, `dynamodb.GetItem`) 존재
   - 각 스팬에 필수 attribute 존재 (`node.name`, `llm.model_id` 등)

3. **Denylist 누출 테스트:**
   - 전체 harness 실행 후 캡처된 모든 stdout JSON 라인에서:
     - AWS 자격증명 패턴 (`AKIA*`, `aws_secret`, `aws_session_token`) 미검출
     - raw vector 결과 전체 (6개 이상 attraction record) 미검출
     - PII 패턴 (전화번호, 이메일) 미검출
   - 모든 스팬 속성에서 동일 denylist 검증

4. **requestId 정렬 테스트:**
   - 로그의 `requestId`가 `state.trace.recommendation_request_id`와 일치

**검증:**
```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_telemetry_contract.py -q
```

**참조:** CICD SPEC §5.1, §5 step 5

---

### Task 7: Parity Check 자동화

**목적:** `src/lovv_agent` ↔ `app/LovvAgentV1/lovv_agent` 간 파일 동기 검증을 자동화한다.

**구현 위치:** `tests/test_parity.py` (신규) 또는 `scripts/check_parity.py`

**비교 대상:**
```text
src/lovv_agent/**/*.py
src/lovv_agent/prompts/*.md
vs
app/LovvAgentV1/lovv_agent/**/*.py
app/LovvAgentV1/lovv_agent/prompts/*.md
```

**제외:** `__pycache__`, `.pyc`, `*.egg-info`

**동작:**
- 불일치 시 mismatched 상대 경로 목록 출력 후 테스트 실패
- 일치 시 pass

**검증:**
```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_parity.py -q
```

**참조:** PRODUCTION READINESS SPEC Requirements 3, CICD SPEC §5 step 4

---

### Task 8: 정본→사본 Sync

**목적:** Task 2~5에서 변경한 `src/lovv_agent/` 파일을 `app/LovvAgentV1/lovv_agent/`에 동기화한다.

**구현:** 수동 복사 또는 sync 스크립트. Task 7 parity check가 통과해야 완료.

**검증:**
```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_parity.py -q
```

---

### Task 9: E2E 실행 결과 캡처 스크립트

**목적:** 라이브 또는 모킹 E2E 실행 시 각 노드/tool의 실제 결과를 JSON으로 dump하여
테스트 결과서에 첨부할 수 있도록 한다.

**구현 위치:** `scripts/capture_e2e_state.py` (신규)

**직렬화 방법 (코드 분석 결과):**
`UnifiedAgentState`는 `@dataclass`이며, `.to_dict()` 메서드가 `dataclasses.asdict(self)`를 호출한다.
따라서 전체 상태를 JSON 직렬화하려면:
```python
import json
from dataclasses import asdict

state = harness.invoke_state(payload, request_id="...")
state_dict = state.to_dict()
# tuple은 JSON list로 변환됨, dataclass 필드는 재귀적으로 dict 변환됨

# 주의: CandidateEvidencePackage, PlannerOutput 등은 NamedTuple 또는 dataclass이므로
# asdict()가 재귀적으로 처리함. 단, custom objects가 있으면 default= 핸들러 필요.
json.dumps(state_dict, ensure_ascii=False, default=str, indent=2)
```

**동작:**
1. `build_harness()` (모킹) 또는 `build_live_harness()` (라이브)로 harness 생성
2. `harness.invoke_state(payload, request_id=...)` 실행
3. 실행 완료 후 `state.to_dict()`로 전체 상태를 dict 변환
4. 테스트 결과서에 필요한 섹션별로 추출하여 JSON 파일로 저장:
   - `state_dict["intent"]` — Intent 추출 결과
   - `state_dict["evidence"]["candidate_evidence_package"]` — CE 패키지
   - `state_dict["festival"]` — Festival Verifier 결과
   - `state_dict["planning"]["planner_output"]` — Planner 일정 출력
   - `state_dict["routing"]` — Supervisor 라우팅 (visited_nodes in node_timings)
   - `state_dict["serving"]["response_payload"]` — 최종 공개 응답
   - `state_dict["trace"]["node_timings"]` — 노드 방문 순서, intent_mode 등
5. 출력 파일: `docs/tasks/results/e2e_state_dump_<timestamp>.json`

**모킹 모드 (AWS 불필요):**
```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run python scripts/capture_e2e_state.py --mock
```
→ `tests/test_harness.py`와 동일한 `RecordingAwsFactory` 사용

**라이브 모드 (AWS 필요):**
```powershell
$env:LOVV_ENABLE_AWS_SMOKE='1'; $env:UV_CACHE_DIR='.cache\uv'; uv run python scripts/capture_e2e_state.py --live
```

**참조:** TEST_PLAN_SPEC §2.5

---

### Task 10: 전체 게이트 수동 실행 확인

**목적:** CI/CD step 1~8에 해당하는 명령을 순서대로 수동 실행하여 전체 pass를 확인한다.

**실행 순서:**

```powershell
# step 1) lint (있다면)
# step 2) unit test
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest -q

# step 3) compileall
$env:UV_CACHE_DIR='.cache\uv'; uv run python -m compileall src tests app\LovvAgentV1

# step 4) parity check
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_parity.py -q

# step 5) telemetry contract test
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_telemetry_contract.py -q

# step 6) (opt-in) structured-output smoke
# $env:LOVV_ENABLE_AWS_SMOKE='1'; uv run pytest tests/test_aws_smoke.py -q

# step 7) agentcore validate
agentcore validate --json

# step 8) agentcore dry-run
$env:UV_CACHE_DIR='D:\bootcamp\workspace\project\03_final\04_Lovv-agent\.cache\uv'; agentcore deploy --target v1 --dry-run --json
```

**검증:** 전체 step pass 또는 환경 blocker 기록.

**참조:** CICD SPEC §5 step 1~8

---

## 완료 기준

- [x] OTel SDK import 가능, init_telemetry() 정상 동작
- [x] 전체 harness 실행 시 모든 노드에 `node.*` 스팬 생성
- [x] BedrockConverse, S3Vectors, DynamoDB에 서브스팬 생성
- [x] AGENT_NODE_METRIC JSON 로그가 §3.3 스키마 준수
- [x] llmMetrics (토큰, contextUsagePercent) 기록됨
- [x] Telemetry contract 테스트 전체 pass
- [x] Denylist 누출 0
- [x] Parity check pass (정본 ↔ 사본 동기)
- [x] E2E 상태 캡처 스크립트 동작 (모킹 모드에서 JSON dump 생성)
- [x] agentcore validate --json pass
- [x] agentcore deploy --target v1 --dry-run --json pass (또는 환경 blocker 기록)
- [x] 기존 pytest 212+ 테스트 회귀 없음

## 결과 산출물

구현 완료 후 `docs/tasks/results/LOVV_V1_OBSERVABILITY_IMPLEMENTATION_RESULT.md`에 기록:
- 브랜치, 타임스탬프
- 각 Task 완료 여부
- pytest 실행 결과 (총 테스트 수, pass/fail)
- compileall 결과
- telemetry contract 테스트 결과
- parity check 결과
- agentcore validate/dry-run 결과
- 환경 blocker (있을 경우)
