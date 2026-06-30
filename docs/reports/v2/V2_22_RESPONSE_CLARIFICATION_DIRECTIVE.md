# V2_22 — Response Clarification 지시서

작성일: 2026-06-30
상태: 실행 지시용 확정안
상위 기준: `V2_21_FESTIVAL_DIRECTIVE.md`, `V2_23_STATE_CONTRACT_DIRECTIVE.md`, 현재 구현된 recommendation response packager shape

---

## 0. 중앙 결정

V2는 public response schema를 새로 갈아엎지 않는다.

현재 구현된 public 응답은 recommendation response 1종이며, graph의 `ServingState.response_status`가 `completed` 또는 `END_WAIT_USER`로 해석 상태를 나눈다. V2 clarification은 이 기존 response 위에 **optional `clarification` block만 additive로 추가**한다.

즉, 기존 소비자는 계속 아래 필드만으로 동작할 수 있어야 한다.

- `response_status`
- `explainability.userNotice`
- `itinerary.days`
- `destination`

새 소비자는 optional `clarification`을 읽어 버튼 선택과 resume patch를 결정한다.

---

## 1. 현재 유지할 public response

기존 packager의 기본 response shape는 유지한다.

```text
RecommendationResponse {
  recommendationId: string
  expiresAt: string
  destination: {
    destinationId: string | null
    name: string | null
    country: string
    region: string | null
  }
  itinerary: {
    tripType: string
    days: [
      {
        day: int
        items: [
          {
            itemId: string
            contentId: string | null
            timeOfDay: string | null
            sortOrder: int
            title: string | null
            body: string | null
            reason: string | null
            moveMinutes: number | null
            latitude: number | null
            longitude: number | null
          }
        ]
      }
    ]
  }
  explainability: {
    matchedConditions: string[]
    unsupportedConditions: string[]
    recommendationReasons: string[]
    itineraryFlowReason: string
    confidence: number
    userNotice: string
  }
  festivalDateVerifications: [
    {
      festivalId: string
      dateStatus: string
      startDate: string | null
      endDate: string | null
      sourceUrl: string | null
      confidence: number
    }
  ]
  links: object
}
```

V2는 위 구조를 삭제하거나 이름 변경하지 않는다.

---

## 2. 추가할 optional block

Clarification이 필요한 응답에만 top-level `clarification`을 추가한다.

```text
RecommendationResponse {
  ...existing fields
  clarification?: Clarification | null
}

Clarification {
  reasonCode: festival_none | festival_tentative | anchor_festival_conflict | no_candidate_city | contradiction | thin_city
  prompt: string
  options: [
    {
      optionId: string
      label: string
      apply: {
        includeFestivals?: bool
        destinationId?: string | null
        destinationLabel?: string | null
        festivalId?: string | null
        festivalLabel?: string | null
        allowTentativeFestivals?: bool
        acceptedFestivalRisk?: bool
        travelMonth?: int | null
      }
      then: anchor | rerun_discovery | abort
    }
  ]
  context: object
  failureSignals: string[]
}
```

### naming 결정

- 내부 node 계약은 snake_case를 써도 된다.
- public response는 기존 response 관례에 맞춰 camelCase를 쓴다.
- Packager가 `reason_code → reasonCode`, `option_id → optionId`, `include_festivals → includeFestivals`처럼 변환한다.

---

## 3. 상태별 응답 규칙

| 상태 | `response_status` | 기존 response | `clarification` |
|---|---|---|---|
| 정상 추천 완료 | `completed` | itinerary 채움 | null 또는 미포함 |
| 사용자 확인 필요 | `END_WAIT_USER` | itinerary 비어 있을 수 있음, `userNotice` 채움 | 반드시 포함 |
| 수정 완료 후 추가 수정 대기 | `modification_pending` | full itinerary + modification summary | 일반적으로 미포함. 추가 확인이 필요하면 포함 가능 |

`END_WAIT_USER`에서 `clarification`이 없으면 V2 계약 위반이다. 단, 기존 소비자 호환을 위해 `explainability.userNotice`에는 `clarification.prompt`와 같은 문구를 넣는다.

---

## 4. Packager 세션 지시

목표: 기존 response shape를 유지하면서 `clarification`만 선택적으로 추가한다.

### 구현 범위

