# V2 아키텍처 결정 보고서

## 문서 정보

| 항목 | 내용 |
| --- | --- |
| 문서 상태 | Working Draft (검토·토론 진행 중) |
| 기준일 | 2026-06-25 |
| 기준 코드 | `src/lovv_agent` V1 (212 tests pass · LovvAgentV1 배포 확인) |
| 관련 문서 | `V2_CITY_PLANNER_SEPARATION_DECISIONS.md`, `LOVV_V2_UPGRADE_SPEC.md` |
| 목적 | V2 설계 토론에서 합의된 방향과 미확정 사항을 정리. Spec 이전 단계의 설계 점검 문서. |

---

## 1. V2 방향 요약 (V2 SPEC 대비 변경점)

`LOVV_V2_UPGRADE_SPEC.md`의 HITL 빌더 루프 설계에서 다음과 같이 방향을 전환한다.

| V2 SPEC (기존) | 실제 방향 |
|---|---|
| HITL 빌더 루프 (PICK/REPLACE/EXCLUDE 매 턴) | **폐기** |
| 사용자가 후보에서 번호 선택 | **폐기** |
| 반경 Provider (DynamoDB + 지도API + 축제 fan-out) | **폐기** |
| 빌더 모드 Planner (pure-code geo만) | **폐기** |
| Profile Agent (가명 선호 read) | **유지** |
| Memory (AgentCoreMemorySaver) | **유지** — 일정 생성 → 자연어 수정 → resume 루프 |
| Gateway 분리 (LinkBuilder) | **유지** (우선순위 하향) |
| 병렬화 (ThreadPool) | **유지** |

핵심 변경: 사용자는 생성된 일정에 대해 **자연어로 수정을 요청**한다. AgentCoreMemorySaver가 checkpoint를 관리하고, thread_id 기반 resume으로 수정 루프를 구현한다.

---

## 2. V2 실제 Flow

```
[초회 생성]
  Intent Agent
  → Candidate Evidence (city_select subgraph: 도시 선정 + 관광지 pool)
  → Festival Verifier (optional)
  → Planner (일정 생성)
  → Response Packager → 일정 반환
  → interrupt (AgentCoreMemorySaver checkpoint 저장)

[수정 루프 · 자연어 · resume]
  사용자: "2일차 오후를 카페로 바꿔줘" / "축제 넣어줘" / "순서 바꿔줘"
  → resume (thread_id)
  → 수정 Intent 해석 (어떤 슬롯을 어떻게 바꿀지)
  → 필요 시 DynamoDB 재인출 (city 고정)
  → Planner 재실행 (부분/전체)
  → 수정된 일정 반환 + interrupt
  → ...반복...
  → 입력이 멈추고 일정 시간 후 종료 (TTL)
```

---

## 3. 결정 사항

### 3.1 CandidateEvidencePackage 분리

현재 `CandidateEvidencePackage`는 도시 선정 결과와 일정 재료를 한 덩어리에 섞어 놓은 구조다. V2에서는 **두 개로 분리**한다.

**분리 이유:**
- 수정 루프에서 "장소 바꿔줘"는 PlacePool만 갱신, "도시 바꿔줘"는 CitySelection부터 재실행 — 분리되어 있어야 자연스러움
- Planner가 실제로 필요한 필드는 6개뿐 (status, selected_city, places, festivals, external_link_themes, reason_claims)
- 나머지는 디버그 audit이거나 도시 선정 결과

**분리 구조:**

```python
@dataclass(frozen=True, slots=True)
class CitySelectionResult:
    """도시 선정 결과. 수정 루프 동안 불변 (도시 변경 요청 시에만 재생성)."""
    selected_city: SelectedCity
    city_rankings: tuple[dict[str, Any], ...]
    mode: str
    city_anchor: dict[str, Any] | None
    retrieval_summary: dict[str, Any]       # 카운트 요약만

@dataclass(slots=True)
class PlacePool:
    """수정 루프에서 갱신되는 장소 후보 풀."""
    city_id: str
    scored_candidates: list[dict[str, Any]]  # 전체 scored pool
    recommended: list[dict[str, Any]]        # 현재 배치 대상
    reserve: list[dict[str, Any]]            # 미사용 후보
    coverage_audit: dict[str, Any]
    exhausted: bool = False                  # 재인출 트리거
```

**Planner가 받는 input:**

```python
@dataclass(frozen=True, slots=True)
class PlannerInput:
    """Planner가 일정을 만들기 위해 필요한 최소한의 input."""
    status: str                                    # ok | insufficient_candidates
    selected_city: SelectedCity
    places: tuple[dict[str, Any], ...]             # 배치할 관광지
    festival_candidates: tuple[dict[str, Any], ...]
    external_link_themes: tuple[str, ...]
    candidate_reason_claims: tuple[CandidateReasonClaim, ...]
```

**V1 호환:** 기존 `CandidateEvidencePackage`는 V1 경로 존속 동안 유지. V2 수정 루프는 분리된 구조만 사용.

**간소화된 필드 행선지:**

| 기존 필드 | V2에서 행선지 |
|-----------|--------------|
| `city_rankings` | `CitySelectionResult` |
| `recommended_places` | `PlacePool.recommended` |
| `reserve_places` | `PlacePool.reserve` |
| `retrieval_audit` | telemetry span attribute |
| `candidate_counts` | telemetry span attribute |
| `fallback_audit` | telemetry span attribute |
| `warnings` | telemetry span attribute |
| `festival_seed_audit` | telemetry span attribute |
| `city_anchor` | `CitySelectionResult` |
| `coverage_audit` | `PlacePool.coverage_audit` (축소) |

### 3.2 city_select Subgraph 도입

`CandidateEvidenceAgent.run()`의 내부 로직을 **LangGraph subgraph**로 분해한다.

**목적:**
- 수정 루프에서 **부분 재실행 진입점**을 명확히 함
- retrieval만, scoring만 독립 테스트 가능
- 나중에 A2A로 별도 Runtime 분리 시 interface가 이미 준비됨

**Subgraph 구조 (2-node):**

