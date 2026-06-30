# V2_21 — Festival 중앙 결정 및 세션별 지시서

작성일: 2026-06-30
상태: 실행 지시용 확정안
상위 기준: `V2_20_MASTER_HANDOFF.md`의 Festival/Clarification 결정, `V2_23_STATE_CONTRACT_DIRECTIVE.md`

---

## 0. 중앙 결정

Festival은 V2에서 **도시 랭킹 요소가 아니라 city_select 앞단 게이트**다.

사용자 요청에 `include_festivals=true`가 명시된 경우, Festival Verifier가 먼저 월/도시/날짜 상태를 검증하고, 그 결과로 city_select가 사용할 도시 후보 집합 `allowed_city_ids`를 제한한다. city_select는 축제를 직접 랭킹하지 않는다.

### 날짜 상태 결정

`date_status`는 raw 데이터에 있는 값이 아니라 Festival Verifier가 파생한다.

| date_status | 처리 |
|---|---|
| `confirmed` | 자동 진행 가능. Festival Gate의 유효 후보 F에 포함한다. |
| `tentative` | 자동 진행 금지. 반드시 clarification으로 사용자 확인을 받는다. |
| `outdated` | 제외. clarification 후보로도 자동 사용하지 않는다. |
| `unknown` | 제외. clarification 후보로도 자동 사용하지 않는다. |
| `skipped` | 제외. 검증 불가/대상 외로 본다. |
| `no_candidate` | F=0 clarification. |

`V2_18_FESTIVAL_HANDLING.md`에는 `tentative`를 조용히 fallback으로 진행하는 문장이 남아 있으나, 이 지시서에서는 최신 `V2_20_MASTER_HANDOFF.md`를 우선한다.

### 통일 규칙

- `confirmed`가 하나 이상 있으면 `confirmed`만 F에 포함하고 자동 진행한다.
- `confirmed`가 없고 `tentative`만 있으면 자동 진행하지 않고 `festival_tentative` clarification을 발생시킨다.
- `confirmed`와 `tentative`가 모두 없으면 `festival_none` 또는 `anchor_festival_conflict` clarification을 발생시킨다.
- clarification이 사용자 응답으로 해소되면 이후 흐름은 **anchored 진입**으로 통일한다.
- Festival 관련 fallback은 Festival Verifier 단에서 통일한다. city_select/planner/packager가 각자 축제 fallback을 새로 만들지 않는다.

---

## 1. Clarification 계약

기존 기본 필드 `needs_clarification`, `clarifying_question`, `failure_signals`, `fallback_audit`는 유지한다. 여기에 구조화된 `clarification` 객체를 추가한다.

Verifier의 `no candidate`는 별도 terminal status가 아니다. 모든 중단 상황은 `status=needs_clarification`과 `reason_code`로 표현한다.

```text
Clarification {
  needs_clarification: bool
  reason_code: festival_none | festival_tentative | anchor_festival_conflict | no_candidate_city | contradiction | thin_city
  prompt: string
  options: [
    {
      option_id: string
      label: string
      apply: {
        include_festivals?: bool
        destination_id?: string | null
        destination_label?: string | null
        festival_id?: string | null
        festival_label?: string | null
        allow_tentative_festivals?: bool
        accepted_festival_risk?: bool
        travel_month?: int | null
      }
      then: anchor | rerun_discovery | abort
    }
  ]
  context: object
  failure_signals: string[]
}
```

### reason_code 의미

| reason_code | 사용 조건 |
|---|---|
| `festival_none` | discovery에서 해당 월의 confirmed 축제 도시 F가 0개일 때 |
| `festival_tentative` | confirmed는 없고 tentative 후보만 있을 때 |
| `anchor_festival_conflict` | 사용자가 도시와 축제를 모두 고정했지만 해당 도시/월에 confirmed 축제가 없을 때 |
| `no_candidate_city` | 축제 외 city_select 후보 자체가 없을 때 |
| `contradiction` | intent 조건이 서로 충돌할 때 |
| `thin_city` | 후보 도시는 있으나 evidence가 너무 얇아 추천을 확정하기 어려울 때 |

### option.then 의미

| then | 의미 |
|---|---|
| `anchor` | 사용자 선택으로 도시가 확정되었으므로 destination anchored 경로로 재진입 |
| `rerun_discovery` | 사용자가 조건을 풀거나 바꿨으므로 discovery를 다시 수행 |
| `abort` | 사용자가 추천 조건을 다시 입력해야 하므로 현재 실행 중단 |

