# V2_23 — Canonical State Contract 지시서

작성일: 2026-06-30
상태: 실행 지시용 확정안
상위 기준: `V2_15_TASK1_CITY_SELECT_HANDOFF.md`, `V2_20_MASTER_HANDOFF.md`, `V2_21_FESTIVAL_DIRECTIVE.md`, `V2_22_RESPONSE_CLARIFICATION_DIRECTIVE.md`

---

## 0. 중앙 결정

V2의 중앙 계약은 **`core/state.py::UnifiedAgentState`** 다.

앞으로 세션 간 지시와 구현은 V1의 `CandidateEvidenceInput`, `CandidateEvidencePackage`, `CandidateReasonClaim`을 state/API 정본으로 참조하지 않는다. 해당 이름은 포팅 과정에서 남은 legacy 명칭이며, V2 최종 계약에서는 제거 대상이다.

### 금지어

V2 state, V2 public response, V2 세션 지시서 신규 작성에는 아래 이름을 쓰지 않는다.

- `CandidateEvidenceInput`
- `CandidateEvidencePackage`
- `CandidateReasonClaim`
- `candidate_evidence_input`
- `candidate_evidence_package`

예외는 legacy 제거 작업을 설명할 때뿐이다. 예외 문장은 반드시 “legacy 제거 대상”이라고 명시한다.

### 대체 이름

| legacy | V2 정본 |
|---|---|
| `CandidateEvidenceInput` | `CitySelectInput` |
| `candidate_evidence_input` | `city_select_input` |
| `CandidateEvidencePackage` | `CitySelectionResult` 또는 `CitySelectResult` |
| `candidate_evidence_package` | `city_selection_result` |
| `CandidateReasonClaim` | `selection_reason_code` + downstream prose |

---

## 1. UnifiedAgentState top-level groups

`UnifiedAgentState`는 아래 top-level group을 가진다. 노드는 자기 group과 downstream에 필요한 최소 group만 읽고, 다른 노드의 내부 audit 구조를 직접 해석하지 않는다.

```text
UnifiedAgentState {
  request: RequestState
  intent: IntentState
  profile: ProfileState
  festival_gate: FestivalGateState
  city_select: CitySelectState
  planner: PlannerState
  response: ResponseState
  routing: RoutingState
  memory: MemoryState
  trace: TraceState
}
```

### group 소유권

| group | writer | 주요 reader |
|---|---|---|
| `request` | API entrypoint | intent, profile, festival_gate, city_select, planner, response |
| `intent` | Intent 세션 | profile, festival_gate, city_select, planner |
| `profile` | Profile 세션 | city_select, planner |
| `festival_gate` | Festival Verifier 세션 | city_select, planner, response |
| `city_select` | City Select 세션 | planner, response |
| `planner` | Planner 세션 | response |
| `response` | Response Packager 세션 | API layer |
| `routing` | Supervisor/Core graph | all nodes read only as needed |
| `memory` | Checkpointer/Resume layer | supervisor, resume handler |
| `trace` | Core/telemetry | diagnostics only |

---

## 2. RequestState

`request`는 raw API 입력에서 온 불변 실행 기준이다. downstream node가 임의로 수정하지 않는다. 사용자 선택으로 조건이 바뀌면 resume patch가 새 state revision을 만든다.

```text
RequestState {
  request_id: string
  user_id: string | null
  country: string
  travel_month: int
  travel_year: int | null
  trip_type: string
  destination_id: string | null
  include_festivals: bool
  themes: string[]
  raw_query: string
  user_location: GeoPoint | null
}
```

`destination_id`는 request가 전달하는 유일한 목적지 식별자다. `city_key/ddb_pk/destination_label`은 request field가 아니라 deterministic resolver가 내부 state에 보강하는 값이다.

`transport_pref`와 `congestion_pref`는 request field가 아니라 Intent가 `raw_query`에서 파싱해 `CitySelectInput`/`PlannerIntent`에 쓰는 값이다.

---

## 3. IntentState

`intent`는 raw query를 구조화한 결과이며, City Select 입력을 직접 보유한다.

```text
IntentState {
  cleaned_raw_query: string
  soft_preference_query: string
  unsupported_conditions: string[]
  contradictions: string[]
  city_select_input: CitySelectInput | null
  planner_intent: object | null
  modify_intent: object | null
}
```

### CitySelectInput 정본

`city_select_input`의 내부 타입명은 `CitySelectInput`이다.

```text
CitySelectInput {
  country: string
  travel_month: int
  travel_year: int
  trip_type: string
  active_required_themes: string[]
  include_festivals: bool
  cleaned_raw_query: string
  soft_preference_query: string
  unsupported_conditions: string[]
  destination_id: string | null
  destination_label: string | null
  city_key: string | null
  ddb_pk: string | null
  user_location: GeoPoint | null
  execution_mode: city_discovery | anchored_place_search | festival_seeded_city_discovery
  congestion_pref: quiet | vibrant | neutral
  transport_pref: walk | car | unknown
  theme_weights: object | null
}
```

`state.intent.candidate_evidence_input`는 금지다. 현재 코드에 남아 있으면 `state.intent.city_select_input`으로 치환한다.

---

## 4. ProfileState

Profile은 request와 장기 선호를 결합해 `effective_theme_weights`를 만든다. City Select는 profile 원본을 해석하지 않고 결합된 결과만 소비한다.

