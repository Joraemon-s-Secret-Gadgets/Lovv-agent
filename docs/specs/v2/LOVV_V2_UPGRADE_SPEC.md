# Lovv AgentCore V2 — HITL 빌더 루프 + Memory 2티어 + Gateway 분리 통합 SPEC

---
title: Lovv AgentCore V2 — HITL 대화형 빌더 + Memory 2티어 + Gateway 분리
project: Lovv (로브)
status: 설계 (Draft)
date: 2026-06-23
baseline: V1 구현 완료 (212 tests pass · LovvAgentV1 배포 확인)
runtime: LovvAgentV1 (us-east-1) — V2 종료 후에도 단일 Runtime 유지
relates:
  - docs/specs/v1/LOVV_V1_OBSERVABILITY_CICD_SPEC.md
  - docs/specs/v1/LOVV_AGENTCORE_V1_FM_ROUTING_SPEC.md
  - docs/specs/v2/LOVV_AGENTCORE_MEMORY_CHECKPOINTER_SPEC.md
  - docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md
  - docs/reports/04_PARALLELIZATION.md
---

## 0. 한 줄 요약

V2는 V1의 단방향 추천 파이프라인을 **사용자가 장소를 턴마다 고르는 HITL 빌더 루프**로
진화시키고, **actorId 가명 ID 기반 Memory 2티어**(단기 ephemeral + 장기 persistent)를
도입하며, 결정론 `LinkBuilder`를 시작으로 **AgentCore Gateway 분리**를 개시한다.

## 1. 현재 상태 (V1 동결 기준선)

### 1.1 구현 완료 항목

| 항목 | 위치 | 상태 |
|---|---|---|
| LangGraph 그래프 (컴파일·실행) | `src/lovv_agent/graph.py` | ✅ |
| UnifiedAgentState 8 group | `src/lovv_agent/state.py` | ✅ |
| Intent Agent (결정론 + LLM 보강) | `agents/intent.py` + `harness.py` | ✅ |
| SupervisorRouter (결정론) | `agents/supervisor.py` | ✅ |
| CandidateEvidenceAgent (S3 Vectors + scoring) | `agents/candidate_evidence.py` | ✅ |
| FestivalVerifierAgent | `agents/festival_verifier.py` | ✅ |
| PlannerAgent (slot template + LLM explanation) | `agents/planner.py` | ✅ |
| ResponsePackager | `tools/response_packager.py` | ✅ |
| 노드별 FM 라우팅 (env config) | `config.py` + `adapters/aws_runtime.py` | ✅ |
| Bedrock Converse adapter | `adapters/bedrock_converse.py` | ✅ |
| AgentCore 배포 | `agentcore/agentcore.json` · 배포 확인 | ✅ |
| 테스트 | 212 passed | ✅ |

### 1.2 현재 그래프 플로우

```text
API request → request_state_from_api()
  → intent_agent → supervisor → candidate_evidence
  → supervisor → festival_verifier (or skip)
  → supervisor → planner → supervisor → response_packager → END
```

- 단방향 선형. 루프 없음.
- `END_WAIT_USER` = clarification 시에만 (terminal, 재개 불가).
- 무상태 (`builder.compile()` checkpointer 없음).
- actorId·Memory·interrupt/resume 미구현.

### 1.3 V1 동결 전략

V1 코드베이스를 **git tag `v1.0`으로 동결**하고, 이후 main에서 V2를 증분한다.

```text
git tag v1.0   ← V1 완성 스냅샷 (212 tests · 배포 확인)
main           ← V2 작업 진행 (같은 src/lovv_agent/ 위에 증분)
```

- V2 코드는 기존 `src/lovv_agent/` 패키지에 **추가**하는 방식. 별도 폴더 분리 없음.
- tools, adapters, repositories는 그대로 재사용.
- V1 one-shot 경로는 V2 빌더 안정화 후 점진 제거.
- 롤백 필요 시: `git checkout v1.0` → `app/LovvAgentV1/` 재배포.
- import 경로 변경 없음 (`from lovv_agent.tools.links import ...` 유지).

### 1.4 V2에서 변경하지 않는 것

- 단일 `LovvAgentV1` AgentCore Runtime (V2 안정화 후 이름 변경 검토).
- `us-east-1` 리전.
- 노드별 FM 라우팅 config 구조.
- V1 Observability·CI/CD 게이트.
- parity check (src ↔ app/LovvAgentV1).

