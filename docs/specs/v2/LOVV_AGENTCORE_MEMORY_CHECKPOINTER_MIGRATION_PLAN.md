---
title: Lovv — AgentCore Memory Checkpointer 전환 구현 계획 (계획 전용)
project: Lovv (로브)
status: 계획 (코드 미수정)
date: 2026-06-22
relates: docs/specs ADR — 개인화·에이전트 상태 아키텍처 결정 기록
scope: ADR 변환 ①(thread/actor 플러밍) ②(checkpointer 주입) ③(interrupt 재배선)
---

# AgentCore Memory Checkpointer 전환 — 구현 계획

> 이 문서는 **계획 전용**입니다. 아래 변경은 아직 적용하지 않았습니다.
> 사용자가 범위를 확정하면 Phase 단위로 실행합니다.

## 0. 목표와 원칙

ADR의 결정 6·7·8을 코드에 반영한다.

- Ephemeral(checkpoint + 세션 컨텍스트) → AgentCore Memory 단기로 **통합**.
- 영속 개인화 프로파일 → 커스텀 2층 티어로 **분리 유지** (이 계획 범위 밖).
- 모든 계층 `actorId` = **가명 ID**.
- **무상태 기본 동작은 깨지 않는다.** checkpointer는 설정으로만 켜지는 opt-in.

## 1. 검증된 현재 상태 (신뢰도 높음 — 코드 확인됨)

| 사실 | 위치 |
|------|------|
| `builder.compile()`에 checkpointer 인자 없음 → 매 invocation 무상태 | `src/lovv_agent/graph.py:321` |
| 그래프 envelope이 `UnifiedAgentState` **객체 전체**를 단일 `state` 채널로 전달 | `graph.py` `LangGraphState`, `invoke_langgraph` |
| `invoke_langgraph(graph, state, config=...)`가 `config`를 `graph.invoke(..., config=...)`로 전달 | `graph.py:324` |
| `harness.invoke(payload, request_id=, graph_config=)`가 `graph_config`를 그대로 전달 | `harness.py` |
| `handle_invocation`은 `graph_config`를 **넘기지 않음** (request_id만) | `agentcore_entrypoint.py:38` |
| `extract_request_id`는 `sessionId` 등을 읽지만 actor_id 개념 없음 | `agentcore_entrypoint.py:68` |
| clarification은 `END_WAIT_USER` → `RESPONSE_PACKAGER`로 종료(terminal). 진짜 interrupt 아님 | `graph.py` conditional edge, `supervisor.py:59` |
| 의존성: `langgraph>=0.6,<2`, base `langgraph-checkpoint`만. `langgraph-checkpoint-aws` 없음 | `pyproject.toml`, `uv.lock` |
| config는 frozen dataclass 섹션 + `RuntimeConfig.from_env` 구조 | `config.py:343,357` |

## 2. 핵심 리스크 — state 직렬화 (신뢰도 높음 / 영향 큼)

현재 그래프는 `UnifiedAgentState` **라이브 파이썬 객체**를 채널 값으로 들고 다닌다.
인메모리(MemorySaver)면 객체 참조라 문제없지만, **영속 saver(AgentCoreMemorySaver/DynamoDBSaver)는 채널 값을 바이트로 직렬화**해야 한다.

- `UnifiedAgentState`는 중첩 dataclass(+ `schemas`의 `PlannerOutput`, `CandidateEvidencePackage` 등)로 구성.
- LangGraph 기본 serde(JsonPlus)가 임의 slots dataclass를 무손실 round-trip 한다는 보장이 없음.
- ⇒ **영속 checkpointer를 켜기 전, `UnifiedAgentState ↔ dict` serde 경로가 선행 요건.**
  - 이미 `to_dict()`(asdict) + `build_memory_safe_summary`가 있으나, **역직렬화(dict→state)** 복원기는 없음.

이 리스크 때문에 Phase 1(플러밍)과 Phase 2(실제 saver)를 분리한다. Phase 1은 직렬화와 무관하므로 안전.

## 3. Phase 별 계획

### Phase 1 — 기반 플러밍 (안전, AWS 불필요, 기본동작 불변) · 변환 ①+②(주입지점)

목적: actor_id(가명)+thread_id를 진입점부터 그래프 config까지 흘리고, `compile()`이 optional checkpointer를 받도록 **자리만** 만든다. checkpointer 기본값 None → 동작 변화 없음.

1. **`graph.py` — `build_langgraph(..., checkpointer=None)`**
   - 시그니처에 `checkpointer: Any | None = None` 추가.
   - `return builder.compile()` → `return builder.compile(checkpointer=checkpointer)`.
   - `None`이면 현재와 동일(무상태).

2. **`config.py` — `MemorySettings` 섹션 추가**
   - 필드: `enabled: bool=False`, `memory_id: str|None`, `event_expiry_days: int=7`, `kms_key_arn: str|None`.
   - `CONFIG_SECTIONS`에 `"memory"` 추가, `ENV_KEYS`에 `LOVV_MEMORY_ENABLED / LOVV_MEMORY_ID / LOVV_MEMORY_EVENT_EXPIRY_DAYS / LOVV_MEMORY_KMS_KEY_ARN` 추가.
   - `from_env`에서 파싱. `enabled=False`가 기본 → import/테스트 영향 없음.