```text
ProfileState {
  saved_trip_count: int
  profile_theme_weights: object
  effective_theme_weights: object | null
  applied_persona_id: string | null
  audit: object
}
```

`effective_theme_weights`가 있으면 `CitySelectInput.theme_weights`에 반영한다. 없으면 City Select가 균등 가중치로 fallback한다.

---

## 5. FestivalGateState

Festival은 city_select 앞단 게이트다. Festival 결과는 `festival_gate` group에 저장한다.

```text
FestivalGateState {
  result: FestivalGateResult | null
  allowed_city_ids: string[]
  clarification: Clarification | null
  audit: object
}
```

`FestivalGateResult`와 `Clarification`의 세부 계약은 `V2_21_FESTIVAL_DIRECTIVE.md`를 따른다. City Select는 festival 후보를 다시 찾지 않고 `festival_gate.allowed_city_ids`만 읽는다.

---

## 6. CitySelectState

City Select 결과의 정본은 `CitySelectionResult`다.

```text
CitySelectState {
  city_selection_result: CitySelectionResult | null
  status: ok | needs_clarification | no_candidate | error
  clarification: Clarification | null
  retrieval_audit: object
  scoring_audit: object
}
```

### CitySelectionResult 정본

```text
CitySelectionResult {
  selected_city: {
    city_id: string
    city_name_ko: string
    ddb_pk: string
    province: string | null
    country: string
  }
  selection_reason_code: string[]
  alternative_city: object | null
  seeds: object[]
  headline_seed: string | null
  theme_evidence: object[]
  missing_themes: string[]
  passthrough: object
  score_breakdown: object
  retrieval_audit: object
}
```

`CandidateEvidencePackage`는 V2 state에 저장하지 않는다. 실패/되묻기 상황도 `CitySelectState.status`와 `CitySelectState.clarification`으로 표현한다.

---

## 7. PlannerState

Planner는 city selection result와 festival gate result를 읽어 itinerary를 만든다.

```text
PlannerState {
  planner_output: PlannerOutput | null
  validation_result: object
  modification: object | null
  alternative_itinerary: object[] | null
  audit: object
}
```

Planner는 City Select의 내부 retrieval audit를 사용자 설명으로 직접 쓰지 않는다. 필요한 설명 재료는 `CitySelectionResult.theme_evidence`, `seeds`, `selection_reason_code`에서 읽는다.

---

## 8. ResponseState

Response Packager가 최종 public payload를 저장한다.

```text
ResponseState {
  response_status: completed | END_WAIT_USER | modification_pending
  response_payload: RecommendationResponse | null
  clarification: Clarification | null
}
```

public response 계약은 `V2_22_RESPONSE_CLARIFICATION_DIRECTIVE.md`를 따른다.

---

## 9. RoutingState / MemoryState / TraceState

```text
RoutingState {
  next_node: string | null
  completed_groups: string[]
  needs_clarification: bool
  clarification_reason_code: string | null
}

MemoryState {
  checkpoint_id: string | null
  pending_clarification: Clarification | null
  last_resume_patch: object | null
}

TraceState {
  run_id: string
  visited_nodes: string[]
  warnings: string[]
  node_timings: object
}
```

Resume은 `MemoryState.pending_clarification.options[]`에서 `selectedOptionId`를 찾아 `apply`와 `then`을 복원한다.

---

## 10. 세션별 지시

### Core/Schema 세션

- `core/state.py`의 `UnifiedAgentState`를 위 top-level group으로 구체화한다.
- legacy `CandidateEvidence*` 이름을 새 state 계약에 추가하지 않는다.
- 필요한 경우 legacy adapter는 별도 임시 함수로 두되, state 필드명은 V2 정본을 쓴다.

### City Select 세션

- state 입력은 `state["intent"]["city_select_input"]`만 읽는다.
- 출력은 `state["city_select"]["city_selection_result"]`에 쓴다.
- `state["intent"]["candidate_evidence_input"]`와 `state["evidence"]["candidate_evidence_package"]`를 제거한다.

### Festival 세션

- 출력은 `state["festival_gate"]`에 쓴다.
- city_select의 내부 state를 수정하지 않는다.
- clarification은 `festival_gate.clarification`에 둔다.

### Planner 세션

- 입력은 `city_select.city_selection_result`와 `festival_gate.result`를 기준으로 한다.
- V1 candidate evidence package를 읽지 않는다.

### Response Packager 세션

- 입력은 `planner`, `city_select`, `festival_gate`, `routing`, `response.clarification`이다.
- public response는 `response.response_payload`에 저장한다.
- optional clarification은 `V2_22` 방식으로 직렬화한다.

---

## 11. 완료 기준

코드 정합 완료 기준:

```text
grep -rn "CandidateEvidence\|candidate_evidence_package\|candidate_evidence_input\|CandidateReasonClaim" src/lovv_agent_v2
```

결과가 0건이어야 한다.

문서 정합 완료 기준:

- 새 지시서에서는 legacy 이름 금지.
- 과거 포팅 문서에 남은 legacy 이름은 “legacy 제거 대상” 또는 “과거 baseline”으로만 해석.
- downstream 지시서는 이 문서의 `UnifiedAgentState` group 이름을 기준으로 작성.