```
[Main Graph]
  Intent → Supervisor → city_select (subgraph) → Supervisor → Planner → ...

[city_select subgraph 내부]
  retrieval_node
    - search_attractions (Gateway tool) × 테마 수
    - merge 중복 제거
    - 도시별 그룹핑 + 테마 AND gate (prune)
       │
       ▼
  scoring_and_selection_node
    - score_place() (도시 내 후보 채점)
    - score_city() (도시 순위, congestion 포함)
    - 도시 확정 (rank 0, capacity 강등 없음)
    - seed 추출 (테마 라운드로빈 × top)

  출력: CitySelectionResult + seed_candidates
```

**V1에서 제거된 것:**
- `select_primary_with_theme_quotas` — Pass 2가 대체
- `candidate_reason_claims` (LLM 생성) — 삭제. 설명은 Planner 완료 후 1회로 통합
- `recommended_places` / `reserve_places` — PlacePool(Pass 2)이 대체
- `coverage_audit` (quota 관련) — 삭제

**Subgraph State:**

```python
class CitySelectState(TypedDict):
    # 입력
    candidate_input: CandidateEvidenceInput
    query_vector: list[float]
    soft_query_vector: list[float] | None
    theme_weights: dict[str, float] | None  # Profile에서 주입

    # retrieval → scoring
    retrieved_candidates: list[dict]
    pruned_groups: dict[str, list]

    # 최종 출력
    city_selection: CitySelectionResult | None
    seed_candidates: list[dict]  # 테마 매칭 상위, day 수 정도

    # 제어
    status: str  # ok | no_candidate | error
    failure_signal: str | None
```

**수정 루프에서 subgraph 재활용:**

```
[수정: "다른 장소로 바꿔줘"]
  → city_select 재실행 불필요. Pass 2 재인출만.

[수정: "도시 바꿔줘"]
  → city_select subgraph 전체 재실행
  → 기존 query_vector 재사용 가능 (여행 의도 동일)
```

### 3.3 scoring.py 개선 (V1·V2 공통)

`V2_CITY_PLANNER_SEPARATION_DECISIONS.md` §4의 scoring 개선은 V1·V2 양쪽에서 사용되므로 **즉시 구현 가치가 있다.**

| 항목 | 변경 내용 |
|------|-----------|
| `semantic_evidence` | `÷budget` → `÷max(1, min(budget, n))` |
| `candidate_sufficiency` | 제거 (또는 viability flag로 분리, ranking 제외) |
| `_select_city_rank_index` | capacity 강등 제거, 항상 rank 0 반환 |
| `_rank_cities` tiebreaker | `(city_score, candidate_count)` → `city_score`만 |
| `congestion_penalty` | 기존 훅 활성화 (visitor stats 데이터 주입) |
| `theme_match_score` | 이진 0.2 → `theme_weights[theme]` 비례 |
| `theme_balance` | Shannon 엔트로피 → profile 가중 목표 분포 divergence |

### 3.4 Memory 저장 범위

#### 2티어 구조

```
단기 메모리: AgentCore Memory (AgentCoreMemorySaver)
  - 용도: 수정 루프 interrupt/resume, graph state checkpoint
  - 수명: 세션 단위 (idle timeout 후 만료)
  - 저장: 전체 UnifiedAgentState (PlacePool + vector 캐시 포함)

장기 메모리: DynamoDB TTL
  - 용도: 사용자 Profile (theme_weights 등 선호도)
  - 수명: TTL 기반 (장기 유지, 갱신 시 리셋)
  - 저장: 집계 요약만 (build_memory_safe_summary 원칙)
  - PK: actorId (가명)
```

#### 단기 (AgentCore Memory)

**결정: 전체 UnifiedAgentState를 checkpoint에 저장한다.**

이유:
1. AgentCoreMemorySaver는 LangGraph graph state 전체를 blob으로 직렬화 — 부분 저장은 커스텀 serde 없으면 불가
2. 20-60KB/턴으로 DynamoDB 400KB item limit 안에 충분
3. resume 시 어떤 수정이든 가능하려면 전체 context 필요

**구현 요구사항:**
- `unified_state_from_dict()` 역직렬화 함수 구현 (`to_dict()` ↔ `from_dict()` round-trip)
- `conversation.messages` 누적 관리: 슬라이딩 윈도우 또는 summary 압축
- `serving.response_payload`는 resume 시 None으로 초기화 (재생성 가능)
- schema version 필드 추가 (checkpoint 복원 호환)

#### 장기 (DynamoDB — Profile 전용 테이블 분리)

**용도:** Profile Agent가 읽고, Profile Writer가 쓰는 사용자 선호도 저장.

**테이블 분리 이유:**
- 도메인 데이터(TourKoreaDomainData)와 개인화 데이터는 수명·권한·확장 패턴이 다름
- TTL은 Profile에만 필요 (도메인 데이터는 영구)
- IAM 최소 권한 분리 (search Lambda → Table1 read only, Profile Agent → Table2 read/write)
- 사용자 삭제 시 Table2만 삭제하면 안전

```
Table 1: TourKoreaDomainData (기존)
  - 관광지 상세, 축제, 도시 등
  - TTL 없음 (영구)
  - 읽기 전용 (Gateway tool이 조회)

Table 2: LovvUserProfile (신규)
  - PK: ACTOR#{actorId} (가명 ID)
  - SK: PROFILE#v1
  - PITR 활성화
  - On-Demand capacity
```

**Table 2 스키마:**

```
LovvUserProfile
  PK: ACTOR#{actorId}
  SK: PROFILE#v1

  Attributes:
    theme_weights: Map              ← 테마별 선호 가중치
    last_updated: String (ISO)
    trip_count: Number
    created_at: String (ISO)
    schema_version: Number

  향후 확장 (SK 추가):
    SK: HISTORY#{timestamp}         ← trip 이력 요약
    SK: PREFERENCE#city             ← 선호 도시
    SK: PREFERENCE#companion        ← 동행 유형
```

**삭제 정책:**

```
hard_delete: 사용자 명시적 삭제 요청 시에만
  - actorId 기반 모든 SK 삭제 (Query PK → BatchDelete)
  - cold start로 복귀
```

**동작:**
- 일정 완성 시 → theme_weights 갱신 + last_updated 갱신
- 사용자가 삭제 요청 → hard delete → 다음 접속 시 빈 profile (cold start)

