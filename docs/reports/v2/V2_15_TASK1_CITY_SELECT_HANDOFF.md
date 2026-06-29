# Task 1 핸드오프 — city_select 구현/정합화 (Claude Code)

> 목표: `lovv_agent_v2`의 **city_select 한 노드를 정책대로 green**으로 만든다. Planner·profile·수정루프·place_score 분리는 **이 작업 범위 밖**(다음 사이클).
> 근거: `lovv_v2_retrieval_planner_soft_policy_summary.md`(정책 정본) + `V2_DECISIONS_LOG` + retrieval 스모크 데이터.
> 원칙: **포팅 baseline 위에서 아래 변경만.** 가중치 수치는 전부 **시작값(튜닝 대상)**, 결정으로 박지 말 것.

---

## 대상 파일 (`src/lovv_agent_v2/agents/city_select/`)
`retrieval_node.py` · `scoring.py` · `selection.py` · `scoring_and_selection_node.py` · `models/schemas.py`

## 정합화 체크리스트 (현재 코드 → V2_15) ⚠ 먼저 읽을 것
> 코드가 이미 V2 방향으로 부분 구현됨(2026-06-29 audit). 아래만 맞추면 정합 완료.

**이미 됨(유지·검증만):** congestion 배선(`_congestion_index_by_city`+`resolve_w_cong`), 도시 키 `.upper()`, `alternative_city` payload, `selection_reason_code`, passthrough, **`CitySelectInput`(입력 개명 완료)**.

**구현 필요(gap):**
- [ ] **⚠ 최우선 — query_vector 임베딩을 노드 내부로**. 현재 `retrieval_node`(line 894/897)는 `state['intent']['query_vector']`를 *이미 계산된 채로* 요구하는데 **이를 생성하는 코드가 코드베이스에 전무** → 항상 빈 벡터 → **검색이 작동 안 함**(이게 없으면 city_select 자체가 안 돎). 해결: 노드 안에서 `BedrockEmbeddingAdapter`(`infra/adapters/embeddings.py`, `embed_query(text)->vec`)를 config로 생성해 **`candidate_input.cleaned_raw_query`를 임베딩** → query_vector. state 의존 제거(V2_09 "임베딩=retrieval_node 책임"). soft_query는 임베딩 안 함.
- [ ] **distance_penalty + duration 스케일**(변경 3-a) — 코드에 `haversine`/`w_dist` **없음**. user_location은 passthrough만 됨 → 실제 점수항 신규 구현.
- [ ] **seeds 테마별 must-include + `is_seed`/`seed_for_theme` 플래그**(변경 4-a) — 현재 단일 seed. 테마별로 + 플래그, day-must→seed-must.
- [ ] **출력 계약**(변경 4-a) — `seeds[]`·`headline_seed`·`theme_evidence`(place+sim, 현재 count)·no-prose.

**검증·정정 필요(코드 대조):**
- [ ] **soft가 score·retrieval에서 진짜 제거**됐는지(변경 1) — `selection.py`에 "soft gates" 잔존. soft 검색·soft_distance·soft_boost 전부 제거, passthrough만.
- [ ] **top_k=50** 값 확인(변경 검색흐름).
- [ ] **w_cong = 조용+0.08/중립+0.03/혼잡−0.05**(변경 3-b) — `resolve_w_cong` 확인. **중립이 0이면 안 됨(+0.03).** 실패 폴백은 0(비활성)이 아니라 중립 index 0.5 처리 점검.
- [ ] **congestion_index = logMM**, 입력 = **travel month total_visitors**(없으면 annual fallback)(변경 3-b).
- [ ] **`candidate_sufficiency` 완전 제거**(`selection.py:336`).
- [ ] **GOSEONG alias**(변경 3-c).

