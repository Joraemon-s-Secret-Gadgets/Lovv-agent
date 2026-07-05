# v2_intent_mocks — V2 입력 mock 세트 (생성·수정)

> 목적: V2.0 1차 개발이 **"이런 입력에 이렇게 대응한다"**를 생성·수정 양쪽에서 보여주는 테스트 케이스 후보.
> 근거: `docs/reports/v2/V2_09_INTENT_PARSING_SPEC.md`(계약) · `V2_04_SCENARIO_CONCRETE.md`(SC-*) · `V2_07_ARCHITECTURE_FINAL.md`(thin slice).
> ⚠ 후보 세트 — 실제 테스트 적용/핸드오프 반영 전. `schemas.py` 변경은 아래 §핸드오프 참조(아직 미적용).

## 구성
- `generation/` — 14개. **city_select 입력**(intent 정상 파싱 결과). 초회 일정 생성 경로.
- `modify/` — 4개. **임의 base 일정 state + ModifyResult/edit_ops**. 자연어 수정(resume) 경로.

## 테마 라벨 (canonical · `intent.py THEME_LABELS`)
`바다·해안` · `자연·트레킹` · `역사·전통` · `예술·감성` · `온천·휴양` (미식·노포는 V2 범위 밖). 한글 라벨이 정본 — 영문 코드는 입력 단계 표기.

---

## 생성 계약 (`intent_output`)
V1 `CandidateEvidenceInput` + V2 델타. 필드:

| 필드 | 타입 | 비고 |
|---|---|---|
| country | "KR" | |
| travel_month | 1–12 | |
| travel_year | int | |
| trip_type | daytrip·2d1n·3d2n | 4d3n+ = V2.1 |
| active_required_themes | [한글 라벨] | |
| include_festivals | bool | |
| cleaned_raw_query / soft_preference_query | str | 코드명 유지(스펙의 raw/soft_query와 동일) |
| **congestion_pref** | quiet·vibrant·neutral | **V2 신규**(V1 텍스트 유추 → 명시 승격) |
| **transport_pref** | walk·car·unknown | **V2 신규**(D-E) |
| destination_id | str·null | 소도시 고정(anchored) |
| user_location | {latitude,longitude}·null | 거리 |
| execution_mode | city_discovery·anchored_place_search·festival_seeded_city_discovery | destinationId→anchored / includeFestivals→festival_seeded / else discovery |
| fixed_city_id | str·null | 고정 모드(유지) |
| unsupported_conditions | [str] | userNotice용 |

> 제외: `city_anchor`(V1 HITL 빌더 잔재 → 삭제). `theme_weights`(Profile 입력, 이번 deferred). `query_vector`(임베딩 — retrieval tool mock).

### 생성 케이스
| 파일 | 신호 | SC |
|---|---|---|
| 01 coast_quiet_2d1n | congestion=quiet | SC-00 |
| 02 coast_vibrant_2d1n | congestion=vibrant | SC-00 |
| 03 nature_2d1n | 단일 자연 | SC-00 |
| 04 history_2d1n | 단일 역사 | SC-00 |
| 05 art_2d1n | 단일 예술 | SC-00 |
| 06 healing_2d1n | 단일 온천·휴양 | SC-00 |
| 07 nature_coast_3d2n | 멀티 soft 게이트 | SC-G1 |
| 08 history_nature_2d1n_userloc | 멀티+거리 | SC-G1 |
| 09 anchored_gyeongju_history_daytrip | 소도시 고정 | SC-G2 |
| 10 history_festival_2d1n | 축제 seeded | SC-G3 |
| 11 coast_walk_daytrip | transport=walk | SC-N1 |
| 12 nature_car_2d1n | transport=car | SC-N1 |
| 13 anchored_yeongyang_coast_no_candidate | 내륙+해안 → no_candidate | SC-R3 |
| 14 coast_rainy_month_3d2n | month=7 → weatherNotice | SC-02 |

> **쿼리 보강 원칙**(`tasks/results/test_cases/`와 동일): 기능 케이스는 `cleaned_raw_query`·`soft_preference_query`를 **충분히 구체화**해 soft 신호가 실제 동작하게 한다. 분위기어가 없는 케이스(09·10·12·13)는 `soft_preference_query=""`가 정상(억지로 채우지 않음 — `intent_normalization` 규칙).