## 2. V2 목표 (우선순위순)

| # | 목표 | 핵심 가치 |
|---|---|---|
| 1 | **HITL 빌더 루프** | 사용자가 장소를 직접 선택 → 만족도↑, 환각 차단 |
| 2 | **Memory 2티어** | 빌더 루프 interrupt/resume + 가명 프로필 영속 |
| 3 | **Gateway 분리 (LinkBuilder)** | AgentCore Gateway 패턴 검증 |
| 4 | **병렬화 (ThreadPool)** | 반경 Provider 후보 조회 지연 단축 |
| 5 | **Planner pure-code geo** | Haversine 동선, LLM 제거 (빌더 모드) |

## 3. HITL 빌더 루프 설계

### 3.1 전체 플로우

```text
[1회 셋업]
  Intent Agent ─────────────────┐  Profile Agent
  (action 파싱 · LLM)           │  (가명 · 시드 기여 · read only)
                                ▼
  Candidate Evidence · 도시 선정
  (공유 검색·스코어 코어 3층 · 1회)
                                │
                                ▼
  루프 시드: {도시, query_vector, anchor, budget}

[대화형 빌더 루프 · HITL · checkpointer interrupt/resume]
  ┌─────────────────────────────────────────────────┐
  │  Supervisor                                     │
  │  (결정론 코드 · Anchor 라우팅)                    │
  │                     │                           │
  │                     ▼                           │
  │  반경 Provider                                  │
  │  (radius gate + action 필터)                    │
  │                     │                           │
  │                     ▼                           │
  │  후보 제시 ‖ interrupt                           │
  │  (서브 윈도우 = 사이드바)                         │
  │       ┌─────────┼─────────┐                     │
  │       ▼         ▼         ▼                     │
  │  DynamoDB    지도 API   축제   ← 병렬 fan-out   │
  │       └─────────┼─────────┘                     │
  │                 ▼                               │
  │  사용자 픽 · 일정 추가                           │
  │  (PICK / REPLACE / EXCLUDE / FILTER)            │
  │                 │                               │
  │  next anchor ◄──┘  (loop)                       │
  └─────────────────┼───────────────────────────────┘
                    │ DONE
                    ▼
  Planner (축소)
  (Haversine geo · 구간 동선 · LLM 없음)
                    │
                    ▼
  설명 생성 (LLM 1회)
  (전체 흐름 설명 + 장소별 간단 설명 · grounded only)
                    │
                    ▼
  Response Packager → 타임라인
  (PLAN DETAIL)
```

상태: AgentCore Memory 체크포인터(ephemeral) → 영속 가명 프로필(커스텀 2티어·TTL→S3)

### 3.2 V1 경로와의 관계

V2 빌더 루프는 V1 one-shot 경로와 **같은 패키지** 안에 증분된다.
V1 one-shot은 빌더 안정화 확인 후 점진 제거한다.

```text
V2 개발 중: V1 one-shot + 빌더 루프 공존 (entry_type 분기)
V2 안정화 후: V1 one-shot 제거, 빌더가 유일한 경로
  └─ "자동 추천" 필요 시 → 빌더 mode="auto" (시스템 자동 PICK)
```

V1 원복 필요 시: `git checkout v1.0` → 배포.

### 3.3 사용자 액션 타입

| 액션 | 의미 |
|---|---|
| `PICK` | 제시된 후보 중 하나를 일정에 추가. anchor 갱신. |
| `REPLACE` | 기존 일정 항목을 다른 장소로 교체. |
| `EXCLUDE` | 특정 장소를 향후 제시에서 제외. |
| `FILTER` | 조건(테마·거리 등) 필터를 적용해 후보 재조회. |
| `DONE` | 루프 종료 → Planner로 전달. |

### 3.4 빌더 루프 State 추가

```python
@dataclass(slots=True)
class BuilderState:
    """HITL 빌더 루프 전용 state."""
    mode: str = "idle"                          # idle | active | done
    city_anchor: GeoPoint | None = None         # 현재 anchor 좌표
    radius_km: float = 3.0                      # 현재 검색 반경
    picks: list[dict[str, Any]] = field(default_factory=list)
    excluded_place_ids: list[str] = field(default_factory=list)
    current_candidates: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    max_turns: int = 15                         # 결정론 종료 가드
    fallback_level: int = 0                     # 0=기본, 1=반경확장, 2=솔직안내
    active_filters: dict[str, Any] = field(default_factory=dict)
```

