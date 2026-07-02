# V2_36 — Interrupt Handling Matrix

작성일: 2026-07-02

상태: 초안

상위 기준:

- `V2_21_FESTIVAL_DIRECTIVE.md`
- `V2_22_RESPONSE_CLARIFICATION_DIRECTIVE.md`
- `V2_30_MODIFY_REQUEST_SCHEMA.md`
- `V2_34_MODIFY_INTENT_SCHEMA.md`
- `0702_tasks.md` §11-12

---

## 0. 목적

이 문서는 V2에서 사용자 재입력이 필요한 모든 케이스를 하나의 matrix로 고정한다.

핵심 구분은 두 가지다.

1. **Clarification interrupt**
   - graph 실행 중 `END_WAIT_USER` 응답을 만들고 LangGraph `interrupt()`로 멈춘다.
   - 같은 `thread_id`에 대해 `Command(resume=...)`로 이어간다.
   - 사용자는 `optionId`만 선택한다. 자연어 답변이면 Intent가 기존 option 중 하나로 resolve한다.

2. **Modification request**
   - 초회 일정은 `modification_pending` 응답으로 끝난다.
   - graph가 계속 대기 중일 필요는 없다.
   - 이후 수정 요청은 같은 `thread_id` checkpoint를 읽어 새 invocation으로 처리한다.

---

## 1. 공통 불변식

### Option 불변식

- `optionId`, `apply`, `then`은 clarification option 생성 시점에 서버가 확정한다.
- 사용자는 `optionId`만 보낸다.
- 자연어 응답은 Intent가 checkpoint의 pending options 중 하나로 resolve한다.
- resume 처리 시 `apply`와 `then`은 사용자 payload가 아니라 checkpoint에 저장된 option 원본에서 복원한다.
- Intent는 새 option을 만들지 않는다.
- Resolve가 애매하거나 기존 option 밖의 요청이면 실행하지 않고 다시 묻는다.

### State 불변식

- pending clarification은 checkpoint에 남아 있어야 한다.
- `END_WAIT_USER` 응답에는 public `clarification` block이 반드시 있어야 한다.
- `modification_pending` 응답에는 수정 가능한 full itinerary와 같은 `thread_id`가 남아 있어야 한다.
- 수정 요청 시 checkpoint state가 없으면 planner edit mode로 들어가지 않는다.

### then 불변식

현재 `ClarificationOption.then` 허용값은 아래 3개다.

| then | 의미 |
|---|---|
| `anchor` | destination anchored 경로로 재진입 |
| `rerun_discovery` | 조건 patch 후 city discovery부터 재시도 |
| `abort` | 현재 실행 중단, 사용자에게 조건 재입력 요청 |

수정 intent clarification을 option-resume으로 태우려면 향후 `planner_apply_edit` 또는 `apply_modify` 같은 then 확장이 필요하다. V2.0 초안에서는 modify clarification을 별도 확정하지 않는다.

---

## 2. Top-Level Matrix

| flow | trigger | response_status | LangGraph interrupt | next user input | checkpoint 필요 | owner |
|---|---|---:|---:|---|---:|---|
| 초회 생성 성공 | planner/packager 완료 | `modification_pending` | no | modify request 또는 저장 확정 | yes | Response Packager |
| 축제 재질문 | festival gate `needs_clarification` | `END_WAIT_USER` | yes | `resume.optionId` 또는 자연어 답변 | yes | Festival Verifier + Intent resolver |
| intent 입력 불가 | 모순/너무 짧음/한국 외 | `END_WAIT_USER` | yes | 조건 재입력 | yes | Intent |
| 수정 요청 | `entryType=modify` | `modification_pending` 또는 notice | no | 추가 수정/저장 | yes | Intent + Planner |
| 수정 요청인데 checkpoint 없음 | missing/expired thread | `END_WAIT_USER` 또는 notice | no | 새 일정 생성 | no | Entrypoint/Supervisor/Packager |
| 일정 저장 확정 | `entryType=confirm` 또는 save event | terminal end | no | 없음 | optional | Profile |

---

## 3. Intent Interrupt Matrix

초기 production intent가 직접 생성하는 clarification은 `abort` 단일 option으로 시작한다.

| case | reasonCode | optionId | apply | then | resume 후 처리 |
|---|---|---|---|---|---|
| 모순된 입력 | `contradiction` | `revise_conditions` | `{}` | `abort` | 현재 run 종료, 새 조건 입력 요청 |
| 너무 짧은 입력 | `underspecified` | `revise_conditions` | `{}` | `abort` | 현재 run 종료, 새 조건 입력 요청 |
| 범위 밖, 한국 외 | `out_of_scope_region` | `revise_conditions` | `{}` | `abort` | 현재 run 종료, KR 범위 안내 |

