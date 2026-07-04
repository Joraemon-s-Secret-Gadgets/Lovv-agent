# V2_42 — 일정 수정 트러블슈팅 기록

작성일: 2026-07-03

상태: live smoke 기반 트러블슈팅 한글판

관련 문서:

- `V2_34_MODIFY_INTENT_SCHEMA.md`
- `V2_38_INTENT_FRONTEND_INPUT_CONTRACT.md`
- `V2_39_INTENT_PROCESSING_OUTPUT_SCHEMA.md`
- `V2_41_ROUTE_DAYS_SMOKE_CASEBOOK.md`

---

## 0. 목적

이 문서는 V2 일정 수정 경로를 live smoke로 검증하면서 발견한 문제, 원인, 수정 방향을 한글로 정리한다.

범위:

- 도시 변경 수정 요청의 timeout 원인
- supervisor routing loop 수정
- live smoke 재검증 결과
- 장소 교체 수정 설계 메모
- 복합 수정 요청에 대한 intent 차단 필요성

---

## 1. 도시 변경 live smoke timeout

### 시나리오

새 AgentCore checkpoint session에서 다음 순서로 실행했다.

1. 일반 탐색 생성
   - `destinationId` 없음
   - query: `조용한 바다 산책과 해안 풍경 위주로 2박 3일 일정`
   - theme: `바다·해안`
   - festival: false
2. 같은 session에서 수정 요청
   - `rawModifyQuery`: `도시는 강릉으로 바꿔줘.`

초기 실행은 150초 timeout에 걸렸다.

### 관측

flush log를 남기는 live stream으로 재실행했을 때, 첫 번째 timeout은 네트워크 지연이 아니라 graph routing loop였다.

초기 loop:

```text
intent
-> supervisor
-> planner
-> supervisor
-> planner
-> supervisor
-> ...
```

원인:

- `intent.modify_intent.routing_hint = planner_direct_anchor`
- supervisor가 city-change direct-anchor modify를 planner로 보내는 조건에서 `planner.planner_output` 존재 여부를 보지 않았다.
- 따라서 planner가 이미 완료되어도 stale response보다 먼저 planner route가 다시 선택됐다.

1차 수정 후에는 planner loop는 사라졌지만, 다음 loop가 드러났다.

```text
planner
-> supervisor
-> explain_itinerary
-> supervisor
-> response_packager
-> supervisor
-> response_packager
-> supervisor
-> ...
```

원인:

- 도시 변경 수정 중에는 기존 `response.response_payload`를 stale response로 무시해야 한다.
- 하지만 response packager가 새 response를 만든 뒤에도 supervisor가 "현재 수정 요청에 대한 새 response"와 "이전 create response"를 구분하지 못했다.
- 그 결과 response packager 이후에도 다시 response packager로 라우팅했다.

---

## 2. 수정 내용

수정 파일:

- `src/lovv_agent_v2/agents/supervisor/router.py`

수정 원칙:

1. city-change direct-anchor route는 planner output이 없을 때만 planner로 보낸다.
2. planner output이 생긴 뒤 stale response가 있으면 무시하고 `explain_itinerary`로 보낸다.
3. response packager가 target city에 대한 새 response를 만들면 graph를 종료한다.

현재 종료 판정:

- `modify_intent.city_change.target_city_id == response.response_payload.destination.destinationId`, 또는
- `modify_intent.city_change.target_city_name == response.response_payload.destination.name`

초기에는 live smoke에서 `destination.name = 강릉시`는 들어오지만 `destinationId = null`인 케이스가 있었기 때문에 name fallback을 두었다.

주의:

- `destinationId = null`은 사용자 응답 품질상 별도 개선 대상이다.
- response packager가 planner output의 city id를 destination id로 보강하면 name fallback 의존도를 줄일 수 있다.

---

## 3. 검증

관련 테스트:

```text
tests/v2/test_supervisor_graph.py::test_supervisor_routes_city_change_modify_to_planner_before_stale_response
tests/v2/test_supervisor_graph.py::test_supervisor_routes_city_change_planner_output_to_explain_before_stale_response
tests/v2/test_supervisor_graph.py::test_supervisor_ends_after_city_change_response_payload
tests/v2/test_modify_city_change_reanchor.py
tests/v2/test_planner_direct_anchor.py::test_retrieve_places_node_treats_empty_city_select_as_direct_anchor
tests/v2/test_intent_dispatch_contract.py::test_intent_node_builds_city_change_modify_intent
```

결과:

```text
6 passed
```

최종 live trace:

```text
session: city-change-general-final-20260703132501

create_done:
  response_status: modification_pending
  raw_query: 조용한 바다 산책과 해안 풍경 위주로 2박 3일 일정

modify:
  intent.destination_id: KR-51-150
  trip_intent.destination_id: KR-51-150
  raw_query: 조용한 바다 산책과 해안 풍경 위주로 2박 3일 일정

route:
  intent
  -> supervisor
  -> planner
  -> supervisor
  -> explain_itinerary
  -> supervisor
  -> response_packager
  -> supervisor
  -> end

elapsed: 11.62s
response:
  response_status: modification_pending
  destination.name: 강릉시
```

### 3.1 2026-07-04 재현: 기존 destinationId가 남는 도시 변경 loop

별도 slot replace 검증 중 다음 순서로 다시 재현했다.

```text
session: v2-live-city-then-slot-0704-03

1. create
   input: v2_gen_07_nature_coast_3d2n_live_payload.json
   result: 동해시 / KR-51-170 / 3일 10개

2. modify city-change
   rawModifyQuery: 도시는 강릉으로 바꿔줘.
   request.destinationId: KR-51-170
   intent.city_select_input.destination_id: KR-51-150
```

처음에는 `response_packager` 이후 다음 loop가 발생했다.

```text
response_packager
-> supervisor
-> response_packager
-> supervisor
-> ...
```

원인:

- front modify payload의 `destinationId`는 "수정 전 현재 도시"를 가리킨다.
- city-change intent가 만든 `intent.city_select_input.destination_id`는 "수정 후 목표 도시"를 가리킨다.
- response packager가 request의 기존 `destinationId`를 우선해 응답 destination을 `KR-51-170`으로 만들었다.
- supervisor는 `modify_intent.city_change.target_city_id = KR-51-150`와 응답 destination이 다르다고 보고 현재 modify response로 인정하지 못했다.

수정:

- city-change modify에 한해서 response packager가 `intent.city_select_input.destination_id`를 destination 기준으로 우선 사용한다.
- slot-replace modify는 기존처럼 request/currentOrder의 destination을 우선한다.

검증:

```text
tests:
  tests/v2/test_response_packager_destination.py
  tests/v2/test_supervisor_graph.py
  tests/v2/test_modify_city_change_reanchor.py
  tests/v2/test_planner_apply_edit_multi.py

result:
  30 passed

live:
  create:       16.966s / 동해시 / KR-51-170 / 10 items
  city-change: 30.210s / 강릉시 / KR-51-150 / 10 items
  slot-replace after city-change:
    10.522s / 강릉시 유지
    Day 1 slot 2: 소돌아들바위공원 -> 칠성산
```

### 3.2 복합 raw query: 도시 변경 + 장소 교체

다음처럼 한 문장에 도시 변경과 장소 변경이 함께 들어오는 경우도 확인했다.

```text
rawModifyQuery:
  도시는 강릉으로 바꾸고 1일차 두 번째 장소도 바꿔줘.

payload:
  v2_mod_live_mixed_city_change_slot_replace_gen07.json
```

현재 rule parser 결과:

```json
{
  "status": "ok",
  "kind": "city_change",
  "edit_ops": [],
  "routing_hint": "planner_direct_anchor",
  "city_change": {
    "target_city_id": "KR-51-150",
    "target_city_name": "강릉시"
  }
}
```

live 결과:

```text
session: v2-live-mixed-city-slot-0704-02
create: 22.904s / 동해시 / KR-51-170 / 10 items
mixed modify: 19.180s / 강릉시 / KR-51-150 / 10 items
```

결론:

- 현재 구현은 복합 modify를 복합 수정으로 처리하지 않는다.
- city-change가 우선 적용되고, slot replace는 `edit_ops`로 남지 않는다.
- 따라서 사용자가 "도시도 바꾸고 장소도 바꿔줘"라고 말하면 현재는 "도시 변경 후 재생성"으로만 처리된다.
- 이 동작은 사용자 의도 일부를 조용히 누락하므로 올바른 최종 정책이 아니다.
- intent 단계에서 city-change와 slot replace가 한 요청에 함께 감지되면 `unsupported` 또는 `needs_clarification`으로 막아야 한다.
- 후속 구현 항목: `intent.modify_parser`/LLM modify parser가 mixed modify를 `kind=city_change`로 단순 축약하지 않고, `reason_code=modify_mixed_city_and_slot_unsupported` 같은 명시적 응답으로 올리게 한다.

---

## 4. 장소 교체 설계 메모

장소 교체는 도시 변경과 다르게 도시/일정 전체를 다시 만들지 않는다.

목표 흐름:

```text
rawModifyQuery
-> intent.modify_intent.edit_ops[]
-> supervisor
-> planner edit mode
-> response_packager
```

### 4.1 Intent 책임

Intent는 `rawModifyQuery + backend checkpoint state`를 기준으로 replace intent를 만든다.

필수 출력:

- `intent_type = modification`
- `kind = slot_replace`
- `status = ok | needs_clarification | unsupported`
- `routing_hint = planner_apply_edit`
- `edit_ops[]`

`edit_ops[]`의 핵심 필드:

- `target`
  - 어떤 response item을 바꿀지
  - `item_id`, `content_id`, `day`, `order`, `target_text`, `resolution`
- `condition`
  - 무엇으로 바꿀지
  - `replacement_query`
  - `replacement_query_raw`
  - `theme`
  - `mood`
  - `place_type`
  - `avoid_content_ids`
- `seed_policy`
  - seed item 보호 여부
  - same-theme replace 허용 여부

Intent는 장소 후보 검색을 하지 않는다. target resolution과 replacement 조건 구조화까지만 맡는다.

### 4.2 Supervisor 책임

`modify_intent.status`가 `ok`이고 `routing_hint = planner_apply_edit`이면 planner로 보낸다.

단, city-change에서 발견한 것처럼 stale response가 남아 있을 수 있다. 따라서 slot replace도 다음 원칙이 필요하다.

1. planner edit output이 없으면 `planner`
2. planner edit output이 있고 explain이 없으면 `explain_itinerary`
3. 새 response가 만들어지면 `end`
4. 기존 create response는 stale로 취급

새 response 판정은 city-change처럼 destination으로 구분하기 어렵다. 따라서 slot replace에는 별도 revision marker가 필요하다.

권장 marker:

```json
{
  "response": {
    "source_intent_type": "modification",
    "source_modify_kind": "slot_replace",
    "source_itinerary_revision": "rev-001"
  }
}
```

또는 response payload metadata에 같은 값을 넣는다.

### 4.3 Planner 책임

Planner는 전체 도시를 다시 선택하지 않는다.

Planner edit mode는 현재 itinerary를 base로 두고 target slot만 교체한다.

단일 replace 흐름:

```text
1. current itinerary load
2. target item locate
3. replacement source 결정
4. 후보 pool 생성
5. avoid_content_ids / existing itinerary content ids 제외
6. seed policy 검사
7. candidate score
8. target slot에 candidate 삽입
9. 해당 day route 재계산
10. explain/response 재생성
```

replacement source:

| 조건 | 후보 출처 | 비고 |
|---|---|---|
| `replacement_query` 없음 | 기존 planner reserve pool | "그 장소만 다른 곳으로" 같은 단순 교체. 새 vector search 없이 현재 일정 생성에서 남은 후보를 우선 사용한다. |
| `replacement_query` 있음 | 같은 도시 안 vector retrieval | "조용한 산책지로 바꿔줘" 같은 의도 교체. 해당 query로만 retrieval한다. |

검색/후보 범위:

- 기본은 현재 itinerary city 안에서만 작동한다.
- city-change request가 아니면 city_select를 다시 실행하지 않는다.
- `replacement_query`가 없으면 reserve pool을 먼저 사용한다.
- `replacement_query`가 있으면 reserve pool을 섞지 않고 query 전용 retrieval 결과만 사용한다.
- theme 조건이 함께 오면 retrieval filter 또는 post-filter에 적용한다.
- theme 조건이 없으면 theme filter를 강제하지 않는다.
- reserve pool이 비어 있거나 모든 후보가 제외/route 실패하면 fallback retrieval을 바로 돌리지 말고 notice 또는 clarification으로 올리는 쪽이 안전하다.

후보 제외:

- 교체 대상 content id
- 현재 일정에 이미 들어간 content ids
- user avoid 조건에 걸린 content ids
- seed conflict 정책에 걸린 candidates
- route hard limit을 위반하는 candidates

### 4.4 Scoring 방향

replace scoring은 city_select/planner 생성 scoring보다 좁아야 한다.

우선순위:

1. replacement source priority
2. replacement query similarity
3. required theme match
4. original target subtype 또는 compatible subtype
5. slot/time compatibility
6. same-day route insertion cost
7. seed policy compatibility

`replacement_query`가 있으면 query similarity를 우선한다.

`replacement_query`가 없으면 query similarity를 새로 만들지 않고 reserve pool의 기존 planner score를 우선한다.

```text
no modifyQuery:
  reserve candidates
  -> existing planner score / theme evidence
  -> route insertion cost

with modifyQuery:
  vector retrieval by replacement_query
  -> optional theme filter
  -> query similarity
  -> route insertion cost
```

기존 target item의 theme/subtype/slot/day context는 `replacement_query`가 없을 때 검색 query가 아니라 reserve 후보의 compatibility scoring에만 사용한다.

기존 문맥 기반 fallback retrieval은 V2.0 기본 경로로 두지 않는다. 이유는 사용자가 "그냥 바꿔줘"라고 했을 때 backend가 임의 해석 query를 만들어 새로운 장소를 끌고 오면 수정 의도가 과해질 수 있기 때문이다.