### 3.5 soft floor 폴백 사다리

매 턴에서 3소스(DynamoDB ∥ 지도 API ∥ 축제)를 이미 병렬로 조회한다.
3소스 합산 결과가 soft floor 미달일 때만 폴백을 시도한다:

```text
3소스 fan-out 합산 < soft_floor (예: 3개 미만)
  │
  ├─ Level 1: 반경 확장 (N → 2N km)
  │    3소스 동일 조건으로 재조회 (확장된 반경)
  │    → 충족 시 제시, 미충족 시 Level 2
  │
  └─ Level 2: 솔직 안내
       "이 근처에 더 이상 추천할 장소가 없습니다. 다른 지역을 선택하시겠어요?"
       사용자에게 선택권 반환 (DONE 또는 anchor 변경)
```

지도 API는 별도 폴백 단계가 아니라 **매 턴 기본 소스**에 이미 포함되어 있으므로,
폴백은 "반경 키우고 재시도 → 솔직 안내" 2단계로 충분하다.

### 3.6 결정론 종료 가드

LLM evaluator를 **두지 않는다**. 코드 가드:
- `turn_count >= max_turns` → 솔직 안내 + 자동 done.
- `fallback_level >= 2` (사다리 소진) 이고 후보 0 → 솔직 안내 + 자동 done.
- `len(picks) >= trip_type_slot_count` → "일정이 가득 찼습니다" + 자동 done.

### 3.7 Intent Agent 책임 경계

Intent Agent는 **자연어 의도 해석이 필요한 입력**만 처리한다.
빌더 루프 내부의 단순 action(번호 선택 등)은 Supervisor가 코드로 처리한다.

**State 기반 프롬프트 분기:**

Intent Agent는 하나의 거대 프롬프트가 아니라, **현재 state에 따라 전용 프롬프트**를
선택해서 LLM을 호출한다. 분류는 코드(state 조회)로 결정론 처리.

```text
코드 분류 (LLM 호출 없이):
  state.builder.mode == "idle"           → initial 프롬프트
  state.needs_clarification == true      → clarification 프롬프트
  state.builder.mode == "active"         → condition_change 프롬프트
```

| state 조건 | 프롬프트 | 역할 | 출력 스키마 |
|---|---|---|---|
| `builder.mode == "idle"` | initial | 도시·테마·trip_type 추출 | `{action, city, themes, trip_type, ...}` |
| `needs_clarification == true` | clarification | 사용자 응답 해석 (예/아니오·선택지) | `{action, resolved_option, ...}` |
| `builder.mode == "active"` | condition_change | 어떤 조건을 어떻게 바꿀지 | `{action, target, new_value, ...}` |

이점:
- 각 프롬프트가 짧고 역할 단일 → 스키마 validation 안정.
- 분류에 LLM 불필요 → 항상 LLM 1회만 호출.
- 프롬프트 버전 관리 용이 (파일별 분리: `intent_initial.v1.md`, `intent_clarification.v1.md`, ...).

**Intent Agent가 처리하는 것:**

| 상황 | 예시 입력 | Intent Agent 출력 |
|---|---|---|
| 초기 진입 | "강릉 바다 여행 만들어줘" | action=start_builder, 도시·테마·trip_type 추출 |
| clarification 응답 | "축제 없이 진행해줘" | action=continue, include_festivals=false |
| 조건 변경 (루프 중) | "도시 바꿀래" / "테마 추가해줘" | action=reset_city / action=add_theme |
| 솔직 안내 후 응답 | "다른 지역으로 해줘" | action=change_city |

**Intent Agent가 처리하지 않는 것 (Supervisor 코드 매칭):**

| 상황 | 예시 입력 | Supervisor 처리 |
|---|---|---|
| 후보 선택 | "2번", "2" | PICK → candidates[1] |
| 장소 제외 | "3번 빼줘" | EXCLUDE → candidates[2] |
| 교체 | "1번을 다른 걸로" | REPLACE → picks[0] 교체 요청 |
| 완료 | "완료", "done" | DONE → 루프 종료 |

**분기 기준 (entrypoint에서):**

