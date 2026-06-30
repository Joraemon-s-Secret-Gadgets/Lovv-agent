# V2 아키텍처 확정본 + 우선순위 (Step 5)

> 입력: `V2_DECISIONS_LOG.md`(Step 4 확정 10건) + 현 설계(`V2_SCENARIO_MATRIX`=노드 로직 정본, `V2_ARCHITECTURE_DECISIONS.md`).
> 이 문서 = **결정을 노드·계약에 박은 확정 델타 + 빌드 우선순위**. 노드 단위 세부 로직의 정본은 여전히 `V2_SCENARIO_MATRIX`. 충돌 시 본 문서의 "결정 반영"이 우선(최신).
> 표기일 2026-06-28. 이 문서 이후의 다음 행동은 **코드**(아래 thin slice)지 추가 문서가 아니다.

---

## 1. 확정 아키텍처 — 컴포넌트별 델타 (vs 현 V2 설계)

각 항목 = **[변경/신규] · 결정 근거(ID)**.

### Intent
- **[유지]** 초회·resume 입력 모두 통과. 요청 해석.
- **[신규] 모순 감지 → 되묻기**: 명백한 모순 입력은 절충 생성 없이 `needs_clarification`. (되묻기 결정)
- 긴서사는 핵심 키워드 추출 후 진행(별개).

### Supervisor (중앙 허브 라우터 — 매 노드 후 개입)
- **[신규] 초회/resume 분기**: `thread_id` + checkpoint 존재 여부로 분기.
- **[신규] 수정 의도 분류**: ① 비-seed 슬롯 교체(1차 대상) ② 도시 변경(경로만 설계, 1차 미구현) ③ 백로그(길이·날짜·전체무드·맥락변화·4d3n·복합 → `userNotice`로 한계 고지). (D-B)
- **[신규] 다건 동시 수정 분해**: 한 입력의 복수 편집("A는 X로, B는 Y로")을 **edit op 리스트**로 분해 → 각 op를 슬롯 교체로 라우팅. 같은 슬롯에 상충 조건이거나 op 간 모순이면 → `needs_clarification`(되묻기). (D-B 확장, 아래 §1.5)
- **[신규] 응답상태 결정**: `completed` / `END_WAIT_USER` / **`modification_pending`**(수정 완료 + 다음 수정 대기). (응답상태)
- **[신규] 세션 avoid 보유·주입**: 전면 불만("다 별로야") 시 기존 도시/테마를 세션 avoid에 적재 → 재생성 시 제외. (기피)

### city_select subgraph (2-node · 부분 재실행 진입점)
**retrieval_node**
- **[유지]** S3 Vector 검색 · merge · prune.
- **[신규]** 수정 시 **슬롯 단위 재인출** 진입점(raw/soft query + 슬롯 조건).

**scoring_and_selection_node**
- **[변경] capacity 결합 제거**: `score_city`에서 `candidate_sufficiency` 삭제 → 항상 rank 0, insufficient는 Planner In-city Itinerary가 흡수. (기확정)
- **[변경] 테마 = soft gate**: `theme_match` → **`theme_weights`** 가중. 부분 충족 허용, 미충족 강한 감점, 누락 테마는 audit/`userNotice` 후보. (기확정)
- **[신규] 다테마 seed 보장**: 다테마 선택 시 seed가 모든 테마를 **soft**로 충족(라운드로빈 유지). (기확정)
- **[유지/명시] seed 추출**: 도시 선택 이유가 된 대표 장소 = day anchor. (reserve 폐기, seed-only)
- **[신규] transport_pref 신호**: `walk`→슬롯 간 거리 페널티 강화 / `car`→완화 / `unknown`→기본. (D-E)

### Festival Verifier (optional fan-out)
- **[유지]** `execution_mode = festival_seeded_city_discovery`일 때 활성.
- **[신규/데이터 전제] 축제 테마 정합 필터**: 축제별 테마 태깅이 적재된 경우에만 정합 검사. (데이터 전제)