Intent가 처리하는 자연어 clarification answer는 별도 option을 만들지 않는다.

| answer type | input | output | execution |
|---|---|---|---|
| button | `selectedOptionId` 또는 `optionId` | existing optionId | resume |
| natural language resolved | "축제 빼고 계속" | existing optionId | resume |
| ambiguous | "음... 아무거나" | unresolved | 재질문 |
| out-of-option request | "제주로 바꿔" | unsupported | 재질문 또는 abort |

---

## 4. Festival Interrupt Matrix

Festival Verifier는 V2.0에서 구조화 clarification option을 실제 생성하는 주 agent다.

### festival_none

| optionId | label intent | apply | then | resume 후 처리 |
|---|---|---|---|---|
| `continue_without_festival` | 축제 없이 계속 | `{"includeFestivals": false, "destinationId": null}` | `rerun_discovery` | festival verifier skip, city discovery |
| `search_any_festival_theme` | 테마 상관 없이 축제 검색 | `{"includeFestivals": true, "destinationId": null, "activeRequiredThemes": [], "festivalThemeAgnostic": true}` | `rerun_discovery` | theme filter 없이 festival verifier 재시도 |
| `revise_conditions` | 조건 다시 입력 | `{}` | `abort` | 현재 run 종료 |

`search_any_festival_theme`은 기존 테마 필터 때문에 축제 후보가 0개가 된 경우를 위한 fallback이다. 재시도 시 festival verifier의 `theme_pool`을 비우거나 festival generic token만 남겨 `specific_theme_tokens(theme_pool)`이 빈 set이 되게 한다.

### festival_tentative

| optionId | label intent | apply | then | resume 후 처리 |
|---|---|---|---|---|
| `accept_tentative_festival:{festivalId}` | 잠정 일정 위험 수락 | `{"includeFestivals": true, "destinationId": "<cityId>", "festivalId": "<festivalId>", "allowTentativeFestivals": true, "acceptedFestivalRisk": true}` | `anchor` | 해당 도시 anchored 경로 |
| `continue_without_festival` | 축제 없이 계속 | `{"includeFestivals": false, "destinationId": null}` | `rerun_discovery` | festival verifier skip, city discovery |

### anchor_festival_conflict

| optionId | label intent | apply | then | resume 후 처리 |
|---|---|---|---|---|
| `continue_without_festival_in_anchor` | 이 도시에서 축제 없이 계속 | `{"includeFestivals": false, "destinationId": "<requestedDestinationId>"}` | `anchor` | 같은 도시 anchored planner |
| `switch_to_festival_city:{cityId}` | 축제 있는 도시로 변경 | `{"includeFestivals": true, "destinationId": "<cityId>", "festivalId": "<festivalId>"}` | `anchor` | 대체 도시 anchored path |
| `revise_conditions` | 조건 다시 입력 | `{}` | `abort` | 현재 run 종료 |

---

## 5. City Select Matrix

City Select는 clarification option을 만들지 않는다.

| possible issue | owner | reason |
|---|---|---|
| discovery city 후보 없음 | none in V2.0 | 전국/전 지역 pool에서 city ranking은 실질적으로 생성된다 |
| anchored 도시가 얇음 | Planner | anchored 요청은 city_select를 건너뛴다 |
| 축제 조건 때문에 도시 제한 | Festival Verifier | `allowed_city_ids`를 city_select 앞단에서 만든다 |
| 후보 부족/일정 수량 부족 | Planner | in-city retrieval/route/validation 이후에만 판단 가능 |

따라서 city_select 관련 interrupt/fallback option은 V2.0 matrix에서 0개다.

---

## 6. Planner / Modification Matrix

### 초회 생성

Planner가 일정을 만들면 Response Packager는 `modification_pending`으로 반환한다.

| case | response_status | interrupt | next |
|---|---|---:|---|
| 정상 일정 생성 | `modification_pending` | no | 사용자가 저장 확정 또는 수정 요청 |
| 후보가 얇지만 일정은 만들 수 있음 | `modification_pending` + notice | no | 사용자가 수정 요청 가능 |
| anchored 도시 후보 부족으로 일정 품질 낮음 | `modification_pending` + notice | no | 사용자가 anchor 해제/조건 변경을 수정 요청 |

