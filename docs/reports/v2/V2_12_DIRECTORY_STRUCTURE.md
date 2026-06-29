# V2 디렉토리 구조 (수정본)

> 작성일 2026-06-28 · 입력: `v2_directory_structure_proposal.md`(팀 제안) 검토 후 반영.
> 변경 요지: ① **`infra/` 데이터 접근 계층 추가**(repositories·adapters·config — 제안서 누락) ② **memory/checkpointer 자리 명시**(P0 F3) ③ **노드명 정본 정합**(`scoring_and_selection_node`) ④ **"재작성 아님 = V1 모듈 포팅" 명문화** ⑤ import 그래프 명시.
> 원칙은 제안서의 vertical slice(에이전트별 종적 격리) 유지.

---

## 1. 디렉토리 트리 (`src/lovv_agent_v2/`)

```text
src/lovv_agent_v2/
├── common/                     # 순수 유틸 (★ 비즈니스 규칙·I/O 금지)
│   ├── telemetry.py            # OTel 계측·구조화 로깅 (= 검증 계측 선결, V2_10 §0)
│   └── utils.py                # haversine 등 순수 함수
│
├── infra/                      # ★신규: 데이터 접근·외부 연동 (공유 인프라, 비즈니스 규칙 금지)
│   ├── config.py               # [포팅] RuntimeConfig · MemorySettings (env, import 시 AWS 무접근)
│   ├── aws_clients.py          # [포팅] boto3 클라이언트 팩토리/주입
│   ├── adapters/
│   │   ├── bedrock_converse.py # [포팅] LLM Converse adapter (모델 비종속)
│   │   └── embeddings.py       # [포팅] Titan/Cohere 임베딩
│   ├── repositories/
│   │   ├── s3_vectors.py       # [포팅] S3 Vector 검색 repo
│   │   └── dynamodb.py         # [포팅] DynamoDB lookup (festival seed · visitor stats · 검증 캐시)
│   └── memory/
│       └── checkpointer.py     # ★신규 자리: build_checkpointer(AgentCoreMemorySaver) — F3 (P0)
│
├── core/                       # 오케스트레이션 프레임워크
│   ├── state.py                # UnifiedAgentState (중앙 계약 = 에이전트 간 약속)
│   └── graph.py                # Main Graph 컴파일 + **checkpointer 배선** + 결정론 라우터 조립
│
├── models/                     # 데이터 계약 DTO (연산 없음)
│   ├── schemas.py              # CitySelectionResult · PlacePool · PlannerInput · CandidateEvidenceInput · ModifyResult · 응답 스키마
│   └── profile.py              # LovvUserProfile
│
├── agents/                     # Vertical slice (구현 영역)
│   ├── intent/                 # 생성/수정 파싱 (V2에서 비중↑)
│   │   ├── node.py
│   │   ├── parser.py           # raw/soft·congestion_pref·transport_pref·theme_hint 추출
│   │   ├── validator.py        # 모순/모호/범위밖/안전 플래그 (입력 검증)
│   │   ├── modify_parser.py    # ★신규: ModifyResult·edit_ops 분해 (수정 경로)
│   │   └── prompts/            # intent_normalization 등
│   │
│   ├── supervisor/             # 결정론 라우터 (★LLM 없음)
│   │   ├── router.py           # conditional_edge 분기 제어
│   │   └── dispatcher.py       # 초회/resume 판별 · 수정 의도 분해 · 응답상태 · 세션 avoid
│   │
│   ├── city_select/            # [포팅: scoring·destination_search·candidate_evidence] + V2 델타
│   │   ├── subgraph.py         # 2-node subgraph 컴파일
│   │   ├── retrieval_node.py   # [포팅] S3 Vector 검색·merge·prune (+슬롯 단위 재인출)
│   │   ├── scoring_and_selection_node.py   # ★정본 노드명. soft 게이트·capacity 제거·★seed·transport
│   │   ├── scoring.py          # [포팅] score_place/score_city + C1(capacity 제거)·C2(theme_weights)
│   │   ├── selection.py        # [포팅] quota/budget 선택 — seed-only로 정리(reserve 폐기)
│   │   └── prompts/
│   │
│   ├── festival_verifier/      # [포팅: festival_verifier] + 테마정합 필터
│   │   ├── node.py
│   │   ├── verifier.py
│   │   └── prompts/
│   │
│   ├── planner/                # [포팅 일부] + 신규
│   │   ├── node.py
│   │   ├── pass1.py            # 도시 선택 + 테마 게이트
│   │   ├── pass2.py            # 도시 고정 · ★seed 라운드로빈 배치 · geo_penalty(haversine)
│   │   ├── edit_mode.py        # ★신규: 비-seed 슬롯 교체 · 일괄 재배치 (수정, V2_11)
│   │   ├── plan_b.py           # ★신규(V2.1): on-demand 실내 대안
│   │   ├── validation.py       # [포팅] 결정론 출력 검증(필드·국가·축제 confirmed)
│   │   └── prompts/
│   │
│   ├── response_packager/      # 결정론 패키징 (prompts 불필요)
│   │   ├── node.py             # 응답 + interrupt 발행
│   │   └── packager.py         # alternativeItinerary · weatherNotice · modification · response_status
│   │
│   └── profile/                # 선호 관리 (집계=결정론, prompts 불필요)
│       ├── node.py
│       └── manager.py          # theme_weights 집계 · 저장 이벤트 · fallback n
│
├── harness.py                  # Composition Root (DI: infra → agents → graph 조립)
└── agentcore_entrypoint.py     # AgentCore HTTP entrypoint (actor_id·thread_id 플러밍, checkpointer SPEC R2)

tests/v2/                       # (src 밖) 에이전트별 격리
├── test_intent.py · test_supervisor.py · test_city_select.py · test_planner.py · ...
└── fixtures/                   # → docs/tasks/results/v2_intent_mocks/ 연결
```