### 생성 — short_input/ (의도적 미보강, 희소 입력)
짧은 입력 = `raw`만 짧게, `soft_preference_query=""`. soft re-rank 없이 raw+테마만으로 동작하는 **희소 입력 경로** 검증용(V1의 19·20 케이스 의도와 동일).

| 파일 | 입력 | 비고 |
|---|---|---|
| short_01 short_coast_daytrip | "동해 바다 보고 싶어" | soft 없음 |
| short_02 short_history_2d1n | "경주 역사 유적" | 최소 입력 |
| short_03 short_multi_nature_coast | "산이랑 바다" | 멀티+희소 |

---

## 수정 계약 — **정본: `docs/reports/v2/V2_11_MODIFY_IO_CONTRACT.md`**
`modify_intent`(ModifyResult, 입력) + `expected`(수정 응답 출력 스키마). 신규 계약(V1 코드 없음).

```
modify_intent: {
  kind: "slot_replace" | "reset",
  raw_modify_query: str,
  edit_ops: [ { target: {day, time_slot}, op: "REPLACE",
               condition: {mood?, place_type?, location?} } ],
  reset?: { avoid: ["city"|"theme"] }   // kind=reset
}
```
- **`base_state` = resume된 checkpoint state slice**(초안 생성 시 persist된 상태에서 출발 — 1차 원칙). `original_intent_output`(재인출 컨텍스트) + `selected_city` + `itinerary`(각 day morning=`seed:true`) 포함.
  - ⚠ **배열 출처**: 실제로는 itinerary 배열을 **front가 수정 요청에 동봉**(드래그앤드롭 반영본, 우선) → 미동봉 시 checkpoint fallback(V2_11 §0). mock의 `base_state.itinerary`는 그 "현재 일정"을 대표. **순서·위치 재배열(REORDER)은 front 담당 → modify op에 없음(REPLACE만)**.
- `time_slot` ∈ morning·afternoon·evening. op=REPLACE만(추가/삭제 없음). target이 seed면 거부.
- **출력(확정)**: `response_status=modification_pending` · itinerary=**전체(full)+`modification.changed_slots` 요약** · 부분실패=부분적용+`failed_slots`/`user_notice` · 전체실패=**원본 유지+notice** · weatherNotice/alt=null(1차) · `move`=front(moveMinutes:null).

### 수정 케이스
| 파일 | 내용 | SC |
|---|---|---|
| 01 slot_replace | 단일 슬롯 교체(+조건) | SC-03 |
| 02 multi_slot_replace | 다건 동시(2 ops, 일괄 재배치) | SC-03/§2.2 |
| 03 multi_partial_fail | 다건 중 1개 no_candidate → 부분 적용+안내 | §2.2 |
| 04 full_reset_avoid | 전면 리셋 → 세션 avoid 재생성 | SC-M4 |

---

## 1차 커버리지
생성(품질 C1·C2·C3 / 고정 / 축제 / transport / 거리 / no_candidate / weatherNotice) + 수정(C4 단일·다건·부분실패 / 리셋). **W2(Plan B 실제 생성)·K1(profile write)·M1(되묻기 품질)·도시변경은 V2.1** → 제외.

---

## 구현 핸드오프 (Claude Code, repo 실행)
1. **`schemas.py` 최소 diff** — `CandidateEvidenceInput`:
   - 추가: `congestion_pref: str = "neutral"`(choice: quiet/vibrant/neutral), `transport_pref: str = "unknown"`(choice: walk/car/unknown).
   - 삭제: `city_anchor`. (참조처 `candidate_evidence.py`의 `city_anchor` 패스스루도 제거)
   - `from_mapping`에 두 필드 파싱 추가.
2. **`ModifyResult`/`edit_ops` 신규 스키마** 정의(위 계약). `resolve_w_cong` 텍스트 유추 → `congestion_pref` 직접 사용으로 전환.
3. **테스트**: 위 mock으로 city_select 단위/골든 + 수정 루프 단위. 계측(점수 분해 로깅·seed_id) 선행(`V2_10` §0).
