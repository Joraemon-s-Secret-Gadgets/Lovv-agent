# V2_17 — city_select 작업 진행 기록 (세션 워크로그)

> 목적: 이번 세션 city_select 작업이 **어떤 순서로** 진행됐고 무엇이 산출됐는지 기록. 커밋할 에이전트가 순서·묶음을 파악하기 위함.
> 결과물 정본: 규격=V2_15, 근거=V2_16. 이 문서는 *과정*.
> 작성: 2026-06-29.

---

## 진행 순서 (phase)

### P1. 점수 수식 확정 — coverage − penalty
- semantic_evidence가 coverage와 중복(단일테마 sem=cov, 멀티 반대당김)임을 데이터로 확인 → **sem 항 제거**.
- missing penalty는 winner엔 무력(0/53)이나 완전성 enforce하는 안전장치로 유지.
- 산출: `offline_rescore.py`(오프라인 재채점 하네스), V2_16 §2~3.

### P2. 데이터 도구 구축
- `retrieval_smoke.py` 수정 — ranked에 **lat/lon 추가**(distance용).
- `fetch_city_stats.py` — DynamoDB STAT(방문객) + GOSEONG alias + casing 병합. → `city_stats.json`.
- `anchored_probe.py` — 도시 고정·theme-off 검색(In-city Itinerary 풀). raw+soft 채널.
- `verify_attraction_data.py` — 설명 채움률·정서성 검증(soft HyDE 게이트).
- `name_recall_probe.py` — 이름 recall(+오타/부분명 변형).
- `gen_retrieval_cases.py` — 테마 커버리지 갭 채우는 입력 16건 생성.

### P3. 가중치·파라미터 결정 (실측)
- **top_k=50** (M=2 기준 100과 동일, 30은 깨짐).
- 유사도 압축(median 0.27, knee 없음) → 부차항이 결정자임을 규명.
- **congestion**: logMM(ADR) + w_cong 재스케일(조용+0.08/중립+0.03/혼잡−0.05) + 소도시 lean. (입력 annual→travel-month는 백로그.)
- **distance**: user_location 게이트 + duration 스케일(당일0.08/1박0.04/2박+off).
- 산출: V2_16 §4~6.

### P4. soft 완전 제거 (city_select)
- 3중 근거(quiet 5/9·vibrant 0/6 / HyDE는 place 신호 / 설명 텍스트 사실형) + recall 모순(안정안+score제거면 死코드) → **soft 검색·주입·score 전부 제거, passthrough만**.
- 함평·경주 S3 원본으로 설명 사실형 확인.
- 산출: V2_15 변경 1, V2_16 §7.

### P5. 분포 검증 (53케이스)
- 락한 로직 적용 → 30/53 distinct, 소도시 lean 작동, 약점(예술·구) 식별.
- 점수 요소 분해(coverage=자격/congestion·distance=결정), 순수유사도 대비 21% 변경(전부 큰→작은).
- 산출: V2_16 §11~12.

### P6. 분기·출력·seed·rationale
- 분기: anchored/no_candidate(count)/discovery. 검증(경주✓·영양✓).
- 출력 계약 정제: alternative_city, theme_evidence(place+sim), ddb_pk, passthrough.
- **seed: day-must→seed-must**, 테마별 must-include + 플래그.
- 설명: city_select는 evidence+selection_reason_code만, 프로즈는 다운스트림(V1 실패 교정).
- 산출: V2_15 변경 4·4-a.

### P7. 근거 문서화
- 산출: **V2_16**(결정 근거 14항 + 한계 + 백로그).

### P8. 코드 audit → 갭 발견
- **치명적: query_vector 생성 코드 부재** → 검색 작동 불가. 노드 내부 임베딩 필요(최우선).
- 입력명 `candidate_evidence_input` legacy, `CandidateEvidence*` 잔재 9곳.
- retrieval_node 961줄 비대(festival/모델/헬퍼/prune 중복) → 슬림화.
- 산출: V2_15 정합화 체크리스트 + Legacy 정리 + 슬림화 지시.

### P9. Planner In-city Itinerary로 전환 (진행중)
- 락 로직으로 `selected_cities.json` 생성(52건) → `anchored_probe --selected`로 각 1위 도시 풀 조회(soft 포함).
- 다음: 풀 충분성·얇은도시·seed 가능성 분석.

---

## 권장 커밋 순서 (경로 명시 staging만 — `git add -A` 금지)
> 워킹트리에 무관한 대규모 변경(app/LovvAgentV1 등) 다수 → 아래 경로만 골라 commit.

1. `feat(scripts): add v2 city-select retrieval and scoring probes`
   - `scripts/v2/*.py` (`__pycache__` 제외)
2. `test(retrieval): add v2 retrieval input cases for theme coverage`
   - `docs/tasks/results/v2_retrieval_inputs/`
3. `docs(city-select): add V2_15 handoff, V2_16 rationale, V2_17 worklog`
   - `docs/reports/v2/V2_15_TASK1_CITY_SELECT_HANDOFF.md` · `V2_16_CITY_SELECT_RATIONALE.md` · `V2_17_CITY_SELECT_WORKLOG.md`
4. (선택, 권장 보류) 대용량 산출물 — `v2_retrieval_smoke/` 결과. **`.embed_cache.json`·`__pycache__` 제외**.

**제외 대상:** `app/LovvAgentV1/`·`agentcore/`·README 등 이번 세션 무관 변경 / `__pycache__` / `.embed_cache.json` / 대용량 스모크 결과(재생성 가능).