### option 규칙

- `option_id`는 UI label과 분리된 stable id다.
- `then=anchor`는 `apply.destination_id`가 반드시 있어야 한다.
- `then=rerun_discovery`는 도시 고정을 해제하거나 조건을 완화한 뒤 discovery부터 다시 돈다. 이때 `apply.destination_id=null`을 명시할 수 있다.
- `then=abort`는 즉시 재실행하지 않고 사용자에게 조건 재입력을 받는다.
- `clarifying_question`은 `clarification.prompt`와 같은 문구를 담아 기존 소비자와 호환한다.
- `failure_signals`는 top-level `failure_signals`와 `clarification.failure_signals`에 같은 값을 넣는다.

### Festival Verifier reason_code별 option

| reason_code | 필수 option |
|---|---|
| `festival_none` | `continue_without_festival` → `apply.include_festivals=false`, `apply.destination_id=null`, `then=rerun_discovery`; `revise_conditions` → `then=abort` |
| `festival_tentative` | tentative 후보별 `accept_tentative_festival` → `apply.include_festivals=true`, `apply.destination_id=<city_id>`, `apply.festival_id=<festival_id>`, `apply.allow_tentative_festivals=true`, `apply.accepted_festival_risk=true`, `then=anchor`; `continue_without_festival` option도 함께 제공 |
| `anchor_festival_conflict` | `continue_without_festival_in_anchor` → `apply.include_festivals=false`, `apply.destination_id=<requested_destination_id>`, `then=anchor`; confirmed 대체 도시가 있으면 도시별 `switch_to_festival_city` → `then=anchor`; 없으면 `revise_conditions` |

---

## 2. FestivalGateResult 계약

Festival Verifier는 `include_festivals=true`일 때만 실행한다. 실행된 Verifier의 top-level status는 아래 둘만 쓴다.

```text
FestivalGateResult {
  status: ok | needs_clarification
  execution_mode: discovery | anchored
  tier: confirmed | tentative | none
  allowed_city_ids: string[]
  verified_festival_cities: [
    {
      ddb_pk: string
      city_id: string
      city_name: string
      festivals: FestivalVerification[]
    }
  ]
  clarification: Clarification | null
  audit: {
    travel_month: int
    target_year: int | null
    requested_destination_id: string | null
    candidate_counts: {
      confirmed: int
      tentative: int
      excluded: int
    }
  }
}
```

### status 규칙

| 상황 | status | tier | clarification |
|---|---|---|---|
| discovery + confirmed 후보 있음 | `ok` | `confirmed` | null |
| discovery + tentative만 있음 | `needs_clarification` | `tentative` | `festival_tentative` |
| discovery + confirmed/tentative 없음 | `needs_clarification` | `none` | `festival_none` |
| anchored + 요청 도시 confirmed 있음 | `ok` | `confirmed` | null |
| anchored + 요청 도시 tentative만 있음 | `needs_clarification` | `tentative` | `festival_tentative` |
| anchored + 요청 도시 confirmed/tentative 없음 | `needs_clarification` | `none` | `anchor_festival_conflict` |

`status=ok`일 때는 `allowed_city_ids`가 비어 있으면 안 된다. `status=needs_clarification`일 때 city_select는 실행하지 않는다.

---

## 3. Festival Verifier 세션 지시

목표: `FestivalGateResult`를 구현하고 Festival fallback의 단일 소유자가 된다.

### 구현 범위

- 입력: `include_festivals`, `travel_month`, `destination_id` 또는 discovery 상태.
- 1차 필터: `travel_month in visit_months`.
- 2차 판정: 목표 여행 연도 기준으로 `event_start_date`/`event_end_date`를 읽어 `date_status` 파생.
- 출력: `FestivalGateResult`.

### 필수 동작

- `confirmed` 후보가 있으면 `status=ok`, `tier=confirmed`.
- `tentative` 후보만 있으면 `status=needs_clarification`, `tier=tentative`, `reason_code=festival_tentative`.
- 후보가 없으면 `status=needs_clarification`, `tier=none`. `status=no_candidate`는 쓰지 않는다.
- anchored 도시가 있고 그 도시가 confirmed F에 없으면 `reason_code=anchor_festival_conflict`.
- outdated/unknown/skipped는 F에서 제외하고, 사용자에게 silent fallback으로 노출하지 않는다.