## Legacy 정리 (`CandidateEvidence*` → `CitySelect*`)
입력은 개명됐으나 **출력·중간 타입에 V1 잔재 9곳**. 전부 V2로:
- **`CandidateEvidencePackage` 제거 → `CitySelectionResult`로 일원화:**
  - `scoring_and_selection_node.py:10` import 정리, `:476`·`:511` 실패경로의 `candidate_evidence_package`(fail_pkg) → **`CitySelectionResult`(no_candidate 결과)** 로 교체.
  - `common/telemetry.py:238-239` `state.evidence.candidate_evidence_package.selected_city` → `city_selection_result.selected_city`.
  - `WorkerOutputState.evidence`의 `candidate_evidence_package` 필드 → **`city_selection_result`로 개명**.
  - `schemas.py __all__`(`:23`)에서 `CandidateEvidencePackage` 제거.
- **`CandidateReasonClaim` 완전 삭제**(schemas `:409`,`:492`,`:540-541`,`:587`) — reason_claims는 V2 폐기(설명=다운스트림 프로즈). 대체 = **`selection_reason_code`(이미 있음)**.
- **`infra/config.py:87` `LLM_NODE_CANDIDATE_EVIDENCE`** — city_select는 **LLM 없는 결정론 노드**(임베딩만, reason-claim/프로즈 제거)이므로 이 LLM 노드 키·관련 모델ID config는 **미사용 → 제거**(또는 명시적으로 unused 표기).
> 완료 기준: `grep -rn "CandidateEvidence\|candidate_evidence_package\|CandidateReasonClaim" src/lovv_agent_v2` → **0건**.

## retrieval_node.py 슬림화 (현재 961줄 — 진입 함수는 `retrieval_node` 1개뿐)
노드가 검색 외 잡무를 다 들고 있어 비대. V2 spec상 retrieval_node = **raw×theme 검색 → canon 그룹핑 → available/missing 기록 → 출력**이 전부. 아래를 분리:
- **festival 로직(~57줄, 4함수 `_run_festival_seed_lookup`·`_festival_seed_failure_package`·`_festival_candidate_payloads`·`_festival_seed_audit`) → 별도 모듈**(예: `festival_seed.py`)로 추출, 노드는 호출만. (festival은 vector 아닌 DynamoDB 경로 = 별개 관심사.)
- **`prune_cities` 중복 제거** — `DestinationSearchTool.prune_cities`(메서드, ~161) vs 모듈 `prune_cities`(~270) 중 V2(soft membership, 변경 2) 하나만 남기고 제거.
- **모델·헬퍼 이동** — `AttractionCandidate`·`normalize_attraction_candidate`·검증 헬퍼(`_required_text`/`_numeric` 등)는 `models/` 또는 `common/`으로. 노드 파일엔 검색 로직만.
- **legacy `candidate_evidence_*` 네이밍(24곳) → `city_select_*`/`*context*`** (위 Legacy 정리와 함께).
> 목표: retrieval_node.py는 검색+그룹핑 핵심만 남겨 ~200줄대로. (단, **NUL 꼬리 패딩은 bash 마운트 아티팩트 — 호스트 파일은 정상 컴파일**. 실제 손상 아님.)

## 변경 0 — 입력 계약 개명 + 필드 추가
- **`CandidateEvidenceInput` → `CitySelectInput`** 개명(V2 노드명 정합). `models/schemas.py` 클래스명 + 모든 import/ensure 참조 치환.
- **`theme_weights: Mapping[str,float] | None = None`** 필드 추가 = **effective theme weights**(이번 요청 강조 + profile 장기선호를 Profile agent가 결합한 *최종* 가중치, 명시 테마 floor 유지). **city_select는 이 결합된 벡터를 그대로 소비** → profile이 도시 랭킹에 반영되는 경로. **None이면 균등(1/n).**
  - ※ request↔profile *결합 계산*(Intent→Profile agent)은 별도 task. Task 1은 city_select가 **effective `theme_weights`를 소비**하도록만 배선(profile 계산 미구현 시 균등 fallback). 출처 분리(request vs profile)는 Profile agent 책임, city_select는 결합 결과만 봄.