**Write 시점:** 일정 완성 후 비동기 (수정 루프 중에는 write 안 함).
**Read 시점:** 초회 생성 시 Profile Agent가 1회 read → theme_weights를 city_select + Planner에 주입.

**규모 확인 후 검토:** Global Tables (리전 복제), 일일 자동 백업, soft TTL(stale 감쇠) 도입.

### 3.5 Profile Agent → scoring 주입 경로

**결정: Candidate Evidence 호출 시 파라미터로 주입한다.**

```
Profile Agent (read) → theme_weights
  ↓
city_select subgraph 호출 시 CitySelectState.theme_weights로 전달
  ↓
scoring_agent가 score_city(), score_place() 호출 시 가중치 적용
```

Profile이 없거나 비어있으면 균등 가중(현재 동작 유지).

### 3.6 수정 시 재인출

**결정: DynamoDB lookup을 별도로 수행한다.**

수정 요청에서 "다른 장소"가 필요할 때:
1. `PlacePool.reserve`에서 먼저 탐색
2. reserve 소진 시 (`PlacePool.exhausted = True`) → DynamoDB 재인출 (city_id 고정)
3. S3 Vector 재검색이 아닌 DynamoDB 직접 조회 (좌표 + theme_tags 필터)

이는 분리 결정 문서 §5의 "Pass-2 재인출"을 수정 루프 맥락에서 축소 적용한 것이다.

### 3.7 수정 횟수 제한 / 종료 조건

**결정:**
- 수정 횟수 제한: **없음**
- 종료 조건: **입력이 멈추고 일정 시간 후 자동 종료 (TTL 기반)**
  - AgentCoreMemorySaver의 `event_expiry_days` 설정으로 제어
  - 세션 idle timeout은 별도 설정 (front에서 관리 가능)

### 3.8 개발 방식: 모듈 분리 + 단일 배포

**결정: 같은 repo에서 모듈 분리 개발 → CI/CD로 단일 AgentCore Runtime 배포.**

```
src/lovv_agent/
  agents/city_selection/     ← 독립 개발·테스트 가능
  agents/planner/            ← 독립 개발·테스트 가능
  agents/intent/             ← 독립 개발·테스트 가능
  shared/                    ← 공유 schemas, tools

CI/CD:
  pytest tests/unit/city_selection/
  pytest tests/unit/planner/
  pytest tests/integration/
  → build → deploy (단일 LovvAgentV1 Runtime)
```

별도 패키지 분리(방식 B)는 팀 확장 시 검토. 현재 시점에서는 모듈 분리(방식 A)로 충분.

### 3.9 Subgraph = Agent-to-Agent 경계

city_select subgraph 분리 자체가 A2A-ready 설계다. 별도 AgentCore Runtime으로 나누는 것은 고려하지 않는다.

- subgraph의 input/output 계약이 명확하면 내부적으로 agent-to-agent 커뮤니케이션과 동일한 효과
- 런타임 분리 없이도 독립 개발·테스트·부분 재실행이 가능
- 진짜 런타임 분리가 필요해지는 시점(팀 분리, 외부 서비스 재사용)은 현재 로드맵에 없음

### 3.11 I/O Tool → AgentCore Gateway (Lambda) 전환

#### 결정

외부 데이터를 취득하는 I/O 작업은 **AgentCore Gateway의 Lambda target**으로 배포한다. V2에서 코드를 재구조화하는 시점에 경계를 Gateway로 잡는다.

#### 대상 Tool (Gateway Lambda)

| Tool 이름 | 하는 일 | Lambda → 호출 대상 |
|-----------|---------|-------------------|
| `search_attractions` | S3 Vector 벡터 검색 (query_vector + filters) | S3 Vectors API |
| `search_place_pool` | Pass 2 인출 (city 고정 + theme off) | S3 Vectors API |
| `lookup_festival_seeds` | 축제 후보 조회 (month + city) | DynamoDB Query |
| `enrich_place_details` | 장소 상세 조회 (pk/sk batch) | DynamoDB BatchGet |
| `embed_query` | 텍스트 → embedding vector 생성 | Bedrock Titan |

#### 인프로세스 유지 (Gateway 아님)

| 모듈 | 이유 |
|------|------|
| ScoringTool | 순수 계산. 네트워크 왕복 낭비 |
| CandidateSelectionHelper | 순수 계산 |
| Planner 배치 로직 | 순수 계산 + state 의존 |
| Supervisor | orchestration 핵심, 밀결합 필수 |
| PlannerScoringHelper | 순수 계산 (base_score + context_score) |

#### 아키텍처

```
LovvAgentV1 Runtime (LangGraph orchestrator)
  │
  ├── Intent Agent (인프로세스)
  ├── Supervisor (인프로세스)
  ├── city_select subgraph (인프로세스 orchestration)
  │     └── 내부에서 Gateway tool 호출
  ├── Scoring / Selection (인프로세스)
  ├── Planner 배치 로직 (인프로세스)
  │
  └── AgentCore Gateway (MCP endpoint)
        ├── search_attractions      → Lambda (S3 Vectors)
        ├── search_place_pool       → Lambda (S3 Vectors)
        ├── lookup_festival_seeds   → Lambda (DynamoDB)
        ├── enrich_place_details    → Lambda (DynamoDB)
        └── embed_query             → Lambda (Bedrock Titan)
```

#### 판단 기준: Gateway로 분리하는 것

- **I/O bound + stateless** → Gateway Lambda
- **순수 계산** → 인프로세스 유지
- **LLM 호출** → 인프로세스 (Bedrock Converse는 Runtime 내에서 직접 호출, embedding만 별도)

#### 이점

- **관심사 물리적 분리:** 데이터 취득 = Gateway tool, 로직 = 인프로세스
- **독립 배포:** 검색 쿼리 튜닝 / DynamoDB 스키마 변경 시 Lambda만 업데이트
- **독립 IAM:** Lambda별 최소 권한 (search → S3 Vectors만, enrich → DynamoDB만)
- **재사용:** 다른 agent나 서비스에서 같은 Gateway endpoint 호출 가능
- **Gateway 부가기능:** interceptor, 인증, 로깅, 정책 자동 적용
- **Observability:** tool별 호출 수/지연/에러가 Gateway 레벨에서 자동 측정

