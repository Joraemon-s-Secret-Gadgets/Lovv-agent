# V2 수정(Modify) I/O 계약

> 작성일 2026-06-28 · 근거: `V2_09_INTENT_PARSING_SPEC.md §2`(ModifyResult) · `V2_DECISIONS_LOG.md`(배치 편집·응답상태·기피) · `memory_checkpointer_spec`(resume) · 사용자 결정(2026-06-28).
> 목적: 생성 쪽 입력 계약(`CitySelectInput`, 과거 `CandidateEvidenceInput` legacy 제거 대상)은 잡혔으나 **수정 쪽 출력 스키마가 미정**이라, 이를 확정한다.
> 표기: ✅ 확정 · ◐ 1차 단순화(의도적 비효율) · ⚠ 경계.

---

## 0. 원칙 — checkpoint state에서 출발 ✅
초안 생성에도 checkpointer를 걸기 때문에(`memory_checkpointer_spec`), **생성된 일정 + 전체 `UnifiedAgentState`가 `thread_id`로 persist**된다. 수정은 그 상태를 **resume으로 복원해 거기서 출발**한다.

- **modify 처리 입력 = `(현재 itinerary)` + `(재인출 컨텍스트)` + `(ModifyResult)`**.
- **현재 itinerary 배열 출처 = front 동봉 우선, 미동봉 시 checkpoint fallback** ✅
  front가 **드래그앤드롭**으로 순서·위치를 바꿀 수 있으므로, 수정 요청에 front가 **현재 itinerary를 실어 보낸다**(드래그 반영본). 안 보내졌으면 checkpoint의 itinerary를 신뢰. → **배열=front, 내용 생성=에이전트.**
  - ✅ **front 동봉 itinerary에 seed 표시 포함**(합의): front가 생성된 일정에 seed(day anchor)를 별도 표시해 같이 보냄 → 에이전트의 seed 보호(교체 거부)가 front 배열 위에서도 동작.
- **재인출 컨텍스트**(themes·query·place 풀·`selected_city`·seed)는 checkpoint(resumed state)에서 복원 — 수정은 이걸 다시 만들지 않는다.
- ◐ **1차 단순화**: 전체 state 재적재여도 OK(비효율 허용). 최적화(부분 state 로드 등)는 나중. 재인출은 **교체 슬롯 단위만**.

---

## 1. ModifyResult — Intent 수정 파싱 출력 ✅ (V2_09 §2 형식화)
```
ModifyResult: {
  kind: "slot_replace" | "reset",          // 1차 범위
  raw_modify_query: str,
  edit_ops: [
    { target: { day: int, time_slot: "morning"|"afternoon"|"evening" },
      op: "REPLACE",
      condition: { mood?: str, place_type?: str, location?: str } }
  ],
  reset?: { avoid: ["city" | "theme"] }     // kind=reset
}
```
- `op = REPLACE`만 — **추가/삭제(개수 변경)도, 순서·위치 변경(REORDER/MOVE)도 안 함**. 순서·위치 재배열은 **front 드래그앤드롭** 담당(move=front의 연장). 에이전트는 내용 교체만.
- target이 **seed 슬롯이면 거부 + 안내**(seed = 도시 선택 이유, 고정).
- op 간/슬롯 내 **모순 → `needs_clarification`**(절충 생성 안 함, V2_09 §1.4와 동일).
- 백로그 의도(무드/길이/날짜/맥락 전체)는 `userNotice`로 한계 고지(여기 안 들어옴).

---

## 2. 수정 처리 (Planner modify mode) ✅
1. resume → resumed state에서 `itinerary`·`selected_city`·seed·원본 themes/query 읽음.
2. 각 `edit_op`: 비-seed 대상 슬롯 → **슬롯 조건(condition) + 원본 themes 컨텍스트**로 S3 Vector 재인출 → 후보.
3. **일괄 적용 → 단일 재배치**(순차 금지): 모든 성공 op를 한 번에 반영하고 geo·타입 균형·transport_pref로 1회 재배치. **seed 고정 · 배치 개수 ≤3 불변**.
4. **부분 실패**: 성공 op만 반영, 실패(no_candidate) 슬롯은 **원본 유지**.

