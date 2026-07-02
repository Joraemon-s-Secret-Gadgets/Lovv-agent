# V2_32 — city_select 스코어링 V1 레거시 감사 (제거 대상 식별)

> `src/lovv_agent_v2/agents/city_select/scoring/`(+nodes·tools·domain) 스코어링 로직에서 V1 레거시/죽은 코드를 식별하고 *확실히 제거 가능한지*를 참조 검증으로 판정.
> 방법: 실제 코드 **Read**(마운트 손상 회피) + `src/lovv_agent_v2/`·`tests/`에서 심볼 **참조 grep**. "0 refs"는 *V2 소스+tests/v2* 스코프. 2026-07-01.

---

## 0. 요약
- **즉시 삭제 안전 (0 refs, 순수 삭제)**: 딱 2개 — `_VIBRANT_KEYWORDS`/`_QUIET_KEYWORDS`, `non_negative_int`.
- **이미 제거됨(확인)**: `THEME_MATCH_BONUS`·`soft_bonus`·`CandidateEvidence*`·`sem_relevance` — V2에 **0 refs**. (우리 "sem 제거·theme_match 제거" 결정이 코드에 반영 완료.)
- **제거 가능하나 소규모 리팩터 필요**: **capacity 도시-강등 no-op 클러스터**(`_select_city_rank_index`→0 + 죽은 reason code/audit 3곳) — V1 잔재의 최대 덩어리.
- **판단 필요(INVESTIGATE)**: `deduplicated_candidates`+`to_dict`(write-only), 하드코딩 `5`, `prune_cities` 죽은 게이트.
- **⚠ 진짜 혼란 근원(범위 밖)**: **V1 전체 패키지 2개가 공존** — `src/lovv_agent/`, `app/LovvAgentV1/lovv_agent/`. scoring 폴더 안이 아니라 *repo에 V1 사본이 통째로* 남아 있는 게 "V1 섞임"의 근본.

### 2026-07-02 반영 상태

- 반영 완료: `_VIBRANT_KEYWORDS` / `_QUIET_KEYWORDS`, `non_negative_int`, `_select_city_rank_index`, `itinerary_capacity_fallback`, `selected_city_rank`, `city_reselected_for_itinerary_capacity`.
- 이미 별도 반영되어 있던 항목: `reserve_budget` 기반 selection API 축소. 현재 `candidate_budgets_for_trip()`은 primary budget `int`만 반환한다.
- 유지: `selected_rank_index = 0` 값 자체는 selected city reason(`city_score_rank_1`)과 ranking annotation의 selected flag 계산에 아직 필요하므로 상수값으로 남겼다.
- 최종 판단 필요: `deduplicated_candidates`/`to_dict` 제거, `planner_capacity`의 hardcoded `5`, `prune_cities` theme gate 정책.

---

## 1. 즉시 삭제 안전 (0 refs · 순수 삭제) ✅

### 1-1. `_VIBRANT_KEYWORDS` / `_QUIET_KEYWORDS` — `scoring/ranking.py:41-42`
```python
_VIBRANT_KEYWORDS = ("vibrant","활기","핫플","축제","복잡","인기","사람 많은","핫플레이스")
_QUIET_KEYWORDS   = ("quiet","한적","조용","힐링","고즈넉","평화","평온","아늑","휴식","쉼")
```
- **참조: 정의 2줄뿐(각 1 ref).** V2의 `resolve_w_cong(congestion_pref)`(ranking.py:102)는 *enum pref*를 받아 이 리스트를 안 씀. V1(`src/lovv_agent/.../candidate_evidence.py`)에서만 `resolve_w_cong(trigger_text)` 키워드 매칭에 쓰였던 잔재.
- → **두 줄 삭제.**

### 1-2. `non_negative_int()` — `scoring/selection_normalization.py:141-146`
- **참조: 정의 1줄뿐.** V2 어디서도 호출 안 함(grep 확인). V1엔 `_non_negative_int`(다른 이름·파일)가 reserve_budget 검증에 쓰였는데 V2는 reserve 개념 축소로 미사용.
- → **함수 삭제.**

## 2. 이미 제거됨 — 조치 불필요 (확인차)
`THEME_MATCH_BONUS`(0), `soft_bonus`(0), `CandidateEvidence`(0), `sem_relevance`(0) — **V2 소스에 존재하지 않음.** V1(`src/lovv_agent`, `app/LovvAgentV1`)·docs에만 있음. V2 `score_place`는 `base_sim + source_quality − ref_dist`(service.py:140-143)로 theme_match·sem 항 없음. (혼란 시 V1 파일을 본 것.)

## 3. 제거 가능 — *소규모 리팩터* 필요 (capacity 도시-강등 no-op) 🔶
V1의 "후보 부족 시 2위 도시로 강등" 로직 잔재. **함수는 살아 배선돼 있으나 항상 0 반환** → 하위 분기가 영구 죽음. 순수 삭제가 아니라 인라인+분기 제거라 리팩터.