```text
resume 후 사용자 입력 도착
  │
  ├─ 키워드/번호 매칭 성공? (정규식: 숫자, "완료", "빼", "done" 등)
  │    → Supervisor 직접 처리 (단순 action)
  │
  └─ 매칭 실패 (자연어)
       → state 기반 프롬프트 선택 → Intent Agent LLM 1회
```

### 3.8 반경 Provider 후보 소스 (병렬 fan-out)

| 소스 | 역할 | 저장소 | 비고 |
|---|---|---|---|
| **DynamoDB 조회** | 도시 내 장소를 가져와 anchor 반경 Haversine 필터 | DynamoDB (기존 테이블) | 좌표·description 등 전체 메타 보유 |
| **지도 API** | 외부 검색 (Kakao/Google Places 반경) | 외부 API | 신규 의존성 |
| **축제** | DynamoDB 축제 시즌 후보 | DynamoDB (기존 테이블) | 기존 인프라 재사용 |

3소스 독립 → ThreadPoolExecutor 병렬 → 지연 ≈ max(三者).

**도시 선정 vs 반경 Provider 저장소 분리:**

```text
도시 선정 (1회)      → S3 Vectors 벡터 검색 (의미적 유사도로 도시 선택)
반경 Provider (매 턴) → DynamoDB 조회 + Haversine 후처리 (좌표 기반 반경 필터)
```

S3 Vectors는 좌표 반경 필터를 지원하지 않고, DynamoDB에 이미 좌표·description·
theme_tags 등 전체 장소 메타데이터가 있으므로, 반경 Provider는 DynamoDB를 소스로 한다.

**DynamoDB 반경 조회 방식:**
1. city_id (PK 또는 GSI)로 해당 도시 장소를 조회.
2. 코드에서 `haversine_km(anchor, place_coords) <= radius_km` 후처리 필터.
3. theme_tags·excluded_place_ids 추가 필터 적용.
   - `excluded_place_ids` = 사용자가 EXCLUDE한 장소 + **이미 picks에 있는 장소**
   - 매 턴 시작 시 `picks[].place_id`를 excluded_place_ids에 자동 합산.
4. 결과를 distance 순 정렬 후 제시.

**중복 병합 규칙:**
3소스 결과를 합산한 뒤 중복을 제거한다.

- **같은 소스 내 (DynamoDB↔DynamoDB)**: `place_id` 기준 dedup, distance 작은 쪽 유지.
- **크로스소스 (DynamoDB↔지도API)**: ID 체계가 다르므로 `place_id` 직접 비교 불가.
  → **좌표 근접(≤30m)** 단일 조건으로 동일 장소 판정. (같은 건물이면 좌표 거의 동일)
  → 동일 판정 시 **DynamoDB 쪽 우선** (메타데이터 풍부).
  → 미매칭은 각각 독립 후보로 유지 (지도 API 결과는 `source: "map_api"` 태그).
- **축제**: `festival_id` 기반 별도 엔티티. 장소와 충돌 없음.

### 3.9 Profile Agent (신규)

| 항목 | 내용 |
|---|---|
| 역할 | 가명 영속 프로필 **read** (루프 시드에 선호 기여) |
| 저장소 | DynamoDB 핫 (PK=actorId, TTL 없음) |
| LLM | 없음 (pure-code) |

**Write 타이밍:**

Profile Agent는 빌더 루프 **도중에 write 하지 않는다.** 선호도는 일정이 완성된
이후에만 의미가 있기 때문이다 (중간 PICK은 REPLACE/취소 가능, 미완성 루프는 탐색일 뿐).

```text
[빌더 루프]
  Profile Agent → READ (기존 선호를 시드에 반영)
  ...사용자 PICK/REPLACE/EXCLUDE...
  DONE

[일정 완성 후 · 비동기]
  Profile Writer → WRITE
    - 완성된 picks에서 선호 패턴 추출 (테마 빈도·선호 반경·선호 도시 등)
    - DynamoDB 프로필에 upsert (actorId PK)
    - raw picks 아닌 집계 요약만 적재 (build_memory_safe_summary 원칙)
```

| 시점 | 동작 | 이유 |
|---|---|---|
| 루프 시작 (1회) | READ | 시드에 기존 선호 반영 |
| 루프 중 | 접근 없음 | 미확정 상태에서 write 금지 |
| 일정 완성 후 | WRITE (비동기) | 확정된 선택만 프로필에 반영, 응답 지연 무영향 |