### Planner (2-pass + 수정 모드)
- **[유지] 초회**: Pass1(도시 선택·테마 게이트) → In-city Itinerary(도시 고정·테마 off·PlacePool ~30–50) → **seed 라운드로빈 배치 + geo_penalty(haversine)**.
- **[신규] 수정 모드**: **비-seed 슬롯 교체**. 교체 슬롯에 자연어 조건(무드·타입·위치 = 추가 query)을 걸어 S3 Vector 재인출. **seed 고정, 배치 개수 ≤3 불변**. (D-B)
- **[신규] 배치 일괄 적용**: 다건 op는 **각자 재인출 후 한꺼번에 적용 → 단일 재배치/재스코어**(geo·타입 균형 재평가). 순차 적용 안 함(순서 의존·중복 회피). seed·≤3 불변. (§1.5)
- **[신규] on-demand Plan B**: `weatherNotice` 후 사용자 동의 시 실내 위주 대안을 **수정 루프로** 생성 → `alternativeItinerary` 채움. 자동 사전 생성 없음. (D-A)
- **[결정] 동선**: 출력 `move`는 채우지 않음(front 담당). 배치 스코어링은 haversine 1차 — front 이동시간 API 사용은 ⏳ 검토. (D-C)

### Response Packager
- **[신규] 출력 스키마 확장**: `alternativeItinerary`(nullable) + `weatherNotice`(발동 사유) + `response_status`에 `modification_pending`. 평상시 alt/notice = null. (D-A, 응답상태)
- **[유지]** interrupt 발행 → checkpoint 저장 → resume 대기.

### Profile Agent
- **[변경] write = 저장 기반만**: 사용자가 일정을 **저장(확정)**할 때 그 일정의 테마·선택 장소에서 `theme_weights` 집계. **수정 중간 발화·단발 신호는 장기 누적 안 함**(변덕 방지). (D-K)
- **[신규] fallback 기준**: 모호 입력 자동 채움은 **`saved_trip_count ≥ n`**일 때만(추천 이유에 "이전 선호 기반" 명시), 부족하면 되묻기. n은 추후 튜닝(2~3). (D-K)
- **[신규 의존]** front의 **"일정 저장" 이벤트** 신호 필요.

### Memory (AgentCore)
- **[유지]** checkpoint/interrupt/resume, `thread_id` + TTL.
- **[신규] 세션 avoid 상태**: checkpoint에 보관, **TTL(세션 종료)까지 유지** 후 소멸. 영구 profile 아님. (기피)

### 데이터 계약 변경 (요약)
| 계약 | 변경 |
|---|---|
| `CitySelectionResult` | `candidate_sufficiency` 제거 · `theme_weights` 추가 · `seed` 명시 |
| `PlacePool` | 세부타입 · `indoor/outdoor` 태그 |
| `PlannerInput` | `transport_pref`(walk/car/unknown) |
| 응답 스키마 | `alternativeItinerary` · `weatherNotice` · `response_status: modification_pending` |
| `LovvUserProfile` | `saved_trip_count` · 집계 `theme_weights` |
| 신규 적재 데이터 | 세부타입 · indoor/outdoor · 도시·월 기상 · visitor stats |

### §1.5 다건 동시 수정 (배치 편집) — 한 입력 N개 편집
현 D-B는 "한 턴 = 한 슬롯"을 암묵 가정했음. 한 입력에 복수 편집이 오는 경우를 정식 처리한다.

- **분해(Intent/Supervisor)**: 입력 → `edit_ops: [{slot, condition}, ...]`. 각 op는 비-seed 슬롯 교체로만(1차 범위 내). seed 변경·도시 변경이 섞이면 해당 부분은 백로그/경로 처리 + `userNotice`.
- **모순 처리**: 같은 슬롯에 상충 조건, 또는 op 간 모순 → 전체를 멈추고 `needs_clarification`(되묻기 결정과 일관).
- **일괄 적용(Planner)**: 모든 op 재인출 후 **한 번에 적용 → 단일 재배치/재스코어**(geo_penalty·타입 균형·transport_pref 재평가). 순차 적용은 순서 의존·동선 꼬임 유발하므로 금지.
- **부분 실패 정책**: op 일부만 후보 없음(no_candidate)일 때 → **부분 적용 + 안내**. 성공 op는 반영, 실패 슬롯은 유지 + `userNotice`로 고지, 상태 `modification_pending`. (확정)
- **상한**: op 수는 비-seed 슬롯 수(=일자당 ≤2~3)로 자연 제한. 별도 하드캡 불필요.

→ 우선순위상 **C4(슬롯 교체)에 흡수**(단일+복수 한 묶음). 난이도 소폭↑(분해 파서 + 일괄 재배치).

---

## 2. 우선순위 (검증가능성 · 구현난이도 · 신규/수정)