- **`fixed_city_id` 드롭**(중복): V1에서 `fixed_city_id = destination_id if anchored else None`로 파생일 뿐. `destination_id` + `execution_mode`로 충분 → 필드 제거. **고정 모드(anchored) 동작은 그대로 유지**(destination_id 있으면 anchored). 노드 내부에서 필요 시 `destination_id`로 city 고정.
- 나머지 필드(congestion_pref·transport_pref 포함, city_anchor 제거)는 유지. 출력은 이미 `CitySelectionResult`.
- 참고: 기존 `v2_intent_mocks`엔 `fixed_city_id`가 남아 있으나 무시/정리 대상(드롭된 필드).

## 변경 1 — soft를 city_select에서 **완전 제거** (검색·주입·score 전부) ⚠ 최우선
`scoring.py::score_place` 현재 `soft_boost=0.3×soft_sim` + soft-only `−0.15` → 제거. 나아가 **soft는 city_select에서 아무 역할도 안 함:**
- `soft_boost`·`raw_penalty` **제거(0.0)**. 그리고 `retrieval_node`의 **soft_query 검색·`soft_distance` 주입도 삭제**(죽은 코드).
- 이유: 안정안(soft-only 도시 admission 안 함)이라 soft가 **pool을 넓히지도(recall ❌)**, score에 들어가지도 않음 → 둘 다 아니면 **아무것도 안 하는 코드**. raw-only 채점에선 soft가 새로 넣은 장소도 raw_sim이 낮아 best_sim이 못 되므로 랭킹 영향 0.
- 실측 근거: coverage가 ~0.2로 평평해 soft 0.10이 top-1 14%(5/37) 뒤집음 + quiet 5/9·vibrant 0/6(노이즈/무신호) + HyDE는 정의상 *place* 신호 + 설명 텍스트가 분위기를 거의 안 담음(함평·경주 확인). → **city 레벨 부적합 3중 확인.**
- **soft_query는 city_select에서 쓰지 않고 `passthrough`로 Planner(place 레벨)에만 전달.** (subtype 신호 들어오면 place-type은 그걸로 → soft는 더욱 불필요.)

## 변경 2 — hard AND 게이트 제거 → soft membership
`retrieval_node.py::prune_cities`: "모든 테마 보유 도시만 생존"(AND) **삭제**. 대신:
- 도시별로 후보를 그룹화하되 **테마 일부만 가진 도시도 생존**시킨다.
- 각 도시에 `available_themes` / `missing_themes`를 기록(다운스트림 penalty용).
- region/allowed_city 제약은 그대로 적용.
- 근거: 스모크 — AND가 멀티테마에서 평균 88개(81%) 도시 + 최근접 도시(6/10)까지 제거.

## 변경 3 — city 점수: coverage − penalty (sem 제거, 실데이터 확정 2026-06-29)
`scoring.py::score_city` 최종 형태:
```
city_score = Σ_{covered t}  w[t] · best_sim[t]    # 가중 테마 coverage (evidence+breadth 단일항)
           − Σ_{missing t}  w[t]                   # 명시 테마 누락 감점 (pen_coef = 1.0)
           − distance_penalty                      # user_location 있을 때만 (게이트)
           − congestion_penalty                    # congestion_pref 반영 (중립도 소도시 lean)
           # soft_bonus 제외 — city_score에 안 들어감 (recall/Planner 전용)
```
- **`semantic_evidence` 항 제거.** 실측: 단일 테마에서 sem=coverage 동일(이중계산), 멀티에선 서로 반대로 당김. depth는 `best_sim[t]` 안에 이미 포함 → 정보 손실 없음. 구 정책의 max(seed)/÷budget 분모 논쟁 전부 폐기.
- **이미 제거 확정**: `candidate_sufficiency`·`scale_correction`·`theme_balance`.
- `best_sim[t]` = 그 도시 테마 t의 best 장소 `sim = 1 − distance`. `w[t]` = effective theme_weights(변경 0). **None이면 균등(1/n).** → profile이 이 가중치로 도시 랭킹에 반영.
- **명시 테마 missing penalty 절대 제거 금지** — profile/soft가 아무리 강해도 명시 테마는 floor.
- ⚠ **유사도 스케일**: 실측 best_sim median ~0.26(범위 0.15~0.74), 도시 간 coverage가 평평함. → distance/congestion 계수는 이 **~0.2 스케일에 맞춘 작은 값**(아래)이어야 하며, 0.10 넘기면 무관한 도시가 튀어 dominate.