## 4. Memory 2티어 설계

### 4.1 아키텍처 개요

```text
actorId = 가명 ID · 전 계층 actor 격리

현재: checkpointer 미연결 → 무상태.
목표: 아래 메모리 정책 (기본 OFF · env-gated).

┌─────────────────────────────┐  ┌─────────────────────────────────────┐
│  단기 · Ephemeral (통합)     │  │  장기 · Persistent (분리)            │
│                             │  │                                     │
│  checkpoint blob            │  │  ① 개인화 프로필 · DynamoDB 핫       │
│  (interrupt / resume)       │  │     TTL 없음 · 가명 PK → Profile Agent│
│                             │  │                                     │
│  세션 컨텍스트              │  │  ② raw 이벤트 로그                   │
│  (checkpoint와 수명 공유)    │  │     DynamoDB TTL → S3 콜드           │
│                             │  │     Streams → Lambda·REMOVE → S3    │
│  공유 expiry                │  │                                     │
│  event_expiry_days=7 (1..365)│  │  보관기간·삭제권 직접 통제            │
│                             │  │  (AgentCore 장기 미사용)              │
└─────────────────────────────┘  └─────────────────────────────────────┘
  AgentCore Memory · env-gated · 기본 OFF
```

### 4.2 Hard line · 보안 경계

- 가명↔실제 매핑은 **AgentCore Identity 경계에만** 존재.
- raw PII 미저장 (전 저장소).
- 별도 KMS · 최소권한 IAM.
- 삭제권: DynamoDB + S3 양쪽 일괄 삭제 (actorId 기반).

### 4.3 langgraph-checkpoint-aws 컴포넌트 매핑

```text
pip install langgraph-checkpoint-aws
```

| SPEC 계층 | 패키지 컴포넌트 | AgentCore Memory 타입 | 역할 |
|---|---|---|---|
| 단기 Ephemeral | `AgentCoreMemorySaver` (checkpointer) | Short-term | 빌더 루프 interrupt/resume · graph state 저장·복원 |
| 장기 선호도 | `AgentCoreMemoryStore` + `UserPreferenceMemoryStrategy` | Long-term | Profile Agent read / Profile Writer write |
| 장기 이벤트 | 커스텀 (DynamoDB + S3) | AgentCore 미사용 | 보관기간·삭제권 직접 통제 |

**사용 패턴:**

```python
from langgraph_checkpoint_aws import AgentCoreMemorySaver, AgentCoreMemoryStore

# 1. Checkpointer (interrupt/resume)
checkpointer = AgentCoreMemorySaver(MEMORY_ID, region_name="us-east-1")
graph = builder.compile(checkpointer=checkpointer)

# 2. Long-term Store (선호도)
store = AgentCoreMemoryStore(MEMORY_ID, region_name="us-east-1")
# Profile Agent: store.search(namespace, query) → 선호도 조회
# Profile Writer: store.put(namespace, key, data) → 선호도 적재

# 3. Runtime config
config = {
    "configurable": {
        "thread_id": "session-123",   # → AgentCore session_id
        "actor_id": "pseudonym-abc",  # → AgentCore actor_id (가명)
    }
}
```

**왜 이렇게 분리하나:**
- `AgentCoreMemorySaver`는 graph state snapshot만 저장. 선호도 관리 불가.
- `AgentCoreMemoryStore`는 세션 간 유지되는 지식(선호도)을 저장·검색.
- raw 이벤트 로그는 AgentCore가 보관기간·삭제 정책을 직접 통제하기 어려우므로 커스텀 인프라.

### 4.4 활성화 단계 (게이트형)

```text
Phase 1                    Phase 2                      Phase 3
무상태 불변         →      serde + saver · env-gated  →  interrupt / resume
─────────────────────────────────────────────────────────────────────────
• build_langgraph(           • langgraph-checkpoint-aws    • END_WAIT_USER →
    checkpointer=None)         의존성 추가                    interrupt() 재배선
• actor_id/thread_id         • adapters/agentcore_memory.py• 빌더 루프 resume
    플러밍(진입→graph config)  • MemorySettings env-gated     동일 thread_id
• unified_state_from_dict()  • agentcore.json memories[]  • 기존 recommendation
    역직렬화 구현               등록                          경로 무영향
• serde round-trip 테스트    • serde 게이트 통과 선행
• 기존 212 테스트 통과       • enabled=False → None 유지
```

