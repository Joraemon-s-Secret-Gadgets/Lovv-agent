# V2_20 — 마스터 인계 (city_select → planner → 수정)

> 다른 에이전트가 콜드로 이어받기 위한 단일 진입점. 상세 정본: **V2_15**(구현규격+정합화) · **V2_16**(결정 근거·데이터) · **V2_17**(워크로그) · **V2_18**(축제) · **V2_19**(현황+다음). 이 문서는 그 위의 요약 + **신규 v2 인덱스 변경** + 작업 순서.
> 작성 2026-06-30.

---

## 0. 한 줄 현황
city_select 설계·축제 설계는 **데이터 실측으로 확정**(단 v1 인덱스 기준). **오늘 인덱스가 kr-tour-domain-v2로 교체됨 → 재검증 필요.** 코드는 부분구현+갭. Planner/수정은 설계 착수 전.

---

## 1. ⚠ 지금 가장 먼저 — v2 인덱스 교체 (오늘 발생)
- 인덱스 `kr-tour-domain-v1` → **`kr-tour-domain-v2`** (bucket lovv-vector-dev, 1024-dim cosine). 덤프: `metadata_audit/kr-tour-domain-v2-all-metadata-20260630T001340Z.json`.
- **변화 4가지:**
  1. **city_id 필터 가능** (nonFilterable = ddb_pk·ddb_sk·raw_s3_uri·embedding_model만). city_id 100%(`KR-39-3` 형식). → anchored를 **city_id로 직접 필터** 가능(list_vectors 우회 제거).
  2. **casing split 해소** — titlecase ddb_pk 0개. `CITY#ANDONG` 단일. → **`.upper()`+GOSEONG alias 정규화 불필요**(V2_15 변경 3-c 무효).
  3. **city(240)+festival(393) 엔티티 인덱스 포함** — festival이 벡터에 `theme_tags`+`visit_months`+city_id 보유 → 축제 벡터 검색 가능(날짜 검증은 여전히 DynamoDB).
  4. 총 7606 레코드(attraction 6973/festival 393/city 240). theme_tags는 attraction·festival 전부 보유(필터 정상).
- **함의: 우리 53케이스 검증·분포·가중치는 전부 v1 기반.** v2에서 유지되는지 **재검증 필수.**
- **지금 할 일(순서):**
  1. 스크립트 v2 전환 — `LOVV_VECTOR_INDEX` 기본값 `kr-tour-domain-v2`, anchored를 city_id 직접 필터로, casing 우회 제거(`scripts/v2/retrieval_smoke.py`·`anchored_probe.py` + 상수).
  2. v2에서 `retrieval_smoke --live --top-k 50` 재실행(53케이스).
  3. v2 결과로 **city_select 결정 재검증**(offline_rescore로 분포·top_k·congestion·distance 유지 확인). 어긋나면 그 항목만 조정.

---

## 2. 핵심 의사결정 (decision log) — 상세는 V2_16

### city_select (확정)
- **수식**: `city_score = Σ_covered w[t]·best_sim[t] − Σ_missing w[t] − distance_penalty − congestion_penalty`. (semantic_evidence 제거 — 단일테마 coverage와 중복, 멀티 반대당김.)
- `best_sim[t]` = 도시 내 테마 t best 장소 `1−cosine_distance`. `w[t]` effective theme_weights(없으면 균등).
- **top_k=50**(M=2 기준 100과 동일, 30은 깨짐). **pen_coef=1.0**(무력한 안전장치 — winner는 항상 전 테마 커버; 하드화=AND게이트 회귀 금지).
- **congestion**: logMM `(ln v−ln vmin)/(ln vmax−ln vmin)`, w_cong **조용+0.08/중립+0.03/혼잡−0.05**. 중립+0.03 = **소도시 추천 기본 기조**. 입력은 **travel-month visitors**(분석은 annual 근사 — 교체 백로그).
- **distance**: `w_dist·min(km/300,1)`, **user_location 있을 때만** + **duration 스케일**(당일0.08/1박2일0.04/2박+~0). 도시 좌표=후보 place lat/lon 평균.
- **soft 완전 제거**(city_select): 검색·주입·score 전부. 근거 3중(quiet 5/9·vibrant 0/6 노이즈 / HyDE=장소 신호 / 설명텍스트 사실형). soft는 **passthrough로 Planner(place)만**.
- **유사도 압축**(median 0.27, knee 없음) → 도시 near-tie → **coverage=자격심사, congestion·distance=실제 결정자**(작아도 tie-break이라 결정적). 순수유사도 대비 congestion만 21% 변경(전부 큰→작은 도시).
- **분기**: anchored(destination 고정·점수우회) / no_candidate(**count 기반**, 유사도 floor 아님) / discovery(top-1 + 대안 1개, M=2).
- **seed: day-must → seed-must.** seed=테마별 best 장소, **Planner must-include**, `is_seed`/`seed_for_theme` 플래그.
- **출력 = evidence만**(프로즈 ❌, 프로즈는 Packager 1회). `selection_reason_code`(theme_match/small_city_lean/proximity/anchored/no_alternative)로 정직 설명.
- **theme_balance 제외** → Planner(풀 깊이). count/밀도도 city_select에서 빠짐(소도시 기조) → Planner In-city Itinerary 관심사.
- **약점(데이터 문제)**: 예술·감성이 대도시 끌어옴(태깅 노이즈) + 도시 구(區) 누수. scoring 아닌 데이터/태깅 이슈.