### 변경 3-a — distance_penalty (게이트 + duration 스케일)
- `distance_penalty = w_dist · min(haversine_km / 300, 1)`, **`user_location` 있을 때만**(없으면 0).
- **w_dist는 trip_duration으로 스케일**(긴 여행일수록 거리 부담↓):
  - 당일 **0.08** / 1박2일 **0.04** / 2박3일+ **~0(off)**. (시작값, 튜닝 대상.)
- 도시 대표 좌표 = 그 도시 후보 place들의 lat/lon 평균(벡터 메타에 lat/lon 있음). **centroid를 DynamoDB에서 가져오지 말 것**(없음).
- 위치를 줬다는 건 "가까운 데로" 의도 → 켜지면 강하게 재정렬(실측 서울 origin w=0.08에서 23/51 재정렬, median 거리 223→104km). 다박은 과하므로 off로.

### 변경 3-b — congestion_penalty (logMM, 소도시 lean)
- `congestion_index` = **log min-max** `(ln v − ln v_min)/(ln v_max − ln v_min)`, pool-relative [0,1]. 통계없음/known<2 → 중립 0.5. (근거: `docs/reports/CONGESTION_INDEX_SCORING_ADR.md`, rank·logFix 기각.)
- `congestion_penalty = congestion_index × w_cong`. **w_cong은 V2 base(~0.2)에 재스케일**(V1 0.35/0.10/0.25는 budget 인플레 base ~2.5 기준 → 그대로 쓰면 dominate):
  - **조용 +0.08 / 중립 +0.03 / 혼잡 −0.05** (시작값, 튜닝 대상).
  - **중립이 0이 아닌 +0.03 = 소도시 추천이 제품 기본 기조.** 실측: 중립 +0.03 → top-1 변경 4/37 전부 더 한적한 도시로(오작동 0).
- `v` = `city_stats.json`의 `annual_visitors`(월별 total_visitors 합).

### 변경 3-c — 도시 키 정규화 (필수)
- 인덱스가 같은 도시를 두 casing으로 쪼개 적재(`CITY#ANDONG` ↔ `CITY#Andong`, place_id 교집합 0). **그룹핑 키 = `ddb_pk.upper()`** 로 통합(미적용 시 도시 evidence 반토막 → 부당 강등).
- 동명 도시 alias: **`CITY#GOSEONG → CITY#GOSEONG-GANGWON`**(강원 고성). 확장 가능한 alias 맵으로.

## 변경 4 — 선택/분기 + representative_seed + 대안 1개
`scoring_and_selection_node.py` — 3개 분기:
- **ANCHORED** (`destination_id` 있음): 그 도시 **고정**, 전국 재랭킹 안 함. 단 고정 도시가 **테마 후보 0개면 no_candidate**(다른 도시로 바꿔치기 금지 — 예: 영양+바다 → "영양엔 바다 명소 없음" clarify).
- **NO_CANDIDATE**: 어떤 도시도 명시 테마 후보가 없을 때. **count(후보 존재) 기반으로 판정, 절대 유사도 floor 아님**(실측 best_sim median 0.26이라 floor 걸면 다 탈락).
- **DISCOVERY**: 그 외 — city_score top-1 선택 **+ 대안(런너업) 1개** 동봉(M=2).