### 금지

- tentative를 planner에 조용히 넘기지 않는다.
- city_select 안에 festival fallback 분기를 새로 만들지 않는다.
- festival presence를 city score bonus로 쓰지 않는다.

---

## 4. City Select 세션 지시

목표: Festival Verifier가 준 `allowed_city_ids`를 city_select의 후보 제한으로만 사용한다.

### 구현 범위

- `include_festivals=true`이면 city_select 전에 Festival Gate 결과를 받는다.
- `FestivalGateResult.status=ok`일 때만 city_select를 실행한다.
- discovery에서는 `allowed_city_ids = verified_festival_cities[].city_id`.
- anchored에서는 기존 `destination_id`가 confirmed F에 포함될 때만 진행한다.
- `needs_clarification`이면 retrieval/rescore를 실행하지 않고 clarification package를 반환한다.

### 금지

- city_select가 festival 후보를 직접 DynamoDB에서 다시 찾지 않는다.
- city_select가 tentative 여부를 재판정하지 않는다.
- city_select가 축제 여부로 도시 점수를 가산하지 않는다.

---

## 5. Planner 세션 지시

목표: 확정된 도시의 confirmed festival만 일정 seed로 반영한다.

### 구현 범위

- Planner는 Festival Verifier가 통과시킨 `FestivalVerification`만 받는다.
- selected city에 포함된 festival은 must-include seed로 본다.
- 날짜가 confirmed인 축제만 자동 배치한다.
- 사용자가 `festival_tentative` clarification에서 위험을 명시 수락한 경우에만 tentative festival을 planner note 또는 optional seed로 처리한다.

### 금지

- Planner가 직접 festival date를 검증하지 않는다.
- outdated/unknown/skipped 축제를 일정에 자동 삽입하지 않는다.
- tentative를 confirmed처럼 표현하지 않는다.

---

## 6. Packager/API 세션 지시

목표: clarification을 사용자에게 구조적으로 전달하고 resume에 필요한 patch를 보존한다.

### 구현 범위

- 응답에는 기존 `needs_clarification`, `clarifying_question`를 유지한다.
- 추가로 `clarification` 객체를 그대로 노출한다.
- UI/API는 `options[].label`을 선택지로 보여주고, 선택된 option의 `apply`를 resume patch로 사용한다.
- `then=anchor`이면 resume state에 `destination_id`와 `include_festivals`를 반영한다.
- `then=rerun_discovery`이면 intent를 patch한 뒤 discovery부터 다시 실행한다.
- `then=abort`이면 현재 run을 종료하고 조건 재입력을 요구한다.
- state 저장 위치는 `state.festival_gate.clarification`과 `state.response.clarification`을 사용한다. `candidate_evidence_package`에는 저장하지 않는다.

### 금지

- clarification option label만 저장하고 apply patch를 잃어버리지 않는다.
- `needs_clarification=true`인데 prompt/options 없는 응답을 만들지 않는다.

---

## 7. 테스트 수락 기준

각 세션은 자기 파트에서 아래 케이스를 최소 단위 테스트로 잠근다.

| 케이스 | 기대 |
|---|---|
| discovery + festival + confirmed 존재 | Festival Gate ok → city_select allowed_city_ids 제한 |
| discovery + festival + tentative만 존재 | `festival_tentative` clarification |
| discovery + festival + 후보 없음 | `festival_none` clarification |
| anchored city + confirmed festival 존재 | anchored city_select 진행 |
| anchored city + festival 없음 | `anchor_festival_conflict` clarification |
| outdated/unknown/skipped만 존재 | F=0 취급, 자동 진행 없음 |

통합 smoke에서는 `include_festivals=false` 기존 경로가 영향받지 않는지 함께 확인한다.

---

## 8. 실행 순서

1. **Schema/Packager 세션**: `Clarification` 계약과 응답 직렬화 확정.
2. **Festival Verifier 세션**: `FestivalGateResult`, `date_status` 파생, clarification 생성 구현.
3. **City Select 세션**: Festival Gate 결과를 받아 후보 제한/중단 처리.
4. **Planner 세션**: confirmed festival seed 반영과 tentative 수락 시 표현 정책 정리.
5. **통합 세션**: retrieval smoke + festival scenario smoke로 전체 회귀 확인.

이 순서를 지켜야 downstream 세션이 임시 필드를 만들지 않고 같은 계약을 공유할 수 있다.