#### 기존 코드와의 관계

현재 `DestinationSearchTool`, `DynamoLookupTool`은 이미 stateless 함수 기반. Lambda handler를 감싸는 것으로 전환 가능:

```python
# 현재 (인프로세스)
result = destination_search.search_candidates(query_vector, city_id=..., theme=...)

# V2 (Gateway MCP 호출)
result = await gateway_client.call_tool("search_attractions", {
    "query_vector": query_vector,
    "city_id": city_id,
    "theme": theme,
})
```

#### 운영 고려사항

- Lambda cold start: 같은 리전 내 +20-50ms. provisioned concurrency로 완화 가능
- Payload 크기: query_vector(~4KB) + 결과(~20-40KB) → Lambda 6MB limit 내 충분
- 인증: Gateway OAuth (Cognito) 또는 SigV4

### 3.10 V2 Planner 설계 — 최초 생성

#### 핵심 원칙

**도시 선정과 일정은 별개다.** city_select에서 인출한 후보(테마 hard gate)를 일정에 그대로 쓰면 편중된 일정이 된다. 일정 배치용 장소는 **별도 인출(Pass 2: city 고정 + theme off)**로 확보한다.

#### 2-pass 검색 구조

```
Pass 1 (city_select subgraph):
  목적: "이 도시가 이 테마에 적합한가" 판단
  방식: theme hard gate → 도시 선정
  산출: CitySelectionResult + seed candidates (테마 매칭 상위, day 수 정도)

Pass 2 (Planner 진입 시):
  목적: "이 도시에서 실제로 갈 만한 최고의 장소는?"
  방식: city_id 고정 + theme off (또는 profile 테마 soft 필터)
  산출: PlacePool (해당 도시의 폭넓은 관광지 ~30-50개)
```

#### seed의 역할

seed = **"이 도시를 선택한 이유가 되는 장소"**
- Pass 1에서 테마 매칭 상위로 선정
- 일정에 반드시 포함 (도시 선정 근거)
- 각 day의 anchor point (동선 기준)
- 단, 일정 전체를 seed 계열로만 채우지 않음

#### seed 배치 전략

seed 수 = day 수 - 축제가 차지한 day 수

```
seed 선택:
  1. 축제가 없는 각 day에 1개씩
  2. 테마를 라운드로빈으로 순회
  3. 각 테마에서 score 최상위 1개를 해당 day seed로
  4. 테마 수 < day 수: 라운드로빈 회귀 (같은 테마에서 2번째 best)
  5. 테마 수 > day 수: score 상위 테마 우선 배정, 나머지는 채우기에서 커버
```

예시:
```
themes=["자연","문화","체험"], 3d2n, 축제 없음:
  Day1 seed: 자연 top-1 / Day2 seed: 문화 top-1 / Day3 seed: 체험 top-1

themes=["자연","문화"], 3d2n, 축제=Day2:
  Day1 seed: 자연 top-1 / Day2: 축제(seed 대체) / Day3 seed: 문화 top-1
```

#### 배치 전체 과정

```
Step 1: 골격 생성
  trip_type → 슬롯 템플릿 (Day1 morning ~ DayN afternoon)

Step 2: 축제 배치 (있으면)
  날짜 확정된 축제 → 해당 날짜 슬롯에 고정
  축제가 해당 day의 seed 역할

Step 3: Seed 배치
  테마 라운드로빈 × score 최상위, 축제 day 제외한 각 day에 1개

Step 4: Pass 2 인출 + 스코어링
  city 고정 + theme off → PlacePool 구성
  Stage 1 base_score 계산 (전체, 1회)

Step 5: 나머지 슬롯 greedy 채우기
  각 빈 슬롯에 대해:
    final_score = base_score + context_score
    최고 후보 배치 → 일정 상태 업데이트

Step 6: 검증
  - 모든 슬롯 채워졌는가 (부족 시 재인출)
  - 동일 장소 중복 없는가
```

#### 스코어링 구조

**Stage 1: Base Score (후보 품질, 1회 계산)**

```
base_score = (
    0.35 × raw_similarity        # primary query vector와의 유사도 (1 - distance)
  + 0.10 × soft_similarity       # soft query vector와의 유사도 (있을 때만, 없으면 0)
  + 0.40 × theme_relevance       # profile_theme_weights 반영
  + 0.15 × source_quality        # 메타데이터 완성도
)
```

| 항목 | 계산 | profile 반영 |
|------|------|-------------|
| raw_similarity | `1 - distance` (Pass 2 S3 Vector 결과, primary query) | 간접 (query가 사용자 의도 반영) |
| soft_similarity | `1 - soft_distance` (soft query로 재검색 시). soft_query 없으면 0 | 간접 |
| theme_relevance | 후보 theme_tags ∩ active_themes, profile 가중 적용 | ✅ 직접 |
| source_quality | 좌표·제목·설명 유무 | ❌ |

**raw + soft 겹침 효과:** 두 query에 모두 가까운 장소는 raw_similarity + soft_similarity가 합산되어 자연스럽게 상위 랭크. V1의 `score_place()` 구조를 계승.

theme_relevance 계산:
```python
def _theme_relevance(candidate_themes, active_themes, profile_weights):
    """profile 가중치 기반 테마 매칭 점수. profile 없으면 균등."""
    weights = profile_weights or {t: 1.0/len(active_themes) for t in active_themes}
    return min(sum(weights.get(t, 0) for t in candidate_themes), 1.0)
```

**visitor_statistics는 Pass 2 base_score에 포함하지 않음:**
- 도시 수준 데이터만 존재 → 도시 내 장소 비교에 무의미
- 도시 간 비교는 city_select의 `score_city()` congestion_penalty에서 이미 반영됨
- 향후 장소 수준 데이터 적재 시 재검토

**Stage 2: Context Score (슬롯 배치 시 재계산)**

```
context_score = (
    geo_penalty                # 같은 day 인접 장소와 일정 거리 이상이면 감점
  + theme_coverage_bonus       # 아직 일정에 안 나온 테마면 가점
)
```