### 변경 4-a — seed must-include + 출력 계약 `CitySelectionResult` 정제 ⚠ 현재 코드 갭
**seed 정책 — day-must → seed-must 전환:**
- seed = **테마별 best 장소(= theme_evidence의 best_place)**. 멀티테마면 **테마당 1개씩**. (단일 테마면 1개.)
- **seed는 Planner의 hard 제약** — Pass2 일정에 **반드시 포함**. 기존 "모든 날 채움"이 아니라 **"전 seed 포함"이 일정 유효성 기준** → 테마 누락 자동 방지.
- 출력 일정 아이템에 **`is_seed: true` + `seed_for_theme`** 플래그(must-include 강제 + 설명 + UI 앵커 구분).

**설명 생성 정책 — V1 실패 교정(프로즈를 city_select가 만들지 않음):**
- V1은 candidate_evidence가 *설명 프로즈*를 생성 → Planner가 무시/재생성 → 낭비·불일치. 원인은 "쓰일 곳이 아닌 데서 미리 만든 것".
- **city_select는 *evidence*(구조화 재료)만 넘기고 프로즈는 안 만든다.** 프로즈는 **Response Packager/Planner 최종 1회**, 실제 일정+evidence로 생성.
- 3층: **audit**(진단 수치, 로깅) / **evidence**(theme별 place+sim, seed, missing, `selection_reason_code`) / **prose**(다운스트림 생성).
- **`selection_reason_code` 필수** — `theme_match / small_city_lean / proximity / anchored / no_alternative` 등. coverage 평평→congestion/distance가 실제 결정자라, *왜 골랐는지*를 코드로 넘겨야 다운스트림이 "여러 도시가 비슷해 그중 한적한 이곳" 처럼 **정직하게** 설명(과장 방지).

**출력 계약 갭(현재 코드: `selected_city/representative_seed/theme_evidence_summary(count)/missing/audit/hints`):**
```
CitySelectionResult {
  selected_city:    { city_id, city_name_ko, ddb_pk(canonical), province, country }
  selection_reason_code: [ theme_match | small_city_lean | proximity | anchored | no_alternative ]   # ★왜 골랐나
  alternative_city: { ddb_pk, city_name_ko, score_delta } | null                                     # ★M=2 폴백
  seeds:            [ { theme, place_id, ddb_sk, title, sim, lat, lon, subtype, must_include:true } ] # ★테마별 must-include
  headline_seed:    place_id                                                                          # 한 줄 설명용(overall max)
  theme_evidence:   [ { theme, best_place:{place_id,title,sim}, coverage_strength } ]                 # ★count→place+sim
  missing_themes:   [theme...]
  passthrough:      { active_themes, theme_weights, trip_duration, congestion_pref,                   # ★명시
                      transport_pref, soft_query, user_location, session_avoid }
  score_breakdown / retrieval_audit                                                                   # 진단(로직 비소비, user-facing ❌)
}
```
- 프로즈 필드 **없음**(evidence만). Pass2가 도시-scoped 재검색하므로 후보 place 전체는 안 넘김 — anchor+seeds+evidence만. soft_query는 안 쓰고 통과.

## 검색 흐름 (retrieval_node)
- 기본: `for theme in active_themes: raw_query × theme ON × top_k=50`.
- **top_k=50 근거(실측)**: M=2(선택+대안1) 기준 k50 vs k100 top-2 차이 1/37(동일 수준), k30은 7/37 깨짐. k=100은 50과 선택 동일(0/37)인데 비용 2배라 불필요.
- **soft_query 검색 없음** — city_select는 raw×theme만. soft는 passthrough로 Planner로만.
- city_pool = 안정안(raw×theme 도시). soft-only 도시 admission(확장안)은 V2.1.