### 4.5 MemorySettings (config.py 추가)

```python
@dataclass(frozen=True, slots=True)
class MemorySettings:
    enabled: bool = False
    memory_id: str | None = None
    event_expiry_days: int = 7          # 1..365
    kms_key_arn: str | None = None
```

ENV: `LOVV_MEMORY_ENABLED` / `LOVV_MEMORY_ID` / `LOVV_MEMORY_EVENT_EXPIRY_DAYS` / `LOVV_MEMORY_KMS_KEY_ARN`

### 4.6 식별자 매핑

| 식별자 | LangGraph | AgentCore | 값 |
|--------|-----------|-----------|-----|
| thread | `configurable.thread_id` | `session_id` | 세션 식별자 |
| actor | `configurable.actor_id` | `actor_id` | **가명 ID** |
| 만료 | — | `eventExpiryDuration` | `event_expiry_days` |

### 4.7 장기 Persistent 계층 상세

**① 개인화 프로필 (DynamoDB 핫)**
- PK = actorId (가명). TTL 없음.
- Profile Agent가 read. 빌더 루프 시드에 선호 기여.
- 결과 요약만 적재 (`build_memory_safe_summary` 원칙).

**② raw 이벤트 로그 (DynamoDB TTL → S3 콜드)**
- DynamoDB에 이벤트 적재 (TTL = N일).
- DynamoDB Streams → Lambda (REMOVE + dynamodb principal 필터) → S3 콜드.
- S3 파티션: `actorHash/날짜/`.
- SSE-KMS 암호화.
- 삭제가 아니라 **가명 유지 적재** (비익명 · 분석·재하이드레이션용).

**삭제권 플로우:**
사용자 요청 시 → actorId로 DynamoDB + S3 prefix 일괄 삭제.

## 5. Gateway 분리 설계

### 5.1 1차 대상: LinkBuilder

| 항목 | 내용 |
|---|---|
| 대상 함수 | `tools/links.py` → `build_default_city_links()` |
| 이유 | 결정론 · 무부작용 · AWS 미호출 · 입력 단순 |
| Gateway tool 이름 | `build_city_links` |
| inputSchema | `{ cityNameKo: string, country: string }` |
| outputSchema | `{ map: object, staySearch: object, foodSearch: object }` |

### 5.2 구현 구조

```text
src/lovv_agent/gateway/
  __init__.py
  link_builder.py         # Gateway handler adapter

agentcore/agentcore.json
  → agentCoreGateways[] 에 build_city_links 등록

tests/test_gateway_link_builder.py
```

### 5.3 후속 Gateway 대상

- `ScoringTool` — Gateway overhead 측정 후.
- 반경 Provider 후보 조회 — HITL 안정화 후.
- S3 Vector 검색 / DynamoDB enrichment — IAM·지연 검증 후.

## 6. 병렬화 설계

### 6.1 대상

| 함수 | 현재 | V2 |
|---|---|---|
| `_retrieve_by_theme()` | `for theme` 순차 | ThreadPoolExecutor 병렬 |
| `enrich_final_places()` | 장소별 순차 GetItem | ThreadPool 또는 BatchGetItem |
| radius_provider fan-out | — | DB ∥ 지도 API ∥ 축제 병렬 |

### 6.2 방식

- asyncio 아님 — boto3 동기·I/O 바운드 → ThreadPool (GIL 네트워크 대기 중 해제).
- `LOVV_SEARCH_MAX_PARALLELISM` env knob (기본 8).
- boto3 `Config(max_pool_connections=N)` 상향 (기본 10 → themes 수 이상).
- 부분 실패 허용 (future 예외 수집 → 워닝 기록, 성공 결과만 병합).

## 7. Planner pure-code geo 설계

### 7.1 빌더 모드 Planner + 설명 생성

| 단계 | LLM | 역할 |
|---|---|---|
| 빌더 루프 중 (매 턴) | ❌ | 후보 조회·제시는 pure-code |
| DONE 후 Planner | ❌ | 동선 정렬(픽 순서 유지)·Haversine 구간 거리 계산 |
| DONE 후 **설명 생성** | ✅ 1회 | 전체 흐름 설명 + 장소별 간단 설명 |

**설명 생성 LLM 호출 입력 (grounded only):**