---

## 3. 수정 응답 출력 스키마 ✅ (확정)
생성 응답 봉투를 재사용 + **`modification` 메타 블록** 추가.

```
{
  "response_status": "modification_pending",       // 수정 완료 + 다음 수정 대기
  "selectedDestination": {...},                    // 불변(리셋 제외)
  "itinerary": { "tripType", "days":[ {day, items:[...]} ] },   // ★ 전체 갱신본(full)
  "modification": {
    "changed_slots": [ {day, time_slot, from_contentId, to_contentId} ],
    "failed_slots":  [ {day, time_slot, reason} ],   // 부분 실패
    "user_notice":   str | null,                     // 실패/안내 문구
    "seed_preserved": true,
    "reset_applied":  false,
    "session_avoid":  { "city":[...], "theme":[...] } // 리셋 시 채움
  },
  "recommendationReasons": [...],                    // 바뀐 슬롯만 갱신
  "weatherNotice": null,
  "alternativeItinerary": null
}
```

### 확정 규칙
- **itinerary 반환 = 전체(full) + `changes` 요약** ✅ — front는 통째 재렌더, `modification.changed_slots`로 강조·안내. (diff 반환 안 함)
- **전체 실패(모든 op no_candidate) = `modification_pending` + 원본 유지** ✅ — 멈추지 않고 기존 일정 유지 + `user_notice`로 안내. (needs_clarification 아님)
- **부분 실패 = 부분 적용 + 안내** — 성공분 반영, `failed_slots` + `user_notice`.
- `move`(이동시간)는 채우지 않음(front 담당, D-C). `moveMinutes: null`.
- **weatherNotice / alternativeItinerary = 1차 modify에서 미발동(null)** — 날씨 동의 → Plan B 실제 생성은 W2(V2.1).

### kind=reset (전면 리셋, SC-M4)
- 기존 도시/테마를 **세션 avoid**로 설정 → city_select 차순위 재생성 → **새 도시의 전체 itinerary** 반환.
- `modification.reset_applied=true`, `session_avoid` 채움. `selectedDestination` 변경됨.
- 세션 한정(TTL까지), 영구 profile 미반영.

---

## 4. 응답상태 매핑 요약
| 수정 결과 | response_status |
|---|---|
| 슬롯 교체 성공(부분 포함) | `modification_pending` |
| 다건 전체 실패 | `modification_pending`(+원본 유지·notice) |
| 리셋 재생성 | `modification_pending` |
| op 모순 / seed 지정 거부 | `END_WAIT_USER`(needs_clarification) |

---

## 5. 1차 범위 밖(V2.1)
도시 변경(change_city 경로) · 날씨 동의→Plan B 실제 생성(W2) · 무드/길이/날짜/맥락 재구성 · diff 반환 최적화 · 부분 state 로드 최적화.

> **에이전트 백로그 아님(= front 담당)**: 순서·위치 재배열(REORDER/MOVE)은 front 드래그앤드롭으로 처리 → 에이전트 modify 범위에서 영구 제외. ADD/DELETE(개수 변경)는 여전히 백로그(추가는 후보 풀 필요).
>
> **단, 나중에 에이전트 op로 끌어와야 하면 저비용**: REORDER/MOVE/SWAP은 **재인출·LLM 0의 순수 결정론 op**(기존 items 순열 재배치). 하루 슬롯 ≤3이라 "최단 동선"조차 brute-force(≤3!=6)로 즉시 최적. **어려운 부분은 intent 파싱 하나**(`op:SWAP/MOVE`, source/target 추출)뿐. REPLACE 같은 무거운 경로 아님. 끌어올 때 정의할 규칙 3개: ① seed-on-move(따라가나/재고정) ② 슬롯 충돌(swap/shift) ③ move 재계산=front(D-C).