| 항목 | 계산 | 역할 |
|------|------|------|
| geo_penalty | 같은 day 인접 장소와의 거리가 threshold(예: 10km) 초과 시에만 감점. threshold 이내면 0 (페널티 없음) | 비현실적 이동 방지. 가깝다고 가점하지 않음 |
| theme_coverage_bonus | 전체 active_themes 중 미커버 테마에 해당하면 +가점 | 테마 밸런스 (multi-theme 시) |

geo_penalty 계산:
```python
def _geo_penalty(candidate, same_day_places, threshold_km=10.0):
    """threshold 초과 거리만 감점. 가까운 건 보너스 아님."""
    if not same_day_places:
        return 0.0
    nearest_km = min(
        haversine_km(candidate.lat, candidate.lng, p.lat, p.lng)
        for p in same_day_places
        if p.lat and p.lng
    )
    if nearest_km <= threshold_km:
        return 0.0  # 패널티 없음
    excess_km = nearest_km - threshold_km
    return -min(excess_km * 0.01, 0.3)  # cap 있는 감점
```

**제외한 항목과 이유:**
- ~~time_slot_fit~~: heuristic, 데이터 근거 없음
- ~~day_theme_diversity (감점)~~: 사용자가 원한 테마 편중은 정상
- ~~type_diversity (감점)~~: 세부 타입 적재 후 재검토
- ~~popularity_signal~~: 도시 간 비교용. city 고정 시 무의미

**고도화 방안 (메모):**
- geo_penalty의 Haversine 직선 거리 → OpenRouteService 자동차 소요 시간으로 전환 가능. 외부 API이므로 Gateway Tool(GT)로 추가하면 됨. fallback은 Haversine 유지.

**전제:**
- 현재 설계는 "query가 충분한 맥락을 갖고 제대로 입력된 경우"를 전제한다. 불완전 입력(필드 누락, 모호한 표현 등) 처리는 V1 Intent의 clarification 경로가 이미 커버하며, V2에서 별도 설계를 추가하지 않는다.

**테마 1개 선택 시 동작:**
- theme_coverage_bonus 발동 안 함 (이미 커버됨)
- 결과: base_score 순수 경쟁 → 자연스럽게 해당 테마 일정

#### PlacePool 부족 시

부족 판정: 슬롯 수 > PlacePool 후보 수

```
→ PlacePool.exhausted = True
→ 기존 query_vector + city_id + top_k 확대로 재검색 (embedding 재생성 없음)
→ 새 후보 scoring → 슬롯 채우기 재시도
→ 그래도 부족: user_notice 안내 + 축소 일정
```

#### 재인출 시 vector 재사용

PlacePool에 `query_vector`, `soft_query_vector`를 캐시 저장. checkpoint에 함께 보존.

| 수정 유형 | embedding 재생성 | 처리 |
|-----------|-----------------|------|
| 같은 조건 교체 | ❌ | 캐시 vector + top_k 확대 |
| 세부 타입 지정 ("카페로") | ❌ | 캐시 vector + metadata filter (place_type) |
| 의미적 변경 ("조용한 곳으로") | ✅ 1회 | 새 query embedding 생성 |
| 도시 변경 | ❌ | 기존 vector 재사용, city_select 재실행 |

#### 분류 코드(lcls_systm3) · 세부 타입 활용

스코어링에는 사용하지 않음 (분류에 우열 없음).

| 용도 | 활용 시점 |
|------|-----------|
| 필터링 ("카페로 바꿔줘") | 검색(인출) 단계에서 metadata filter |
| 중복 방지 (같은 타입 연속) | 세부 타입 적재 후 배치 단계에서 재검토 |
| 설명 생성 (타입 라벨) | 응답 단계 |

#### 축제 배치 상세

| 상황 | 처리 |
|------|------|
| 축제 날짜가 여행 기간 내 특정일에 해당 | 해당 day에 배치 |
| 축제가 여행 기간 전체에 걸쳐 있음 | 가장 적합한 day에 배치 (슬롯 밀도 고려) |
| 축제 2개 이상 | 다른 day에 분산 |
| 축제를 먼저 배치하는 이유 | 날짜가 고정된 유일한 제약, 나머지는 유연 조정 가능 |

#### V1과의 차이 요약

| 항목 | V1 | V2 |
|------|-----|-----|
| 배치 로직 | 순차 매핑 (places[i]→slot[i]) | seed→축제→맥락 스코어링 |
| 검색 | 절대 안 함 | Pass 2 인출 + 부족 시 재인출 |
| 동선 | 없음 | geo_penalty (threshold 초과 시만) |
| 테마 밸런스 | CandidateEvidence quota 의존 | theme_coverage_bonus |
| 축제 | day1 afternoon 고정 | 실제 날짜 매칭, seed 대체 |
| profile | 없음 | theme_relevance 가중 |
| 설명 생성 | city 선택 시 reason_claims (LLM) + Planner 시 explanation (LLM) = 2회 | **일정 완성 후 LLM 1회로 통합** (도시 선택 이유 + 일정 흐름 + 장소별 설명) |
| city 선택 근거 | candidate_reason_claims (LLM 생성, front 미사용) | selection_reason_code (코드 기반, 설명은 최종 LLM에서 통합) |

---

## 4. V2_CITY_PLANNER_SEPARATION_DECISIONS.md 항목별 최종 상태

| 분리 결정 문서 항목 | V2 실제 방향에서 상태 |
|---|---|
| §4 scoring.py 개선 | ✅ **유효 — 즉시 구현** |
| §5 RAG 2-패스 (Planner 재인출) | ✅ **유효 — 채택** — Pass 2 (city 고정 + theme off)로 PlacePool 구성. S3 Vector 동일 인덱스 사용 |
| §6 Candidate 출력 계약 변경 | ✅ **유효** — CitySelectionResult + PlacePool 분리로 구현 |
| §7 Planner 일정 마무리 flow (10단계) | ❌ **무효** — 자연어 수정 루프로 대체. Planner는 초회 생성 + 수정 모드 |
| §7.1 fallback 사다리 | ❌ **무효** — TTL 기반 종료 + 사용자에게 솔직 안내로 대체 |
| §8 non-seed 슬롯 채우기 (MMR) | ⚠️ **축소** — 초회 생성에서 다양성 보장용으로만 검토 |
| §9 모드별 영향 | ⚠️ **부분 유효** — festival/anchored 모드 처리는 subgraph 내부에서 유지 |
| §10 Supervisor 영향 | ⚠️ **수정 필요** — resume 분기 + 수정 라우팅 추가 |
| §11 병렬화 | ✅ **유효** — `_retrieve_by_theme` ThreadPool은 V2-A에서 구현 |
| §12 미결정 사항 | 대부분 해소됨. 남은 항목은 §5에 정리 |

