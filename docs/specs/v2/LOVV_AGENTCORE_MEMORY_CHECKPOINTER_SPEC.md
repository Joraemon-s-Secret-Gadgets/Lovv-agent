# Lovv AgentCore Memory Checkpointer SPEC

---
title: Lovv — AgentCore Memory Checkpointer 설계 문서 (SPEC)
project: Lovv (로브)
status: 설계 (코드 미수정 · 구현 전)
date: 2026-06-22
relates:
  - docs/specs/v2/LOVV_AGENTCORE_MEMORY_CHECKPOINTER_MIGRATION_PLAN.md (단계 구조)
  - ADR — Lovv 개인화·에이전트 상태 아키텍처 결정 기록 (결정 6·7·8)
supersedes_boundary:
  - LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md Requirement 5.4
    ("does not enable AgentCore Memory") — 본 SPEC이 이를 게이트형으로 해제
---

## Objective

ADR의 결정 6·7·8(멀티턴 HITL용 checkpointer = AgentCoreMemorySaver, "ephemeral은
통합·persistent는 분리", `actorId` = 가명 ID)을 Lovv-agent 코드에 반영하기 위한
**설계 계약**을 정의한다. 본 SPEC은 구현 코드를 포함하지 않으며, 구현 시 따라야 할
요구사항·인터페이스·경계·검증 기준을 규정한다.

대상 코드베이스: 본 저장소 `04_Lovv-agent`. 정본(canonical) = `src/lovv_agent/`.
배포 사본 = `app/LovvAgentV1/lovv_agent/` (parity 동기화 대상).

## Current Structure (검증됨 · 신뢰도 높음)

```text
agentcore_entrypoint.handle_invocation(event)
  -> extract_recommendation_payload(event)
  -> extract_request_id(event)              # sessionId 읽음, but graph로 안 넘김
  -> _cached_live_harness().invoke(payload, request_id=...)   # graph_config 미전달

harness.LovvLangGraphHarness.invoke(payload, request_id=, graph_config=)
  -> request_state_from_api(...)
  -> invoke_langgraph(self.graph, state, config=graph_config)

graph.build_langgraph(nodes, supervisor=None)
  -> StateGraph(LangGraphState)             # envelope.state = UnifiedAgentState 객체 전체
  -> builder.compile()                      # checkpointer 인자 없음 → 무상태
graph.invoke_langgraph(graph, state, config)
  -> graph.invoke({"state": state}, config=dict(config or {}))

clarification: supervisor → next_node=END_WAIT_USER → RESPONSE_PACKAGER → END
  # 진짜 interrupt 아님(terminal). 재개 불가.
```

확인된 사실:

1. `builder.compile()`에 checkpointer 없음 (`src/lovv_agent/graph.py:321`).
2. envelope이 `UnifiedAgentState` **라이브 객체**를 단일 `state` 채널로 전달.
3. `invoke_langgraph`가 `config`를 `graph.invoke(..., config=...)`로 그대로 전달.
4. `handle_invocation`이 `graph_config`를 구성/전달하지 않음.
5. 의존성에 `langgraph-checkpoint-aws` 없음 (base `langgraph-checkpoint`만).
6. `state.to_dict()`(asdict)는 있으나 역복원기(dict→state) 없음.

## Assumptions

1. 가명화는 AgentCore Identity 경계의 책임이며, 진입 이벤트의 `actorId`는 **이미
   가명 ID**라고 가정한다. 본 범위에서 재식별·치환하지 않는다.
2. 무상태 기본 동작을 유지한다. checkpointer는 설정으로만 켜지는 opt-in.
3. `/recommendations` 요청·응답 스키마는 변경하지 않는다.
4. 영속 가명 개인화 프로파일·raw 이벤트는 **커스텀 DynamoDB(TTL)→S3 콜드**로 보관한다(보관기간·
   삭제권 직접 통제). 단기만 AgentCore Memory. 매핑·PII는 별도 KMS·IAM. 장기 보관은 본
   SPEC(checkpointer/단기)의 범위와 구분된다.

## Requirements

### Requirement 1: Checkpointer 주입 지점 (변환 ②-자리)

**User Story:** Lovv 메인테이너로서, 그래프 컴파일이 optional checkpointer를 받도록
하여, 무상태 기본을 깨지 않고도 영속 saver를 한 지점에서 켤 수 있길 원한다.

**Acceptance Criteria:**

1. `build_langgraph`가 `checkpointer: BaseCheckpointSaver | None = None` 파라미터를
   받고, `builder.compile(checkpointer=checkpointer)`로 전달한다.
2. `checkpointer=None`이면 컴파일 결과·실행 결과가 현재와 동일하다(무상태).
3. `build_harness`/`build_live_harness`가 checkpointer를 `build_langgraph`로 배선하되,
   Phase 1 기본값은 `None`이다.
4. 변경 후 정본(`src/lovv_agent`)과 배포 사본(`app/LovvAgentV1/lovv_agent`)이 parity를
   유지한다.

### Requirement 2: actorId(가명)·thread_id 플러밍 (변환 ①)

**User Story:** Lovv 운영자로서, 진입 이벤트의 세션·actor 식별자가 그래프 config까지
전달되어, HITL 재개와 actor 격리가 동일 키로 동작하길 원한다.

**Acceptance Criteria:**

1. `handle_invocation`이 이벤트에서 `actor_id`(가명)와 `session_id`를 추출해
   `graph_config = {"configurable": {"thread_id": session_id, "actor_id": actor_id}}`
   를 구성하고 `harness.invoke(..., graph_config=graph_config)`로 전달한다.
2. `thread_id`는 LangGraph thread, `session_id`는 AgentCore session에 매핑된다.
3. `actor_id`가 없으면 안전한 기본(예: `request_id` 기반 임시 세션키)으로 폴백하고,
   재식별 가능한 원본 식별자를 절대 사용하지 않는다.
4. config가 비어도(무 checkpointer) 기존 무상태 실행이 깨지지 않는다.

### Requirement 3: Memory 런타임 설정 (게이트형 활성화)

**User Story:** Lovv 운영자로서, AgentCore Memory 사용 여부·만료·KMS를 환경설정으로
통제하여, 기본은 off이고 명시적으로만 켜지길 원한다.

**Acceptance Criteria:**

1. `config.py`에 `MemorySettings` 섹션을 추가한다: `enabled: bool=False`,
   `memory_id: str|None`, `event_expiry_days: int=7`, `kms_key_arn: str|None`.
2. `ENV_KEYS`에 `LOVV_MEMORY_ENABLED / LOVV_MEMORY_ID /
   LOVV_MEMORY_EVENT_EXPIRY_DAYS / LOVV_MEMORY_KMS_KEY_ARN`를 추가한다.
3. `RuntimeConfig.from_env`가 이를 파싱하며, import 시 AWS 호출·자격증명 접근을 하지
   않는다(기존 config 규약 유지).
4. `enabled=False`(기본)이면 checkpointer는 생성되지 않는다.

### Requirement 4: 상태 직렬화 round-trip (영속 saver 선행 게이트)

**User Story:** Lovv 개발자로서, 영속 checkpointer가 채널 값을 바이트로 직렬화해도
무손실 복원되도록, `UnifiedAgentState`의 직렬화 경로를 보장하길 원한다.

**Acceptance Criteria:**

1. `state.py`에 `unified_state_from_dict(d)`(=`to_dict()`의 역함수)를 추가하고,
   중첩 schemas(`PlannerOutput`, `CandidateEvidencePackage`, `FestivalVerification`
   등)를 정확히 재구성한다.
2. `state == unified_state_from_dict(state.to_dict())`가 모든 그룹에 대해 성립한다.
3. 그래프 envelope이 영속 saver에서 직렬화될 때 이 serde 경로를 사용한다.
4. 본 게이트가 통과하기 전에는 영속 saver(Requirement 5)를 활성화하지 않는다.

### Requirement 5: AgentCoreMemorySaver 연결 (변환 ② · env-gated)

**User Story:** Lovv 운영자로서, 설정이 켜졌을 때 checkpoint+세션이 AgentCore
Memory 단기에 통합 저장되어, microVM 세션 만료 후에도 동일 thread로 재개되길 원한다.

**Acceptance Criteria:**

1. `pyproject.toml`에 `langgraph-checkpoint-aws`를 추가하고 버전을 **pin**한다
   (preview/CDK alpha 변동 대비). `uv.lock`을 갱신한다.
2. `adapters/agentcore_memory.py`에 `build_checkpointer(memory: MemorySettings) ->
   BaseCheckpointSaver | None`를 신설한다. `enabled=False`면 `None`.
3. checkpoint와 세션 컨텍스트는 **수명을 공유**하며, `event_expiry_days`는 "재개 허용
   최대 기간"으로 해석한다(ADR 4.6).
4. checkpoint는 actor·session 단위로 격리되며, 장기 기억 추출 대상에서 제외된다.
5. `actorId`로는 항상 가명 ID를 사용한다(Requirement 2와 동일 키).

### Requirement 6: clarification → interrupt/resume (변환 ③ · 별도 단계)

**User Story:** Lovv 사용자로서, planner가 후보 목적지를 제시하면 같은 thread에서
선택을 이어가, 멀티턴으로 재개되길 원한다.

**Acceptance Criteria:**

1. `END_WAIT_USER` 종료 분기를 LangGraph `interrupt()` 기반 재개 가능 흐름으로
   재배선한다.
2. 재개 입력(선택된 목적지)을 동일 `thread_id`로 resume한다.
3. interrupt는 활성 checkpointer(Requirement 5)를 선행 요건으로 한다.
4. 본 요구는 회귀 위험이 크므로 **별도 구현 단계**로 분리한다.

### Requirement 7: 경계 (Scope Boundaries)

**Acceptance Criteria:**

1. `/recommendations` 요청·응답 스키마를 변경하지 않는다.
2. 영속 가명 개인화 프로파일·raw 이벤트는 **커스텀 DynamoDB(TTL)→S3**로 분리 보관한다(AgentCore
   Memory 장기로 이관하지 않음). 매핑·PII는 별도 KMS·IAM. actorId = 가명 ID로 actor 격리.
3. 가명 ID↔실제신원 매핑 테이블을 본 코드 경로에서 접근하지 않는다.
4. 비밀·자격증명·PII 포함 페이로드를 커밋하지 않는다.
5. Phase 1은 무상태 기본 동작을 변경하지 않는다.

## Architecture

```text
AgentCore Identity (가명 ID 경계)
  -> handle_invocation(event)
       -> extract actor_id(가명), session_id
       -> graph_config = {configurable: {thread_id, actor_id}}
       -> harness.invoke(payload, graph_config)

RuntimeConfig.from_env
  -> MemorySettings(enabled, memory_id, event_expiry_days, kms_key_arn)

build_live_harness
  -> build_checkpointer(config.memory)        # enabled=False -> None
  -> build_harness(checkpointer=...)
       -> build_langgraph(nodes, checkpointer=...)
            -> builder.compile(checkpointer=...)

[Ephemeral 통합]  AgentCoreMemorySaver: checkpoint blob + 세션 컨텍스트 (공유 expiry)
[Persistent] 커스텀: DynamoDB(프로필 핫 / 이벤트 TTL)→S3 콜드 · 매핑·PII 별도 KMS/IAM

[Phase 3] END_WAIT_USER -> interrupt() -> resume(thread_id)
```

## Components And Interfaces

### build_langgraph (graph.py)

```python
def build_langgraph(
    nodes: GraphNodeSet,
    *,
    supervisor: SupervisorRouter | None = None,
    checkpointer: "BaseCheckpointSaver | None" = None,
) -> Any:
    ...
    return builder.compile(checkpointer=checkpointer)
```

### MemorySettings (config.py)

```python
@dataclass(frozen=True, slots=True)
class MemorySettings:
    enabled: bool = False
    memory_id: str | None = None
    event_expiry_days: int = 7
    kms_key_arn: str | None = None
    def __post_init__(self) -> None:
        if self.event_expiry_days < 1 or self.event_expiry_days > 365:
            raise ConfigError("event_expiry_days must be 1..365")
```

### entrypoint (agentcore_entrypoint.py)

```python
def extract_actor_id(event) -> str | None: ...   # actorId/actor_id/userId(가명) 우선
def handle_invocation(event, context=None) -> dict:
    payload = extract_recommendation_payload(event)
    session_id = extract_request_id(event)
    actor_id = extract_actor_id(event) or session_id
    graph_config = {"configurable": {"thread_id": session_id, "actor_id": actor_id}}
    return _cached_live_harness().invoke(payload, request_id=session_id,
                                         graph_config=graph_config)
```

### build_checkpointer (adapters/agentcore_memory.py · 신설)

```python
def build_checkpointer(memory: "MemorySettings") -> "BaseCheckpointSaver | None":
    if not memory.enabled:
        return None
    # AgentCoreMemorySaver 정확한 시그니처는 설치 버전에서 검증 (Open Questions)
    return AgentCoreMemorySaver(memory_id=memory.memory_id, ...)
```

### state serde (state.py)

```python
def unified_state_from_dict(d: Mapping[str, Any]) -> UnifiedAgentState: ...
# 불변식: s == unified_state_from_dict(s.to_dict())
```

## Data Model

| 식별자 | LangGraph | AgentCore | 값 |
|--------|-----------|-----------|-----|
| thread | `configurable.thread_id` | `session_id` | 세션 식별자 |
| actor | `configurable.actor_id` | `actor_id` | **가명 ID** |
| 만료 | — | `eventExpiryDuration` | `event_expiry_days`(일, 1..365) |

저장 분리: checkpoint blob(actor·session 격리, 장기추출 제외) ↔ 세션 컨텍스트(수명 공유).

## Testing Strategy

1. **무상태 회귀**: `build_langgraph(checkpointer=None)` 결과가 기존과 동일 — 기존
   pytest 전부 통과.
2. **entrypoint 단위**: 다양한 이벤트 래퍼에서 `thread_id/actor_id`가 올바르게
   구성되고, 누락 시 안전 폴백.
3. **config 단위**: `MemorySettings` 파싱·검증(범위·기본 off), import 시 AWS 무접근.
4. **serde round-trip**: `s == unified_state_from_dict(s.to_dict())` (모든 그룹·중첩
   schemas) — 영속 saver 활성화의 선행 게이트.
5. **parity**: `src/lovv_agent` ↔ `app/LovvAgentV1/lovv_agent` 동기 확인.
6. **(가능 시) 통합 스모크**: AgentCore Memory 테스트 리소스로 thread 재개. 로컬
   한계 시 모킹.

## Boundaries

- Phase 1(R1·R2·R3)은 무상태 기본 불변 · AWS 불필요 · 회귀 위험 최소.
- Phase 2(R4·R5)는 serde 게이트 통과 후, env-gated. 로컬 완전검증 제한.
- Phase 3(R6)은 별도 구현 단계(그래프 제어흐름 변경).

## Success Criteria

1. checkpointer 주입 지점·식별자 플러밍·Memory 설정이 정의대로 존재하고 기본 off에서
   무상태 동작이 보존된다.
2. serde round-trip 불변식이 테스트로 보장된다.
3. `LOVV_MEMORY_ENABLED=true` 시 동일 thread 재개가 동작한다(통합 스모크 또는 모킹).
4. 정본/사본 parity 유지, `/recommendations` 스키마 불변.

## Open Questions

1. 설치된 `langgraph-checkpoint-aws`의 `AgentCoreMemorySaver` 정확한 생성자
   시그니처(`memory_id`, expiry, KMS 인자명) — 설치 후 검증(신뢰도 중간).
2. `event_expiry_days` 최종값(planning 세션 수명 기준) 산정.
3. AgentCore Memory 테스트 리소스 가용 여부 → 통합 스모크 범위 결정.
4. serde에서 schemas 중첩 객체 전체 round-trip 가능성 정밀 점검.
5. 본 SPEC이 Production Readiness SPEC R5.4 경계를 해제하므로, 해당 문서에 cross-ref
   주석을 남길지 결정.