---

## 2. 제안서 대비 변경점

| # | 변경 | 이유 |
|---|---|---|
| 1 | **`infra/` 계층 신설**(config·aws_clients·adapters·repositories·memory) | 제안서는 `common/aws_clients`만 있고 S3 Vector·DynamoDB·Converse·config·memory가 누락. 이건 agent-private가 아닌 **공유 인프라**. common(순수 유틸)과 분리 |
| 2 | **`infra/memory/checkpointer.py`** | P0인 F3(resume/interrupt)·`AgentCoreMemorySaver`·`MemorySettings`가 제안서에 없었음 |
| 3 | **`core/graph.py`에 checkpointer 배선 명시** | 그래프 컴파일 시 checkpointer 주입(checkpointer SPEC R1) |
| 4 | 노드명 `selection_node` → **`scoring_and_selection_node`** | 정본(`V2_SCENARIO_MATRIX`·V2_07) 노드명과 정합 |
| 5 | `intent/modify_parser.py` 추가 | 수정 경로 ModifyResult·edit_ops(V2_09 §2·V2_11) |
| 6 | `planner/validation.py` 추가 | V1 Validation Skill(결정론 출력 검증) 자리 |
| 7 | profile·response_packager의 `prompts/` 제거 | 둘 다 LLM 없음(집계·결정론 패키징) |

---

## 3. 개발·격리 원칙 (Rules of Engagement)

### 3.1 허용 import 그래프 (명시)
```
agents/*  →  { common, infra, core.state, models }      (O)
agents/*  →  agents/* (다른 에이전트 내부)                  (X, 절대 금지)
infra/*   →  { common }                                   (O, 단 비즈니스 규칙 금지)
common/*  →  (외부 의존 없음, 순수)                         (O)
```
- 에이전트 간 데이터·제어는 **`core/state.py`의 State 객체 + `core/graph.py` 오케스트레이터로만**.
- 각 에이전트 외부 노출은 `node.py`의 `def {agent}_node(state) -> dict` 하나뿐.

### 3.2 계층 책임 (3-tier, business rule는 agents에만)
- **common** = 순수 함수(연산·포맷). I/O·비즈니스 규칙 금지.
- **infra** = 외부 I/O(AWS·DB·LLM·config·memory). 비즈니스 규칙 금지.
- **agents** = 비즈니스 규칙 전부(스코어링·게이트·배치·파싱).

### 3.3 ★ 재작성 아님 = V1 모듈 포팅
"v1 안 건드린다 = **v1을 수정하지 않는다**"지 **재작성이 아니다.** 검증된 V1 로직은 **복사→V2 델타만 적용**한다.

| V1 출처 | → V2 위치 | 작업 |
|---|---|---|
| `tools/scoring.py` | `agents/city_select/scoring.py` | 포팅 + C1(capacity 제거)·C2 |
| `tools/destination_search.py` | `agents/city_select/retrieval_node.py` | 포팅 + soft 게이트(prune) |
| `tools/candidate_selection.py` | `agents/city_select/selection.py` | 포팅 + seed-only 정리 |
| `agents/candidate_evidence.py` | `city_select/*_node.py` 분해 | 2-node로 재배치 + seed·congestion_pref |
| `agents/festival_verifier.py` | `agents/festival_verifier/verifier.py` | 포팅 + 테마정합 |
| `repositories/{s3_vectors,dynamodb}` | `infra/repositories/` | 거의 그대로 |
| `adapters/{bedrock_converse,embeddings}` · `config.py` | `infra/` | 거의 그대로 |
| `agents/intent.py` | `agents/intent/*` | 포팅 + 수정파싱·congestion/transport 승격 |
| (신규) supervisor dispatcher · modify_parser · edit_mode · plan_b · profile manager | — | 신규 구현 |

> 원칙: **포팅 우선, 신규 최소.** 스코어링 공식·검색·repo·adapter는 재작성하지 말 것(테스트·동작 손실 + 신규 버그).

### 3.4 테스트 격리
`tests/v2/test_{agent}.py`로 에이전트별 격리 → 로컬 1초 검증. fixtures = `v2_intent_mocks/` 연결.