3. **`agentcore_entrypoint.py` — actor/session 추출 + config 주입**
   - `extract_actor_id(event)` 신설: `actorId / actor_id / userId(가명)` 키 우선, 없으면 `extract_request_id` 결과를 fallback 세션키로.
   - `handle_invocation`: `graph_config = {"configurable": {"thread_id": session_id, "actor_id": actor_id}}` 구성 → `harness.invoke(payload, request_id=, graph_config=graph_config)`.
   - ⚠ actor_id는 **이미 가명화된 값이라고 가정**(가명화는 Identity 경계 책임). 여기서 재식별·치환하지 않음.

4. **`harness.py` — checkpointer 주입 배선(자리만)**
   - `build_harness(..., checkpointer=None)` 파라미터 추가 → `build_langgraph(..., checkpointer=checkpointer)`로 전달(`harness.py:208`).
   - `build_live_harness`는 Phase 2에서 config 기반으로 checkpointer를 만들어 전달. Phase 1에서는 `None` 유지.

**Phase 1 검증**: 기존 테스트 전부 통과(동작 불변) + 신규 단위테스트 — entrypoint가 `configurable.thread_id/actor_id`를 올바르게 구성하는지, `build_langgraph(checkpointer=None)`이 기존과 동일 결과인지.

### Phase 2 — AgentCoreMemorySaver 실제 연결 (env-gated, 기본 off) · 변환 ②

선행: Phase 1 완료 + **state serde 복원기 구현**.

1. **의존성**: `pyproject.toml`에 `langgraph-checkpoint-aws` 추가(+ `uv.lock` 갱신). 버전 **pin**(preview/alpha 변동 대비).
2. **`adapters/agentcore_memory.py` 신설**: `build_checkpointer(config.memory) -> Saver | None`.
   - `config.memory.enabled`가 False면 `None` 반환(무상태 유지).
   - True면 `AgentCoreMemorySaver(memory_id=, ...)` 생성. `event_expiry`는 "재개 허용 최대기간"으로 해석(ADR 4.6).
3. **`state.py` — `unified_state_from_dict(d)` 복원기 추가**: `to_dict()`의 역함수. 중첩 schemas 재구성 포함. graph envelope의 serde 어댑터로 사용.
4. **`harness.build_live_harness`**: `build_checkpointer(resolved_config.memory)` → `build_harness(..., checkpointer=...)`.

**Phase 2 검증**: 직렬화 round-trip 단위테스트(`state == from_dict(to_dict(state))`) + (가능하면) AgentCore Memory 테스트 리소스로 thread 재개 통합 스모크. 로컬 한계상 일부는 모킹.

### Phase 3 — clarification → 진짜 interrupt/resume (별도 태스크) · 변환 ③

가장 크고 회귀 위험 높음(그래프 제어흐름 변경). **독립 태스크로 분리** 권장.

- 현재 `END_WAIT_USER → RESPONSE_PACKAGER`(종료) 분기를 LangGraph `interrupt()` 기반으로 재배선.
- 재개 입력(사용자가 고른 목적지)을 같은 `thread_id`로 resume.
- 선행: Phase 2(checkpointer 동작) 필수 — interrupt는 checkpointer를 요구.
- 영향 파일: `graph.py`(엣지/노드), `supervisor.py`(clarification 분기), `harness`(resume 진입점), 응답 패키저.

## 4. 변경 파일 요약

| 파일 | Phase 1 | Phase 2 | Phase 3 |
|------|---------|---------|---------|
| `graph.py` | checkpointer 파라미터 + compile | serde 어댑터 연결 | interrupt 재배선 |
| `config.py` | MemorySettings | — | — |
| `agentcore_entrypoint.py` | actor/session 주입 | — | resume 페이로드 처리 |
| `harness.py` | checkpointer 배선(None) | checkpointer 생성 연결 | resume 진입점 |
| `adapters/agentcore_memory.py` | — | 신설 | — |
| `state.py` | — | from_dict 복원기 | — |
| `pyproject.toml`/`uv.lock` | — | dep 추가·pin | — |

## 5. 미해결 / 확인 필요

- [ ] `langgraph-checkpoint-aws` 설치 버전의 `AgentCoreMemorySaver` 정확한 생성자 시그니처(`memory_id`, expiry, KMS 인자명) — **설치 후 검증**(신뢰도 중간).
- [ ] `eventExpiryDuration` 최종값(planning 세션 수명 기준) 산정.
- [ ] state serde: schemas 중첩 객체 전부 round-trip 가능한지 정밀 점검.
- [ ] AgentCore Memory 테스트 리소스 가용 여부(로컬 통합 스모크 범위 결정).

## 6. 권장 진행 순서

Phase 1 → (state serde 단위테스트) → Phase 2(env-gated) → 별도 태스크로 Phase 3.
Phase 1만으로도 ADR 변환 ①과 ②의 "주입 지점"이 확보되고, 무상태 기본은 그대로라 회귀 위험이 거의 없다.