### 평가 기준
- **신규/수정**: 수정=기존 V1 자산 고도화(재사용·낮은 리스크) / 신규=새 구성요소(높은 리스크).
- **검증가능성(상/중/하)**: 상=단위·스키마·룰로 결정론적 검증 / 중=골든셋·분포로 검증 / 하=대화 E2E·NLU 의존(검증 비용 큼).
- **구현난이도(상/중/하)**.
- **의존**: 선행 blocker.

### 평가 표
| # | 항목 | 신규/수정 | 검증 | 난이도 | 의존 | 등급 |
|---|---|---|---|---|---|---|
| **F1** | 데이터 4종 적재(세부타입·indoor/outdoor·기상·visitor) | 신규 | **상** | 중 | — (다수의 전제) | **P0** |
| **F2** | 출력 스키마 확장(alt·weatherNotice·modification_pending) | 신규(계약) | **상** | 하 | front 협의 | **P0** |
| **F3** | 수정 루프 인프라(resume·interrupt·Supervisor 분기) | 신규(핵심) | 하 | **상** | checkpoint | **P0** |
| C1 | capacity 제거(score_city 단순화) | 수정 | 상 | 하 | — | **P1** |
| C2 | soft 테마 게이트 + theme_weights | 수정 | 중 | 중 | F1 | **P1** |
| C3 | seed 추출 + 라운드로빈 배치 | 수정/고도화 | 중 | 중 | — | **P1** |
| C4 | 슬롯 교체 + 슬롯 조건 재인출(단일·**복수** 일괄, Planner 수정모드) | 신규 | 중 | 중상 | F3 | **P1** |
| W1 | weatherNotice 임계 판정(룰) | 신규 | 상 | 하중 | F1(기상) | **P1** |
| T1 | transport_pref geo_penalty | 신규 신호 | 중 | 하중 | C3 | P2 |
| K1 | profile write(저장기반) + fallback n | 신규/수정 | 중 | 중 | F2(저장 신호) | P2 |
| W2 | on-demand Plan B 실제 생성 | 신규 | 중 | 중 | W1·C4 | P2 |
| A1 | 세션 avoid(전면 불만) | 신규 | 중 | 하중 | F3 | P2 |
| M1 | 모순→되묻기 / 되묻기 경계 | 신규/수정 | 하 | 중 | — | P2 |
| V1 | 축제 테마 정합 필터 | 수정 | 상 | 하 | F1(축제 태그) | P2 |

### 빌드 순서 (의존 반영)
1. **P0 기반** (병렬 가능): F1(데이터팀) ∥ F2(front 협의) ∥ F3(그래프). — **이게 안 깔리면 나머지 다 막힘.**
2. **P1 코어 품질**: C1(즉시·독립) → C2 → C3 → C4 + W1.
3. **P2 정책·부가**: T1·K1·W2·A1·M1·V1.

### ★ V2.0 thin slice (먼저 출하할 최소 단위)
> **F1 + F2 + F3 + C1 + C2 + C3 + C4 + W1**
> = "품질 개선된 초회 생성(capacity 제거·soft 테마·seed 배치) + 비-seed 슬롯 교체 수정 + 날씨 안내".
> Plan B **실제 생성(W2)**, profile write(K1), transport(T1), 세션 avoid(A1), 되묻기(M1)는 **V2.1로 미룬다**.

근거: thin slice는 (a) P0 기반 위에서 (b) 검증 쉬운 수정 항목(C1/C2/C3) + (c) 핵심 신규 가치 1개(C4 슬롯 교체)를 묶어 **하나의 동작하는 수정 루프**로 출하 가능. W2/K1/M1처럼 검증이 어렵거나(하) front·데이터 의존이 큰 건 다음 사이클로 분리해 출하를 막지 않음.

---

## 3. 남은 미정(구체화 단계에서 수치만 확정 — 설계는 안 바뀜)
D-J 임계 수치 · D-C 실이동 API 채택 여부 · profile fallback `n` · 4d3n 확장 시점 · 축제 테마 태깅 데이터 확보. *(수정 응답 반환 방식은 `V2_11`로 확정 — itinerary 전체(full)+changes)*

> **드리프트 경고**: 위 6개는 전부 "수치·협의" 수준이라 설계를 다시 열 이유가 안 됨. 여기서 더 문서를 파지 말고 **thin slice의 F1/F2/F3 착수**로 넘어갈 것.