```text
입력:
  - picks[]: 확정된 장소 리스트 (place_id, name, 좌표)
  - 각 장소 DynamoDB metadata (description, theme_tags 등)
  - 구간 거리: haversine_km 계산 결과
  - 사용자 테마: active_required_themes
  - trip_type, travel_month

출력:
  - trip_summary: "바다를 따라 이동하는 강릉 당일 여행입니다..."
  - place_descriptions[]: 각 장소 1~2줄 설명
```

**규칙:**
- 입력은 확정된 사실(DB metadata + 좌표)만. 없는 장소·없는 정보 생성 금지.
- DynamoDB description이 있으면 그것을 기반으로 다듬기. 없으면 metadata만으로 최소 설명.
- 설명에 가격·영업시간·리뷰 등 미검증 정보 포함 금지.
- schema validation + retry (기존 V1 structured-output 패턴 재사용).

| 항목 | 빌더 모드 | 기존 recommendation 모드 (V1) |
|---|---|---|
| 동선 결정 | 픽 순서 = 동선 (사용자 의지) | slot template 배치 |
| 구간 거리 | Haversine 계산 → `distance_km` | 없음 |
| 설명 생성 | LLM 1회 (DONE 후) | 기존 explanation_runtime 유지 |
| 검증 | 정합성 게이트 인라인 (코드) | 기존 validation 유지 |

### 7.2 Haversine 유틸

```python
import math

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))
```

## 8. 단계 계획 (Phasing)

```text
V2-A  기반 준비 + Memory Phase 1 (무상태 불변)
  ├─ BuilderState 정의 + UnifiedAgentState 확장
  ├─ unified_state_from_dict() 역직렬화 구현
  ├─ serde round-trip 테스트
  ├─ build_langgraph(..., checkpointer=None) 파라미터 추가
  ├─ handle_invocation → actor_id/thread_id 추출 → graph_config 배선
  ├─ MemorySettings 추가 (enabled=False 기본)
  ├─ haversine_km 유틸 추가
  ├─ _retrieve_by_theme → ThreadPool 병렬화
  ├─ config.py LOVV_SEARCH_MAX_PARALLELISM 추가
  ├─ boto3 max_pool_connections 상향
  └─ 기존 212 테스트 전부 통과 확인

V2-B  Gateway 분리 (LinkBuilder)
  ├─ src/lovv_agent/gateway/link_builder.py
  ├─ agentcore.json agentCoreGateways 등록
  ├─ test_gateway_link_builder.py
  ├─ agentcore validate 통과
  └─ deploy dry-run 확인

V2-C  Memory Phase 2 + HITL 빌더 루프 (핵심)
  ├─ langgraph-checkpoint-aws 의존성 추가 (pin)
  ├─ adapters/agentcore_memory.py 신설
  ├─ agentcore.json memories[] 등록
  ├─ serde 게이트 통과 확인
  ├─ entry_type="builder" 분기 (graph.py)
  ├─ Profile Agent 구현 (READ: DynamoDB 핫 · 가명 PK)
  ├─ Profile Writer 구현 (WRITE: 일정 완성 후 비동기 upsert)
  ├─ radius_provider 노드 구현 (3소스 fan-out)
  ├─ interrupt()/resume() 빌더 루프 적용 (Memory Phase 3)
  ├─ 사용자 액션 처리 (PICK/REPLACE/EXCLUDE/FILTER/DONE)
  ├─ 빌더 전용 Planner (pure-code geo)
  ├─ 설명 생성 프롬프트 구현 (LLM 1회 · grounded only)
  ├─ Response Packager → 타임라인 패키징
  ├─ 빌더 루프 통합 테스트
  └─ 기존 recommendation 경로 회귀 테스트

V2-D  장기 Persistent + 안정화
  ├─ DynamoDB 이벤트 로그 테이블 + TTL
  ├─ Streams → Lambda → S3 콜드 파이프라인
  ├─ 삭제권 플로우 (actorId 기반 일괄)
  ├─ 빌더 전용 메트릭 (루프 길이·폴백·정합성·tokens/turn)
  ├─ enrich_final_places BatchGetItem/ThreadPool
  └─ V1 CI/CD 게이트에 빌더 smoke 추가
```

## 9. 비용 영향