### 축제 (확정, V2_18)
- `include_festivals` 명시·절대 토글. **월** 매칭(`travel_month ∈ visit_months`).
- **Festival Verifier = city_select 앞단 게이트** → `FestivalGateResult{verified_festival_cities[]}` → city_select `allowed_city_ids`. 축제는 게이트지 랭커 아님(도시 랭킹은 평소 coverage+congestion).
- **date_status(Verifier 파생, raw에 없음)**: event_start_date 연도 vs 목표연도로 파생. **confirmed→F / tentative→되묻기(미확정 감수, silent 포함 금지 — tentative≈outdated 위험) / outdated·unknown·skipped→제외.** confirmed 우선, 없으면 tentative 되묻기, 둘 다 없으면 F=0 되묻기.
- 모든 축제 fallback이 Verifier 단 통일. **되묻기 해소 = 그 도시 anchored 진입**(resume 시 destination_id+include_festivals 갱신).

### Clarification/Fallback (⏳ 미확정 — 중단 지점)
- 코드엔 기본형만(`needs_clarification`/`clarifying_question`/`failure_signals`/`fallback_audit` + `validate_clarification`).
- **필요한 구조화안**(미확정):
```
Clarification { needs_clarification, reason_code(festival_none|festival_tentative|anchor_festival_conflict|no_candidate_city|contradiction|thin_city),
  prompt, options:[{label, apply:{include_festivals?,destination_id?,...}, then: anchor|rerun_discovery|abort}], context, failure_signals }
```
- 핵심 `options[].apply`(resume state patch)+`then`(라우팅)으로 **되묻기→anchored 전환을 스키마 구동.** ← **여기부터 확정 필요.**

---

## 3. 작업 순서 (인계받는 에이전트)

| # | 작업 | 의존 | 산출 |
|---|---|---|---|
| **A** | **v2 인덱스 재검증** | — | 스크립트 v2 전환 → smoke 재실행 → 결정 재검증(§1) |
| **B** | **Clarification 스키마 확정** | — | 위 구조화안 → reason_code·options·apply·then 확정 + 문서화 |
| **C** | **city_select 코드 정합화** | A | V2_15 체크리스트: ①임베딩(최우선) ②정책 ③정리 ④검증 |
| **D** | **Festival Verifier 구현** | B,C | FestivalGateResult + date_status 파생 + tentative→Clarification |
| **E** | **Planner In-city Itinerary 설계** | C | anchored_probe 실행→풀 분석(충분성/얇은도시/seed) → 도시고정 theme-off 재검색·seed-must 배치·duration 채움·theme_balance |
| **F** | **수정 요청(modification)** | B,E | edit_ops/seed보호/부분적용/모순 fallback/modify 출력스키마(V2_11) + 되묻기 resume=anchored + checkpointer interrupt/resume |
| G | (선택) 선호 subtype 추출(intent, theme-scoped, 추출+결정론 매핑) — soft 대체 / 커밋 | | |

### C 상세 (V2_15 정합화 체크리스트 요약)
- **① 임베딩(최우선)**: retrieval_node가 `state['intent']['query_vector']`를 요구하나 **생성 코드 전무 → 검색 死.** 노드 내부에서 `BedrockEmbeddingAdapter.embed_query(cleaned_raw_query)` 호출. 입력명 `candidate_evidence_input`→`CitySelectInput`.
- **② 정책**: distance+duration / seeds 테마별 must-include / 출력계약(seeds·selection_reason_code·no-prose) / soft 제거 검증(selection.py "soft gates") / top_k50 / w_cong·logMM·travel-month / candidate_sufficiency 제거.
- **③ 정리**: legacy `CandidateEvidence*` purge(grep 0건) + retrieval_node 슬림화(festival 추출·prune 중복제거·모델 이동). **v2라 casing 정규화·GOSEONG alias는 단순화/제거 가능.**
- **④ 검증**: AWS mock intent → selection, v2 분포와 대조.

---

## 4. 자산 인벤토리
- **스크립트** `scripts/v2/`: retrieval_smoke(좌표) · offline_rescore(재채점 하네스) · fetch_city_stats(congestion) · anchored_probe(In-city Itinerary 풀, city_id 필터로 보강됨) · verify_attraction_data(설명 검증) · name_recall_probe · gen_retrieval_cases.
- **데이터** `docs/tasks/results/`: v2_retrieval_inputs(53케이스) · v2_intent_mocks · v2_retrieval_smoke/<ts>(v1 결과 + city_stats.json + selected_cities.json) · **metadata_audit/(v2 인덱스 덤프)**.
- **문서** `docs/reports/v2/`: V2_15~20. 코드: `src/lovv_agent_v2/agents/city_select/` + `models/schemas.py`.

## 5. 주의 (gotchas)
- **워킹트리에 무관한 대규모 변경**(app/LovvAgentV1 등) — `git add -A` 금지, 경로 명시 staging만.
- 검증 수치는 **v1 인덱스·annual congestion·53 소표본** 기반 = 방향성. v2 재검증 전엔 절대값 신뢰 금지.
- bash 마운트가 가끔 stale/NUL — 호스트(Read 도구)가 정본. 새 파일은 fresh.
- 중립 congestion 게이트(소도시 default +0.03 유지 vs 명시할 때만) — 제품 결정 미정.
- city_select는 **LLM 없는 결정론 노드**(임베딩만). reason-claim/프로즈 제거됨 → `LLM_NODE_CANDIDATE_EVIDENCE` config 미사용.