- 현재 구현된 `package_recommendation_response()` shape를 V2 public envelope 기준으로 삼는다.
- `ServingState.response_status`는 기존처럼 graph가 소유한다.
- Packager는 state에 구조화된 clarification이 있으면 top-level `clarification`으로 직렬화한다.
- `END_WAIT_USER`일 때는 `explainability.userNotice = clarification.prompt`.
- planner output이 없더라도 기존처럼 빈 itinerary를 반환한다.
- 내부 audit 전체를 response에 노출하지 않는다.
- 입력 state는 `V2_23`의 `state.response.clarification`, `state.festival_gate.clarification`, `state.city_select.city_selection_result`, `state.planner.planner_output`을 기준으로 한다.

### 금지

- `END_WAIT_USER` 전용 별도 response envelope를 만들지 않는다.
- `recommendationId`, `destination`, `itinerary`, `explainability`, `festivalDateVerifications`, `links`를 제거하거나 이름 변경하지 않는다.
- Verifier의 raw audit를 그대로 public response에 덤프하지 않는다.
- UI label만 넘기고 resume patch를 잃어버리지 않는다.

---

## 5. Backend/API 세션 지시

목표: public API의 breaking change 없이 V2 clarification을 통과시킨다.

### 구현 범위

- 기존 response DTO가 있으면 optional `clarification` 필드만 추가한다.
- 기존 클라이언트가 `clarification`을 무시해도 응답 파싱이 깨지지 않아야 한다.
- `response_status=END_WAIT_USER`인 응답은 HTTP error가 아니라 정상 200 응답이다.
- resume endpoint는 선택된 option의 `apply`와 `then`을 받을 수 있어야 한다.
- 서버가 `optionId`만 받는 경우, checkpoint에 저장된 clarification에서 option을 찾아 `apply`를 복원한다.

### 권장 resume 요청

```text
ResumeRequest {
  recommendationId: string
  selectedOptionId: string
}
```

서버는 checkpoint의 원본 `clarification.options[]`에서 `selectedOptionId`를 찾고, 해당 option의 `apply`와 `then`을 적용한다.

### 허용 대안

```text
ResumeRequest {
  recommendationId: string
  apply: object
  then: anchor | rerun_discovery | abort
}
```

이 대안은 front가 apply payload를 그대로 보존해야 하므로 1차 구현에서는 `selectedOptionId` 방식을 우선한다.

---

## 6. Front/API 소비 규칙

목표: 기존 단문 안내 UI와 V2 선택지 UI를 모두 지원한다.

- `clarification`이 없으면 기존처럼 `explainability.userNotice`만 표시한다.
- `clarification`이 있으면 `prompt`와 `options[].label`을 표시한다.
- 사용자가 선택하면 `selectedOptionId`를 resume endpoint로 보낸다.
- front는 `apply`를 직접 해석하지 않아도 된다.
- 단, 디버그/미리보기 목적이면 `apply`를 표시하지 않는다.

---

## 7. 테스트 수락 기준

| 케이스 | 기대 |
|---|---|
| completed recommendation | 기존 response shape 유지, `clarification` 없음 |
| END_WAIT_USER + festival_none | `userNotice=prompt`, `clarification.reasonCode=festival_none`, options 포함 |
| END_WAIT_USER + festival_tentative | tentative 수락 option에 `allowTentativeFestivals=true`, `acceptedFestivalRisk=true` |
| END_WAIT_USER + anchor_festival_conflict | anchored 유지/대체 도시/조건 재입력 option 중 해당 option 포함 |
| legacy client parse | `clarification`을 무시해도 기존 필드 파싱 성공 |
| resume selectedOptionId | checkpoint option에서 `apply` 복원 후 `then`에 맞게 재진입 |

---

## 8. 세션별 실행 순서

1. **Schema 세션**: internal snake_case Clarification 모델과 public camelCase 직렬화 규칙 추가.
2. **Packager 세션**: 기존 recommendation response 유지 + optional `clarification` 추가.
3. **Backend/API 세션**: response DTO optional field, resume `selectedOptionId` 처리.
4. **Festival Verifier 세션**: `FestivalGateResult.clarification` 생성.
5. **통합 세션**: `END_WAIT_USER` response와 resume 재진입 smoke.