### 4.4.1 Modify Query 분기

`condition.replacement_query_raw` 또는 `condition.replacement_query`가 있으면 query-constrained replace다.

```text
target: 1일차 오후 장소
modifyQuery: 조용한 숲길
theme: 자연·트레킹
```

처리:

1. current city 안에서 `조용한 숲길` query로 retrieval
2. theme 조건이 있으면 `자연·트레킹` 후보만 생존
3. target/existing itinerary content id 제외
4. route hard limit 검사
5. 가장 좋은 후보를 target slot에 삽입

`condition.replacement_query`가 없으면 reserve-based replace다.

```text
target: 1일차 오후 장소
modifyQuery: null
```

처리:

1. 기존 planner reserve pool에서 후보를 읽음
2. target/existing itinerary content id 제외
3. target item의 theme/subtype/slot/day와 호환되는 후보를 우선
4. ORS/haversine route insertion 검사
5. 가장 좋은 후보를 target slot에 삽입

이 경로에서는 raw/soft query retrieval을 새로 돌리지 않는다.

### 4.4.2 다중 수정 정책

다중 replace는 가능하지만, V2.0에서는 "동시에 전역 최적화"가 아니라 **순차 적용**으로 시작한다.

권장 규칙:

1. `edit_ops`를 현재 itinerary order 기준으로 정렬한다.
2. 앞 op의 결과를 다음 op의 base itinerary로 사용한다.
3. 각 op마다 candidate pool을 독립적으로 만든다.
4. 앞 op에서 새로 사용한 content id는 뒤 op의 `avoid_content_ids`에 추가한다.
5. 한 op라도 unresolved/ambiguous/route impossible이면 전체 적용을 중단하고 `needs_clarification` 또는 partial-failure notice를 반환한다.
6. V2.0에서는 partial success를 사용자에게 자동 반영하지 않는다.

다중 replace가 어려운 이유:

- 두 target이 같은 day에 있으면 첫 교체가 두 번째 교체의 route cost를 바꾼다.
- 두 target이 서로 가까운 후보를 경쟁하면 candidate 중복이 생긴다.
- 한 target을 바꿨더니 다른 target의 hard leg limit이 깨질 수 있다.
- seed item이 포함되면 same-theme 정책과 route repair가 동시에 걸린다.

따라서 초기 구현의 안전한 제한:

- 최대 2개 replace까지 허용
- 모두 non-seed일 때만 자동 실행
- 같은 day multiple replace는 순차 적용하되 day route를 매 op 이후 재검증
- 서로 다른 day multiple replace는 각 day별로 독립 적용
- 3개 이상 또는 seed 포함 multiple replace는 clarification/unsupported로 올림

후속 고도화:

- 같은 day의 multiple replace를 batch 후보 조합으로 풀기
- 후보 조합별 route cost를 계산해 전역 최적 조합 선택
- 실패 op만 사용자에게 재질문하고 성공 op를 preview로 보여주는 partial edit flow

### 4.5 Route 적용

replace는 전체 route_days를 처음부터 다시 돌릴 수도 있지만, 초기 구현은 더 좁게 시작하는 것이 안전하다.

권장 V2.0 방식:

1. target day만 재배치한다.
2. target slot에 candidate를 넣고 day route를 다시 계산한다.
3. hard leg limit을 넘으면 다음 candidate를 시도한다.
4. 모든 candidate가 실패하면 `needs_clarification` 또는 notice를 반환한다.

후속 확장:

- target day 실패 시 다른 day로 이동 가능한지 simulation
- reserve candidate로 cross-day repair
- front reorder 결과를 정본으로 받는 경우, front order 기준 route repair

### 4.6 Clarification / Unsupported

replace는 다음 경우에 실행하지 않는다.

- target item unresolved
- target item ambiguous
- seed item을 다른 theme/city로 바꾸려는 경우
- replacement query가 도시 변경 의도를 포함하는 경우
- 후보가 route hard limit을 모두 위반하는 경우

이때는 `response_packager_wait_user`로 사용자에게 다시 묻는다.

---

## 5. 다음 구현 순서

권장 순서:

1. Supervisor에 `planner_apply_edit` 라우팅과 stale/new response marker 추가
2. Planner edit mode input adapter 추가
3. 단일 non-seed replace 구현
4. 같은 day route repair
5. seed same-theme replace
6. multiple replace

city-change troubleshooting에서 얻은 교훈:

- modify 경로는 이전 checkpoint state가 남아 있으므로 stale group을 항상 의식해야 한다.
- Supervisor는 "어떤 output이 현재 modify request에 의해 생성된 것인가"를 판정할 수 있어야 한다.
- 단순히 `response_payload` 존재 여부만 보면 modify loop가 쉽게 생긴다.
