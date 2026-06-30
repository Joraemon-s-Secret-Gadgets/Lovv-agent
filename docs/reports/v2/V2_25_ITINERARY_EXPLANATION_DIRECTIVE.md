# V2_25 — Itinerary Explanation Node 지시서 (planner copy, V1 재사용)

> 확정 일정(In-city Itinerary Build, V2_23 `assemble_itinerary` 산출)에 **사용자-facing 한국어 문안**을 붙이는 노드.
> 방침: **V1 planner_copy 메커니즘을 그대로 재사용**, 입력만 V2 일정 객체에 맞춤. 새 LLM 설계·새 grounding 파이프라인 만들지 말 것.
> 노드명: `explain_itinerary`. 2026-06-30.

---

## 0. 위치 — subgraph 밖 response 노드
- **In-city Itinerary Build subgraph 밖**, 일정이 확정된 *뒤* 1회 실행(V2_23 §7-a). 내부 루프(클러스터링·트림)가 재호출하지 않음.
- 수정(modification) 시 **바뀐 item만 재생성**(§6 로컬 재생성) — V1의 per-`item_ref` 구조가 이걸 그대로 지원.
- **결정론 일정은 절대 안 바꿈** — title/body/reason *문구만* 다듬음. 추천·검색·점수·배치 금지.

## 1. 재사용 자산 — *새로 만들지 말 것*
**V1 (그대로 차용):**
- 프롬프트: `src/lovv_agent/prompts/planner_copy_explanation.v1.md` (필드 지침·톤·금지·검증 규칙 완성형).
- 컴포저: `src/lovv_agent/tools/explanation_composer.py` — `compose_planner_copy_explanation()`, `build_planner_copy_safe_summary()`, `validate_planner_copy_explanation_output()`, `PLANNER_COPY_EXPLANATION_OUTPUT_SCHEMA`, `INTERNAL_EXPLANATION_TERMS`, 결정론 fallback 분기. **구조화 출력 + schema 강제 + retry + 내부용어 차단** 전부 여기 있음.

**V2 (이미 존재 — 재사용):**
- grounding fetch: `src/lovv_agent_v2/infra/dynamo_lookup.py` → **`enrich_final_places(final_places, *, dynamodb) -> DetailEnrichmentResult`**. ddb_pk/ddb_sk로 `get_detail_item` → `details.overview`(수집 시 TourAPI overview를 `description`에 적재 → `_normalize_detail_overview`가 `overview`로 alias). 키 없음/조회실패/항목없음은 **warning + details=null**로 격리(throw 안 함). 전이기 PK shim(`_to_legacy_city_pk`) 포함.

→ 구현 = **두 자산을 V2 일정 객체로 연결**하는 얇은 어댑터. LLM 로직 재작성 ❌.

## 2. 데이터 흐름 (V2)
```
assemble_itinerary → Itinerary(확정, V2_23 §10-B-4)
 → ① enrich: 각 place의 ddb_pk/ddb_sk로 enrich_final_places → details.overview 부착
 → ② safe_summary 구성(V1 build_planner_copy_safe_summary 형식)
 → ③ compose_planner_copy_explanation(구조화 LLM 1콜)
 → ④ item_copies(title/body/reason)를 일정 item에 적용(item_ref로 매칭) + recommendation_reasons + itinerary_flow_reason
 → (LLM 실패 → 결정론 fallback copy, 일정 불변)
```

## 3. 입력 매핑 — V1 safe_summary ← V2 Itinerary (구현 에이전트가 확정)
V1 `_item_prompt_summary`/`_query_summary`가 기대하는 필드를 V2 일정에서 채움:
- `selected_city` ← city_select 결과(city_id, city_name_ko, country, selection_reason_code).
- `query` ← `cleaned_raw_query`, `soft_preference_query`(PlannerInput passthrough, V2_23 §10-B-1).
- `final_itinerary_items[*]` ← 일정 place: `item_ref`(=`item:{index}`, **인덱스 안정**), `item_type`, `placeId`, `title`, `city_id/ko`, `theme_tags`, `source`, **`overview`(①enrich 결과)**, festival이면 `date_status`/dates.
- `candidate_reason_claims` ← **V2 대응 필요**: V1은 별도 claim 목록. V2는 `assemble`의 **place별 `reason_code`+`evidence`**(V2_23 §10-B-4)를 claim 형태(`text_ko`, `evidence_refs`, `required_place_ids`, `public_eligible`)로 변환. *공개 가능(public_eligible=true)만 통과.*
- `verified_festivals` ← 일정 내 festival item(V2_18 FestivalVerification).
- `validation_result` ← 공개 안전 신호만(status, festival placed/skipped, planner_status_gate).

## 4. 출력 — V1 스키마 그대로
```
{ item_copies:[{item_ref, title, body, reason}], recommendation_reasons:[1~3], itinerary_flow_reason }
```
- `item_ref` 입력값 그대로 복사(allowed set 밖이면 reject). `body` ≤50자, overview 근거. `reason` claim 근거. 내부용어(점수/스코어/ranking/top_k/dynamodb/s3 vector…) 차단. 마크다운 특수문자 금지.
- 적용: `_apply_item_copies`로 일정 item의 title/body/reason 갱신(`copy_source="llm_planner_copy"`). 나머지 일정 필드 불변.

## 5. 안전·fallback (V1 정책 유지)
- schema 위반/내부용어/빈 필드 → retry, 한도 초과 → **결정론 fallback copy**(일정·근거 불변, audit에 `schema_failure` note).
- **사실 창작 금지**: overview·claim에 없는 식당·가격·영업시간·평점·날씨 생성 ❌. details=null(enrich 실패)인 place는 **보수적 짧은 body**.

## 6. 모델·런타임 (구현 에이전트 확정)
- V1은 Bedrock Converse 구조화 출력, `reasoning_effort="low"`. **모델 버전은 V2 LLM 노드 설정을 따름**(하드코딩 ❌ — 버전은 검색/설정으로 확인). 임베딩 캐시와 무관.

## 7. 구현 에이전트가 정할 것
1. **claim 변환**: V2 `reason_code`/`evidence` → V1 claim 스키마 매핑(가장 실질 작업). public_eligible 판정 규칙.
2. **노드 배선**: response 노드로 등록, modification 시 변경 item_ref만 재컴포즈(전체 재생성 ❌).
3. **safe_summary 어댑터**: §3 필드 매핑 함수.
4. **모델/런타임 설정** 확인.
> 위 4개 외 LLM 프롬프트·스키마·안전·fallback은 **V1 그대로** — 재설계 금지.

## 8. 검증
- grounding: body가 overview 범위 내, 입력에 없는 사실 0(샘플 수기 점검 + 금지어 자동 차단 테스트).
- 스키마: 잘못된 item_ref/추가 키/빈 필드 → reject·fallback 동작.
- enrich 실패(ddb 키 없음) → details=null → 보수 copy, throw 없음.
- 수정 로컬성: 1개 슬롯 변경 시 그 item_ref copy만 갱신, 타 item 불변.

## 의존성 / 미해결
- **V2 DynamoDB(`TourKoreaDomainDataV2`) detail item에 `description`(=overview) 적재 여부 확인** — V1 코드 주석상 수집 파이프라인이 넣게 돼 있으나, V2 테이블 실데이터로 1건 확인 필요(없으면 전 place details=null → plan-level copy로 강등).
- claim 소스: `assemble_itinerary`가 place별 reason 재료를 실제로 emit하는지(V2_23 §10-B-4 스키마 확정과 연동).