## 설계 근거 — 왜 city_select는 raw만, Planner는 soft까지 쓰나
> 원칙: **soft_query는 *장소 granularity*의 분위기 신호다. 장소 결정이 일어나는 Planner에 속하지, 도시 결정(city_select)이 아니다.**
- **raw_query** = 정제된 *구체 요청*. city 전용이 아니라 **검색 내용 앵커** → city_select(전국 테마검색) + **Planner Pass2(도시-scoped 검색)** **양쪽에서 사용**.
- **theme** = 하드 필터(양 단계). **congestion_pref** = *도시* 레벨 혼잡(방문객·구조화) → 무드 중 **crowd 축을 직접·신뢰성 있게** 처리(그래서 도시 단계에 있음).
- **soft_query** = HyDE 분위기 묘사문 → *장소* 분위기 매칭. **도시 선정엔 부적합(4중 확인)**: ① coverage 평평으로 신뢰불가(quiet 5/9·vibrant 0/6), ② crowd는 congestion 상위호환, ③ HyDE는 정의상 *장소* 매칭(도시는 분위기 불균질 = category 불일치), ④ 설명 텍스트 사실형 → 자연·경관 편향(place 레벨도 약함, 데이터 보강 대기).
- → soft는 **Planner의 도시-내 *장소* 선택/배치**에서 분위기 가산. **요지: raw=구체 앵커(양 레이어), congestion=도시 혼잡(city_select), soft=장소 분위기(Planner only).**

---

## 검증 기준 (pytest, AWS 없이 fixture로)
- **U**: 일부 테마만 가진 도시가 prune 후 **생존**(AND였으면 탈락하던 케이스).
- **U**: `score_place`에 soft 기여 **0**(soft_boost·raw_penalty 둘 다 없음).
- **U**: `candidate_sufficiency`·`scale_correction`·`semantic_evidence` 컴포넌트 **없음**.
- **U**: city_score = `Σ w·best_sim − Σ w(missing)` — 주어진 themes+weights에 대해 기대값.
- **U**: 도시 키 정규화 — `CITY#ANDONG`+`CITY#Andong`가 **한 도시로 병합**, `CITY#GOSEONG`→`-GANGWON` alias.
- **U**: distance/congestion 게이트 — user_location/pref 없으면 해당 항 0; congestion logMM 통계없음→0.5.
- **U**: 분기 — anchored(destination 고정), 고정도시 테마후보0 → no_candidate, discovery는 대안1 동봉.
- **U**: `representative_seed` = 선택 도시 best 장소.
- **G/기준선**: `v2_intent_mocks/generation` 멀티테마 케이스에서 AND였으면 탈락하던 도시(~88개)가 후보 유지; 031(경주 고정)·035(영양 no_candidate) 분기 동작.
- 계측: `score_breakdown`·`retrieval_audit` 컴포넌트별 로깅(V2_10 §0).

## 시작값 (전부 튜닝 대상 — 결정 아님)
| 항목 | 시작값 |
|---|---|
| per_theme top_k | **50** |
| theme_weights(effective) | None → 균등(1/n) |
| pen_coef (missing penalty) | 1.0 (안전장치, 실측상 top-1 선택엔 무영향) |
| w_dist (user_location 있을 때만) | 0.05~0.08, `min(km/300,1)` |
| w_cong (logMM × w) | 조용 +0.08 / 중립 +0.03 / 혼잡 −0.05 |
| soft | city_score에서 제외(0) |

## 범위 밖 (이 작업에서 하지 말 것)
Planner Pass2 · Planner place_score(0.35/0.25/… 분리식) · profile_theme_weights 결합계산 · 수정 루프 · soft-only city admission(확장안) · soft judge.

> 완료 정의: 위 변경 + 검증 green. 그 뒤에야 다음 사이클(Planner Pass2)로 간다.