- **`_select_city_rank_index()` — `payloads.py:45-54`** (`"...V2에선 capacity 강등 제거, 항상 0 반환"`). `agent.py:113`에서 호출→`selected_rank_index`. 파라미터 4개 전부 무시. **tests/v2 참조 0.** → `selected_rank_index = 0`으로 인라인, 함수·파라미터 제거.
- **죽은 분기 — `city_payload.py:29-30`**: `if selected_rank_index > 0: reason_codes.append("itinerary_capacity_fallback")` — rank가 늘 0이라 **절대 실행 안 됨.** `itinerary_capacity_fallback` 문자열 V2 유일 출현처. → 분기 삭제.
- **죽은 값 — `audit.py:47-48`**: `"selected_city_rank": selected_rank_index+1`(늘 1), `"city_reselected_for_itinerary_capacity": selected_rank_index>0`(늘 False). → 필드 정리.
- 주의: `_annotate_city_rankings`·`_itinerary_coverage_audit`·`_status_from_selection`의 **planner capacity 충분성**(`available_place_count >= required`)은 *다른·활성* 메커니즘 → **유지**(V2 planner insufficient 게이트가 사용).

## 4. 판단 필요 (INVESTIGATE) 🟡
- **`deduplicated_candidates` + `CandidateSelectionResult.to_dict()`** — `selection_types.py:44,46-55`. 필드는 `selection.py:119,203`에서 *쓰기만*, 읽는 건 `to_dict()` 하나인데 **`to_dict()` 호출처가 V2 소스·tests/v2에 없음**(라이브는 `.primary`·`.coverage_audit`만 읽음). → write-only. 외부/텔레메트리 소비자 없음 확인되면 필드+to_dict 제거 가능.
- **하드코딩 `5` vs `CANDIDATE_SUFFICIENCY_THRESHOLD`** — `selection_result.py:39` `("sufficient" if len(primary)>=5 ...)`. 상수(service.py:49)의 매직넘버 복제. → 상수 import해 사용(또는 이 `planner_capacity` 필드가 `_status_from_selection`과 중복이라 필드 제거 검토).
- **`prune_cities` 죽은 게이트** — `retrieval/policy.py`(스코어링 아니지만 직결). `eliminated_cities=()` 하드코딩·전 도시 survived → 테마 커버리지 게이트가 **무력**(모든 검색 도시가 스코어링으로 감). `eliminated_cities` 배선이 failures/audit에 늘 빈값으로 흐름. → 게이트 구현 or `eliminated_cities` 플럼빙 제거, 택1.

## 5. 유지 (활성 스코어링 경로) — 건드리지 말 것
라이브: `nodes → scoring/agent.CitySelectScoringAgent → ranking(_score_groups/_rank_cities) → service(score_place/score_city → service_candidates/geo/theme/validation/types) → selection_maps → selection(select_primary_with_theme_quotas) → payloads → city_payload → audit`.
- `CANDIDATE_SUFFICIENCY_THRESHOLD`(service.py:49) = **유지**(primary_budget 기본값·tests/v2·scripts 참조 4 refs).
- `details` 필드(contracts.py:53) = **유지**(스코어링 경로에선 None이나 `infra/dynamo_lookup`이 채우고 `response_packager`가 읽음 → 다른 경로에서 live).
- service_*·ranking·selection*·payloads·city_payload·audit·failures·selection_maps·agent 전부 참조 확인 → **유지.**

## 6. ⚠ 근본 원인 (범위 밖, 그러나 최대 혼란원)
repo에 **완전한 코드베이스 3개 공존:**
1. `src/lovv_agent_v2/` — V2(대상).
2. `src/lovv_agent/` — V1 패키지(루트 `tests/test_scoring.py` 등이 `from lovv_agent.tools.scoring` import).
3. `app/LovvAgentV1/lovv_agent/` — 또 다른 V1 전체 사본.
- "V1 스코어링 섞임"의 실체 상당수가 *이 두 V1 사본*(각 `tools/scoring.py`에 THEME_MATCH_BONUS 등 잔존). V2 스코어링과 물리적으로 분리돼 있어 V2를 죽이진 않지만, **검색/가독성 혼란의 최대 원인.**
- **단, 통째 삭제는 별도 결정** — V1이 아직 배포/참조되는지(agentcore·app 진입점) 확인 후. 이 감사 범위(city_select 스코어링) 밖이라 여기선 *식별만*.

## 7. 권고 실행 순서
1. **지금 삭제(안전)**: §1 두 항목(keyword 리스트, non_negative_int). 회귀 위험 0.
2. **다음(작은 리팩터)**: §3 no-op capacity 클러스터 — `_select_city_rank_index` 인라인 + 죽은 reason/audit 정리. tests/v2 영향 없음.
3. **확인 후**: §4 (to_dict 소비자·prune 게이트 정책·매직넘버).
4. **별도 결정**: §6 V1 패키지 2개 폐기 여부(배포 의존성 확인 선행).

---
### 근거 grep 요약 (V2 스코프)
`THEME_MATCH_BONUS 0 · soft_bonus 0 · CandidateEvidence 0 · sem_relevance 0 · _VIBRANT/_QUIET 각1(정의) · non_negative_int 1(정의) · _select_city_rank_index 3(정의+호출+import) · itinerary_capacity_fallback 1(죽은 분기) · CANDIDATE_SUFFICIENCY_THRESHOLD 4(활성)`