---

## 5. 미확정 사항 (Spec 이전에 결정 필요)

### Front-end 협의 필요

| # | 항목 | 설명 |
|---|------|------|
| 1 | 수정 범위 | "2일차 바꿔줘" → 해당 일자 전체? 특정 슬롯? front에서 슬롯 지정? |
| 2 | 수정 UI 인터랙션 | 자연어만? 아니면 UI에서 슬롯 클릭 + 자연어 조합? |
| 3 | 일정 표시 중 수정 가능 범위 | 전체 교체 / 부분 교체 / 순서만 변경 중 지원 범위 |

### 데이터/연동 확인

| # | 항목 | 설명 |
|---|------|------|
| 4 | visitor statistics 커버리지 | 도시·월 조합 확인 (congestion 활성화 전제) |
| 5 | DynamoDB 도시별 장소 조회 방식 | city_id 기반 GSI 존재 여부, 반경 재인출 가능 구조 확인 |
| 6 | Profile 저장소 설계 | DynamoDB 핫 (PK=actorId)? 스키마? |
| 7 | Intent의 congestion/vibe 필드 | 신규 추가 범위 |

### 구현 순서

| # | 항목 | 설명 |
|---|------|------|
| 8 | scoring 개선을 선행할지 | V1 + 빌더 양쪽 이득, 독립 PR 가능 — 선행 권장 |
| 9 | subgraph 도입 시점 | scoring 개선 후? 동시? |
| 10 | Memory serde 구현 시점 | subgraph보다 먼저? 동시? |

---

## 6. 권장 구현 순서

```
Phase 1: 기반 (V1 위에 증분, 기존 테스트 불변)
  ├── scoring.py 개선 (§3.3)
  ├── CitySelectionResult + PlacePool schema 정의
  ├── unified_state_from_dict() serde 구현 + round-trip 테스트
  └── 기존 212 테스트 통과 확인

Phase 2: Gateway Tool + Subgraph + Memory
  ├── I/O Tool Lambda 구현 + Gateway 등록 (§3.11)
  │     search_attractions, search_place_pool,
  │     lookup_festival_seeds, enrich_place_details, embed_query
  ├── city_select subgraph 구현 (Gateway tool 호출)
  ├── EvidenceState에 city_selection + place_pool 필드 추가
  ├── Planner가 PlannerInput 계약으로 전환 + Pass 2 인출
  ├── AgentCoreMemorySaver 연동 (checkpoint 저장·복원)
  ├── interrupt/resume 기본 동작 확인
  └── 모듈별 독립 테스트 CI 구성

Phase 3: 수정 루프
  ├── 수정 Intent 해석 (state 기반 프롬프트 분기)
  ├── Planner 수정 모드 (기존 일정 기반 부분 재배치)
  ├── Gateway tool 재호출 (PlacePool 소진 시)
  ├── Supervisor resume 분기 라우팅
  └── E2E 수정 루프 테스트

Phase 4: Profile + 개인화
  ├── Profile Agent (DynamoDB 핫 read)
  ├── theme_weights → CitySelectState 주입
  ├── Profile Writer (일정 완성 후 비동기 write)
  └── 병렬화 (Gateway Lambda가 독립 스케일하므로 자연 해결)
```

---

## 7. LLM 모델 선택

### V2에서 LLM을 호출하는 지점

| 지점 | 호출 빈도 | 입력 크기 | 출력 형태 | 핵심 요구 |
|------|-----------|-----------|-----------|-----------|
| **Intent (초회)** | 1회/세션 | ~500 tokens | structured JSON | JSON schema 준수, 한국어 이해 |
| **Intent (수정 해석)** | 수정 턴마다 1회 | ~300 tokens | structured JSON | 빠른 응답, 수정 의도 분류 |
| **설명 생성 (최종)** | 1회/세션 | ~2000 tokens | 한국어 prose | 한국어 작문, grounded 설명, 환각 억제 |

V2에서 LLM을 호출하지 않는 곳:
- city_select subgraph (순수 검색 + 스코어링, reason_claims 제거)
- Supervisor (결정론 코드)
- Planner 배치 로직 (순수 계산)

### 후보 모델 비교 (Bedrock on-demand, us-east-1)

| 모델 | Context Window | Input ($/1M) | Output ($/1M) | 특징 |
|------|---------------|-------------|--------------|------|
| **Amazon Nova Micro** | 128K | $0.035 | $0.14 | 최저가, text only, 빠름 |
| **Amazon Nova Lite** | 300K (v1) / 1M (v2) | $0.06 | $0.24 | 저가, multimodal |
| **Amazon Nova 2 Lite** | 1M | TBD (Lite급 예상) | — | reasoning, MCP tool 지원, preview |
| **Amazon Nova Pro** | 300K | $0.80 | $3.20 | 복잡한 추론 |
| **Claude Haiku 4.5** | 200K (1M preview) | $1.00 | $5.00 | 빠름, 코딩/에이전트 강점 |
| **Claude Sonnet 4.6** | 200K (1M preview) | $3.00 | $15.00 | 밸런스, 한국어 품질 높음 |
| **Claude Opus 4.7** | 200K | $5.00 | $25.00 | 최고 성능, 에이전트 장기 작업 |

### 노드별 모델 선택 기준

| 기준 | Intent (초회/수정) | 설명 생성 |
|------|-------------------|-----------|
| JSON schema 준수 | 매우 높음 | 낮음 (prose) |
| 한국어 품질 | 중간 (필드 추출) | 높음 (사용자 노출) |
| 속도 | 높음 (사용자 대기) | 중간 (마지막 단계) |
| 비용 민감도 | 높음 (수정 턴마다 호출) | 중간 (1회) |
| Context window 필요 | 작음 (<1K tokens) | 중간 (~3K tokens) |

