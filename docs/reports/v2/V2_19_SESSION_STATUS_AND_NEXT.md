# V2_19 — 세션 현황 + 다음 작업 (city_select → planner → 수정)

> 2026-06-29 세션 종료 시점. 내일 이어서 진행. 정본: V2_15(구현)·V2_16(근거)·V2_17(워크로그)·V2_18(축제).

---

## ✅ 이번 세션 완료

### city_select (설계 확정, 53케이스 실측 근거)
- **수식**: `city_score = Σ_covered w[t]·best_sim[t] − Σ_missing w[t] − distance − congestion` (sem 제거).
- **파라미터**: top_k=50 / pen=1.0(안전장치) / congestion logMM·조용+0.08·중립+0.03·혼잡−0.05 / distance 게이트+duration(당일0.08/1박0.04/2박+off).
- **soft 완전 제거**(city_select) — passthrough로 Planner만. raw=양 레이어, soft=place(Planner).
- **분기**: anchored / no_candidate(count) / discovery. **seed: day-must→seed-must**(테마별 must-include + 플래그).
- **출력 계약**: selected/alternative_city/seeds/theme_evidence(place+sim)/selection_reason_code/passthrough. 프로즈 ❌(evidence만, 프로즈는 Packager).
- 분포 검증: 30/53 distinct, 소도시 lean 작동. 약점=예술·구(데이터/태깅 문제).

### 축제 (V2_18, 확정)
- include_festivals=절대 토글. **월** 매칭(visit_months ∋ travel_month).
- **Festival Verifier = city_select 앞단 게이트** → `FestivalGateResult{verified_festival_cities}` → city_select allowed_city_ids.
- date_status(Verifier 파생, raw에 없음): **confirmed→F / tentative→되묻기(미확정 감수) / outdated·unknown·skipped→제외.** (tentative≈outdated 위험이라 silent 포함 안 함.)
- 모든 축제 fallback이 Verifier 단 통일. **되묻기 해소 = 그 도시 anchored 진입.**

### 도구·데이터·문서
- `scripts/v2/`: retrieval_smoke(좌표)·offline_rescore·fetch_city_stats·anchored_probe·verify_attraction_data·name_recall_probe·gen_retrieval_cases.
- `selected_cities.json`(52건, 락 로직 선택) 생성. retrieval input 16건 보강(테마 커버리지).
- 코드 audit: **갭 식별 완료**(임베딩 부재·legacy `CandidateEvidence*`·retrieval_node 961줄 비대·distance/seeds 미구현) → V2_15 체크리스트.

---

## ⏳ 중단 지점 (내일 이어서)
**Clarification/Fallback 구조화 스키마 — 논의만 하고 미확정.** 기본형(`needs_clarification`/`clarifying_question`/`failure_signals`)만 코드에 있음. 우리가 필요한 구조화안:
```
Clarification {
  needs_clarification: true
  reason_code: festival_none | festival_tentative | anchor_festival_conflict
             | no_candidate_city | contradiction | thin_city
  prompt: str
  options: [ { label, apply:{include_festivals?,destination_id?,...}, then: anchor|rerun_discovery|abort } ]
  context: {...}
  failure_signals: [...]
}
```
→ 핵심 `options[].apply`(resume state patch) + `then`(라우팅)으로 **되묻기→anchored 전환을 스키마 구동.** **내일 이걸 V2_19b 또는 V2_18에 확정.**

---

## 📋 내일 작업 (순서)

### A. Clarification 스키마 확정 (중단 지점)
- 위 구조화안 → reason_code·options·apply·then 확정 → 문서화. 기존 기본형 흡수.

### B. city_select 코드 정합화 (Claude Code Task 1 — V2_15 체크리스트)
1. **① 임베딩**(최우선): retrieval_node가 `BedrockEmbeddingAdapter.embed_query(cleaned_raw_query)` 내부 호출(현재 query_vector 외부 요구 → 死). 입력명 `candidate_evidence_input`→`CitySelectInput`.
2. **② 정책**: distance+duration / seeds 테마별 must-include / 출력계약 / soft 제거 검증 / top_k50 / w_cong·logMM·travel-month / candidate_sufficiency·GOSEONG.
3. **③ 정리**: legacy `CandidateEvidence*` purge(grep 0) + retrieval_node 슬림화(festival 추출·prune 중복·모델 이동).
4. **④ 검증**: AWS mock intent → selection, 53케이스 분포 대조.

### C. Festival Verifier 구현
- `FestivalGateResult` wrapper + date_status 파생(event_start_date 연도 vs 목표연도) + tentative→Clarification.
- 그래프: `Supervisor → (include_festivals) Festival Verifier → city_select`.

### D. Planner In-city Itinerary (설계 착수)
1. **anchored_probe 실행**(`--selected selected_cities.json`, soft 포함) → 도시별 풀 분석.
2. 분석: 풀 충분성(duration별 필요량) / 얇은도시(→alternative_city 폴백) / seed 가능성(테마별 seed 존재).
3. In-city Itinerary 설계: 도시 고정 theme-off 재검색 → seed-must 배치(축제 seed 포함) → duration별 일정 구성 → theme_balance(여기서).

### E. 수정 요청(modification) 처리
- edit_ops / seed 보호 / 부분 적용 / 모순 fallback / modify 출력 스키마(V2_11 일부 있음, 갱신 필요).
- **되묻기 resume = anchored 전환**과 연결(Clarification.options.apply).
- memory checkpointer interrupt/resume 배선.

### (선택) F. 선호 subtype 추출(intent, theme-scoped, 추출+결정론 매핑) — soft HyDE 대체. / G. 커밋(V2 문서군+scripts, 경로 명시).

---

## ⚠ 주의 (내일)
- 워킹트리에 **무관한 대규모 변경**(app/LovvAgentV1 등) — `git add -A` 금지, 경로 명시 staging만.
- congestion 입력 **annual→travel-month** 교체 백로그.
- 중립 congestion 게이트(소도시 default +0.03 유지 vs 명시할 때만) — 제품 결정 미정.
- anchored_probe는 city_id 기반 필터로 보강됨(사용자 수정 반영). 실행은 repo+AWS.