| 항목 | 분류 | 비고 |
|---|---|---|
| Gateway (LinkBuilder) | 거의 0 | 결정론·무부작용 |
| 병렬화 ThreadPool | 절감 | 지연↓, API call 수 동일 |
| AgentCore Memory (단기) | 증가(소) | env-gated · interrupt/resume 시 checkpoint rw |
| DynamoDB 이벤트 + Streams/Lambda | 증가(소~중) | 이벤트량 비례 |
| S3 콜드 | 증가(소) | 장기 단가↓ |
| 지도 API (신규) | 증가(중) | fan-out 의존 |
| Haversine / Planner LLM 제거 | **절감** | 루프 중 LLM 0회, DONE 후 1회만 |
| Profile Agent (DynamoDB read) | 증가(미미) | 가명 PK GetItem 1회 |
| Profile Writer (비동기 upsert) | 증가(미미) | 일정 완성 시에만 1회 |

## 10. 경계 / 불변

- V1 `v1.0` 태그로 동결. 롤백은 태그 checkout + 재배포.
- V2는 같은 `src/lovv_agent/` 패키지에 증분. 별도 폴더 없음.
- V1 one-shot 경로는 빌더 안정화 후 점진 제거.
- 단일 AgentCore Runtime 유지 (V2 안정화 후 이름 변경 검토).
- `us-east-1` 리전.
- `actorId` = 가명 ID. 전 계층 격리. 재식별 불가.
- raw PII · 자격증명 · aws-targets.json 커밋 금지.
- Gateway는 기존 추천 동작을 변경하지 않는다.
- 빌더 루프 Supervisor = 결정론 코드 (LLM evaluator 추가 금지).
- 후보 제시 시 환각 금지 — DB/DynamoDB/지도API 검색 결과만 제시.
- 가명↔실제 매핑 테이블은 본 코드 경로에서 접근 금지.

## 11. 미해결 / 확인 필요

- [ ] 반경 초기값 N km · 확장 배수 · 최대 반경.
- [ ] 빌더 루프 최대 턴 수 (15?).
- [ ] soft floor 최소 후보 수 (3?).
- [ ] 빌더 모드 진입 API 설계 (entry_type 확장 vs 별도 endpoint).
- [ ] 지도 API 선택 (Kakao/Google) · timeout · fallback.
- [ ] `event_expiry_days` 최종값.
- [ ] `AgentCoreMemorySaver` 생성자 시그니처 (설치 버전 검증).
- [ ] LangGraph interrupt/resume AgentCore Lambda 환경 호환 여부.
- [ ] Gateway authorizer (AWS_IAM vs NONE).
- [ ] Profile Writer 비동기 실행 방식 (같은 Lambda 내 post-response vs SQS/EventBridge).
- [ ] Cognito JWT 검증 책임 경계 (AgentCore Identity vs entrypoint).
- [ ] `PSEUDONYM_SECRET` 로테이션 주기 (가명 HMAC 필요 시).
- [ ] 콜드 S3 도메인 분리(옵션) 채택 여부.
- [ ] 삭제권 진입점 (앱 vs Cognito pre-deletion 훅).

## 12. 성공 기준

1. `entry_type="builder"` 요청 시 interrupt → 후보 제시 → 사용자 PICK →
   resume → 반복 → DONE → 최종 타임라인 반환이 동작한다.
2. V1 태그(`v1.0`)에서 기존 212 테스트가 그대로 통과한다.
3. Gateway `build_city_links` tool이 AgentCore에 등록·호출·반환된다.
4. Memory Phase 1 완료 후 무상태 동작 불변 (기존 테스트 100% 통과).
5. serde round-trip 게이트: `s == unified_state_from_dict(s.to_dict())` 모든 그룹.
6. 동일 thread_id로 interrupt → resume이 동작한다 (Memory Phase 2+3).
7. Profile Agent가 가명 PK로 프로필을 read 하고, 일정 완성 후 Profile Writer가
   확정된 선호를 비동기 write 한다.
8. 병렬화 후 기존 테스트 결과 동일.
9. Haversine 구간 거리가 빌더 출력에 포함된다.
10. 결정론 종료 가드가 무한 루프를 방지한다.
11. 삭제권: actorId 기반 DynamoDB + S3 일괄 삭제가 동작한다 (V2-D).

> 본 문서는 V2 통합 SPEC이다. V1 관측·CI/CD 게이트 통과를 전제로 각 단계를 진행하며,
> "미해결" 항목은 해당 단계 착수 전 확정한다.