### 권장 조합 후보

| 전략 | Intent | 설명 생성 | 월 1000세션 추정 비용 |
|------|--------|-----------|---------------------|
| **A. 비용 최적** | Nova Micro | Haiku 4.5 | ~$3-5 |
| **B. 밸런스** | Nova Lite | Haiku 4.5 | ~$5-8 |
| **C. 품질 우선** | Haiku 4.5 | Sonnet 4.6 | ~$14-20 |

(세션당 초회 1회 + 수정 3턴 + 설명 1회 기준 근사)

### 결정 방식

Phase 1에서 **샘플 테스트 후 확정:**

| # | 검증 항목 | 방법 |
|---|-----------|------|
| 1 | Nova Micro/Lite의 한국어 structured output 안정성 | Intent schema로 10회 호출, 파싱 성공률 측정 |
| 2 | Haiku 4.5의 한국어 prose 품질 | 일정 + metadata → 설명 생성 비교 (vs Sonnet) |
| 3 | Nova 2 Lite us-east-1 가용 여부 | Bedrock console 확인 |
| 4 | 현재 `openai.gpt-oss-120b-1:0`의 실제 정체 | 팀 내부 확인 |
| 5 | 모델별 Converse API tool_use 지원 | Bedrock 문서 확인 |

검증 통과 시 **전략 B (Nova Lite + Haiku 4.5)**를 기본으로, 한국어 품질 미달 시 **전략 C**로 fallback.

### V1 config 구조 유지

```
# agentcore.json env vars (V2)
LOVV_INTENT_LLM_MODEL_ID:     (테스트 후 확정)
LOVV_PLANNER_LLM_MODEL_ID:    (설명 생성용, 테스트 후 확정)
LOVV_SUPERVISOR_LLM_MODEL_ID: (V2에서도 미사용, 결정론)
```

노드별 FM 라우팅 config 구조는 V1 그대로 유지. 모델 ID만 변경.

---

## 8. 데이터 모델 (V2 Schemas)

### V1에서 유지

| Schema | 위치 | 변경 |
|--------|------|------|
| `RequestState` | state.py | 유지 |
| `ConversationState` | state.py | 유지 (messages 누적 관리 추가) |
| `TraceState` | state.py | 유지 |
| `IntentState` | state.py | 유지 + 수정 intent 필드 추가 가능 |
| `RoutingState` | state.py | 유지 + resume 분기 필드 |
| `FestivalState` | state.py | 유지 |
| `ServingState` | state.py | 유지 |
| `CandidateEvidenceInput` | schemas.py | 유지 |
| `FestivalVerification` | schemas.py | 유지 |
| `GeoPoint` | schemas.py | 유지 |
| `SelectedCity` | schemas.py | 유지 |

### V2 신규/변경

| Schema | 용도 | 상태 |
|--------|------|------|
| **`CitySelectionResult`** | city_select 출력 (도시 확정) | 신규 |
| **`SeedCandidate`** | day별 anchor 장소 | 신규 |
| **`PlacePool`** | 일정 재료 (mutable, 수정 시 갱신) | 신규 |
| **`PlannerInput`** | Planner가 받는 최소 입력 | 신규 |
| **`CitySelectState`** | subgraph 내부 state (TypedDict) | 신규 |
| **`EvidenceState`** | city_selection + place_pool 추가 | 변경 |
| **`PlannerOutput`** | explanation 간소화 | 변경 |

### Schema 초안

```python
# === city_select 출력 ===

@dataclass(frozen=True, slots=True)
class CitySelectionResult:
    selected_city: SelectedCity
    city_rankings: tuple[dict[str, Any], ...]   # score breakdown 포함
    mode: str                                    # city_discovery | anchored | festival_seeded
    city_anchor: dict[str, Any] | None

@dataclass(frozen=True, slots=True)
class SeedCandidate:
    place_id: str
    title: str
    city_id: str
    theme_tags: tuple[str, ...]
    latitude: float | None
    longitude: float | None
    place_score: float
    assigned_day: int | None = None              # seed 배치 시 할당된 day


# === PlacePool (mutable) ===

@dataclass(slots=True)
class PlacePool:
    city_id: str
    scored_candidates: list[dict[str, Any]]      # 전체 scored pool
    recommended: list[dict[str, Any]]            # 현재 일정에 배치된 장소
    reserve: list[dict[str, Any]]                # 미배치 후보
    exhausted: bool = False                      # 재인출 트리거

    # 재인출용 캐시
    query_vector: list[float] | None = None
    soft_query_vector: list[float] | None = None
    active_themes: list[str] | None = None
    last_top_k: int = 50


# === Planner 입력 ===

@dataclass(frozen=True, slots=True)
class PlannerInput:
    status: str                                  # ok | insufficient_candidates
    selected_city: SelectedCity
    seeds: tuple[SeedCandidate, ...]             # day별 anchor
    place_pool: PlacePool                        # Pass 2 결과
    festival_candidates: tuple[dict[str, Any], ...]
    external_link_themes: tuple[str, ...]
    trip_type: str
    travel_month: int
    profile_theme_weights: dict[str, float] | None


# === city_select subgraph 내부 state ===

class CitySelectState(TypedDict):
    # 입력
    candidate_input: CandidateEvidenceInput
    query_vector: list[float]
    soft_query_vector: list[float] | None
    theme_weights: dict[str, float] | None

    # retrieval → scoring
    retrieved_candidates: list[dict]
    pruned_groups: dict[str, list]

    # 출력
    city_selection: CitySelectionResult | None
    seed_candidates: list[SeedCandidate]

    # 제어
    status: str
    failure_signal: str | None


# === EvidenceState V2 확장 ===

@dataclass(slots=True)
class EvidenceState:
    # V1 호환 (점진 제거 예정)
    candidate_evidence_package: CandidateEvidencePackage | None = None
    selected_destination: dict[str, Any] | None = None

    # V2
    city_selection: CitySelectionResult | None = None
    place_pool: PlacePool | None = None
    seed_candidates: tuple[SeedCandidate, ...] = ()
```

### Schema 간 관계