초회 생성 완료 후 graph는 END로 끝나도 된다. checkpointer가 같은 `thread_id`의 최종 state를 저장하면 수정 요청은 가능하다.

### 수정 요청

수정은 interrupt resume이 아니라 새 invocation이다.

| case | entry | checkpoint | result |
|---|---|---|---|
| non-seed slot replace | `entryType=modify` | required | Planner edit mode |
| seed same-theme replace | `entryType=modify` | required | Planner edit mode, same-theme guard |
| reset / "다 별로야" | `entryType=modify` | required | session avoid 후 rediscovery |
| unsupported backlog | `entryType=modify` | optional | notice |
| checkpoint 없음/만료 | `entryType=modify` | missing | 새 일정 생성 요청 안내 |

### 수정 clarification

V2.0 초안에서는 modify clarification option set을 확정하지 않는다.

이유:

- 현재 `then` enum이 `anchor | rerun_discovery | abort`라 planner edit 재개를 표현하기 어렵다.
- target ambiguity는 `target:{itemId}` 같은 option을 만들 수 있지만, resume 후 목적지는 planner edit mode다.
- 따라서 modify clarification을 구조화 option으로 태우려면 `then=planner_apply_edit` 또는 `then=apply_modify` 확장이 먼저 필요하다.

임시 처리:

| case | 처리 |
|---|---|
| target ambiguous | `END_WAIT_USER`로 묻되 실행하지 않음. 다음 modify utterance에서 다시 parse |
| target unresolved | notice 또는 `END_WAIT_USER`, 새 수정 문장 요청 |
| op contradiction | `END_WAIT_USER`, 수정 조건 재입력 요청 |
| unsupported backlog | `modification_pending` 또는 notice, 기존 일정 유지 |

---

## 7. Profile / Save Matrix

Profile은 interrupt option을 만들지 않는다.

| case | entry | response | profile write |
|---|---|---|---|
| 사용자가 일정 저장 확정 | save/confirm event | terminal END | yes |
| 초회 생성만 완료 | generation | `modification_pending` | no |
| 수정 중간 발화 | modify | `modification_pending` | no |
| clarification answer | resume | downstream 재실행 | no |

장기 profile 업데이트는 저장 확정된 일정에서만 수행한다.

---

## 8. Entrypoint/API Matrix

| request shape | meaning | graph payload |
|---|---|---|
| generation request 또는 mock intent | 초회 생성 | initial state |
| `resume` / `resumeValue` with optionId | clarification 선택 | `Command(resume=...)` |
| natural language clarification answer | pending option resolve 필요 | Intent resolver 후 `Command(resume=optionId)` |
| `entryType=modify` | 일정 수정 | checkpoint load + modify intent |
| save/confirm event | 일정 확정 저장 | profile write path |

API 응답 규칙:

- `END_WAIT_USER`는 HTTP error가 아니다. 정상 200 response로 반환한다.
- `modification_pending`도 정상 200 response다.
- checkpoint가 없는 modify request는 planner 실행 실패가 아니라 사용자 안내 응답이다.

---

## 9. 구현 순서

1. Festival Verifier
   - `festival_none`에 `search_any_festival_theme` option 추가.
   - resume patch에 `activeRequiredThemes=[]` 또는 `festivalThemeAgnostic=true`를 반영.
2. Intent
   - `contradiction`, `underspecified`, `out_of_scope_region`을 abort-only clarification으로 반환.
   - 자연어 clarification answer를 checkpoint pending option으로 resolve.
3. Supervisor / Resume
   - checkpoint option 원본에서 `apply/then` 복원.
   - `then=rerun_discovery`, `then=anchor`, `then=abort` routing 구현.
4. Modify
   - checkpoint 없는 modify request를 명시 안내로 처리.
   - modify clarification option 확장은 `then` enum 확정 후 진행.

---

## 10. 수락 기준

| scenario | expected |
|---|---|
| `festival_none` response | `END_WAIT_USER`, options에 `continue_without_festival`, `search_any_festival_theme`, `revise_conditions` 포함 |
| `search_any_festival_theme` resume | festival verifier 재시도 시 theme filter 미적용 |
| natural language "축제 빼고 계속" | 기존 `continue_without_festival` option으로 resolve |
| intent contradiction | `END_WAIT_USER`, `revise_conditions -> abort` 단일 option |
| city_select path | clarification option 생성 없음 |
| generation success | `modification_pending`, interrupt 없음, checkpoint 저장 |
| modify with valid checkpoint | planner edit mode 진입 |
| modify without checkpoint | planner 실행 없이 새 일정 생성 안내 |