```
Intent
  → CandidateEvidenceInput
      ↓
city_select subgraph (CitySelectState)
  → CitySelectionResult + SeedCandidate[]
      ↓
Pass 2 인출 (Gateway tool: search_place_pool)
  → PlacePool
      ↓
PlannerInput = CitySelectionResult + Seeds + PlacePool + Festivals
  → Planner
      → PlannerOutput (itinerary + explanation)
          ↓
      checkpoint 저장 (UnifiedAgentState 전체)
```

### V1 Schema 제거 대상 (V2 안정화 후)

| Schema/필드 | 이유 |
|------------|------|
| `CandidateEvidencePackage.recommended_places` | PlacePool.recommended으로 대체 |
| `CandidateEvidencePackage.reserve_places` | PlacePool.reserve로 대체 |
| `CandidateEvidencePackage.candidate_reason_claims` | 삭제 (설명은 최종 LLM 1회) |
| `CandidateEvidencePackage.coverage_audit` (quota 관련) | 삭제 |
| `CandidateEvidencePackage.retrieval_audit` | telemetry span으로 이동 |
| `CandidateEvidencePackage.fallback_audit` | telemetry span으로 이동 |
| `CandidateEvidencePackage.warnings` | telemetry span으로 이동 |
| `CandidateReasonClaim` | 삭제 |
| `PlannerExplanationAudit` | 간소화 (최종 LLM 1회 구조에 맞춰 재설계) |

---

## 9. 변경하지 않는 것 (V1 불변 목록)

- 단일 `LovvAgentV1` AgentCore Runtime
- `us-east-1` 리전
- 노드별 FM 라우팅 config 구조
- V1 Observability · CI/CD 게이트
- V1 one-shot 경로 (빌더 안정화 후 점진 제거)
- `actorId` = 가명 ID. raw PII 미저장

---

## 10. Spec 작성 가이드 — 인원 분배 단위

V2 Spec을 작성할 때 아래 **작업 단위(Work Unit)**별로 독립 Spec을 생성한다. 각 단위는 서로 다른 인원에게 배정 가능하며, 인터페이스 계약(input/output schema)만 공유하면 병렬 개발이 가능하다.

### Spec 분리 기준

```
[Agent Spec]        = LangGraph 노드/subgraph 단위. orchestration 로직 포함.
[Gateway Tool Spec] = Lambda + Gateway 등록 단위. I/O 로직 + tool schema 정의.
```

### 작업 단위 목록

#### Gateway Tool Specs (데이터 취득 — Lambda 개발)

| Spec ID | Tool 이름 | 담당 범위 | 의존성 |
|---------|-----------|-----------|--------|
| **GT-1** | `search_attractions` | S3 Vectors 검색 Lambda + Gateway tool schema + 배포 | S3 Vector index |
| **GT-2** | `search_place_pool` | Pass 2 인출 Lambda (city 고정 + theme off/filter) | S3 Vector index |
| **GT-3** | `lookup_festival_seeds` | DynamoDB 축제 조회 Lambda | DynamoDB table + GSI |
| **GT-4** | `enrich_place_details` | DynamoDB 장소 상세 BatchGet Lambda | DynamoDB table |
| **GT-5** | `embed_query` | Bedrock Titan embedding Lambda | Bedrock model access |

각 GT Spec에 포함할 것:
- Tool input/output JSON schema (MCP tool schema)
- Lambda handler 구현
- Gateway target 등록 설정 (agentcore.json 또는 CLI 명령)
- 단위 테스트 (mock input → expected output)
- IAM 권한 정의

#### Agent Specs (로직 — LangGraph 노드 개발)

| Spec ID | Agent/Module | 담당 범위 | 의존 Gateway Tool |
|---------|-------------|-----------|-------------------|
| **AG-1** | city_select subgraph | retrieval → scoring → selection orchestration | GT-1, GT-5 |
| **AG-2** | Planner (최초 생성) | seed 배치 + Pass 2 스코어링 + 슬롯 채우기 | GT-2, GT-4 |
| **AG-3** | Planner (수정 모드) | 수정 Intent 해석 + 부분 재배치 + 재인출 | GT-2, GT-4, GT-5 |
| **AG-4** | Supervisor (resume 라우팅) | 수정 루프 분기 + Memory interrupt/resume | — |
| **AG-5** | Profile Agent | DynamoDB read + theme_weights 주입 | — |
| **AG-6** | Memory/Serde | unified_state_from_dict + checkpoint 저장·복원 | — |
| **AG-7** | scoring.py 개선 | V1 scoring 수정 (§3.3) | — |

각 AG Spec에 포함할 것:
- State input/output 계약 (dataclass schema)
- 노드 로직 상세
- Gateway tool 호출 인터페이스 (어떤 tool을 어떤 파라미터로)
- 단위 테스트 (Gateway tool을 mock한 상태에서)
- 통합 테스트 기준

### 병렬 개발 가능 범위

```
[독립 개발 가능 — 인터페이스 합의 후 병렬]
  GT-1~5 (Gateway Tool 전체) ←→ AG-1~3 (Agent 로직)
  AG-7 (scoring 개선)        ←→ 나머지 전부
  AG-5 (Profile)             ←→ AG-1, AG-2
  AG-6 (Memory/Serde)        ←→ AG-4 (Supervisor resume)

[순차 의존]
  GT-1, GT-5 완료 → AG-1 통합 테스트
  GT-2, GT-4 완료 → AG-2, AG-3 통합 테스트
  AG-1 완료 → AG-2 (seed 입력 필요)
  AG-6 완료 → AG-4 (checkpoint 필요)
```

### Spec 작성 시 공유해야 하는 계약 문서

| 계약 | 내용 | 소비자 |
|------|------|--------|
| Gateway Tool Schema | 각 tool의 MCP inputSchema / outputSchema | AG-1, AG-2, AG-3 |
| CitySelectionResult | 도시 선정 결과 dataclass | AG-2 |
| PlacePool | 장소 후보 풀 dataclass | AG-2, AG-3 |
| PlannerInput | Planner 입력 계약 | AG-2, AG-3 |
| CitySelectState | subgraph 내부 state | AG-1 내부 |
| UnifiedAgentState (V2 확장) | 전체 graph state | AG-4, AG-6 |

**이 계약들을 먼저 확정하면 각 Spec을 독립적으로 작성·개발할 수 있다.**
