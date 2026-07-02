# V2_33 — city_select · planner 점수식: 데이터 기반 도달 과정 & 남은 한계

> "왜 지금의 점수 계산식이 되었나"를 *실제 데이터 분석*으로 역추적하고, 그럼에도 남은 한계를 정리.
> 근거: v2 인덱스(kr-tour-domain-v2) 재검증·anchored_probe·ORS 라이브·profile 오프라인 그리드·실제 `score_city`/`build_in_city_itinerary` 재실행. 표기: [확인]=실측 / [추론]=간접. 2026-07-01.

---

## A. city_select 도시 점수식
현재: `city_score = capped_theme_coverage − distance_penalty − congestion_penalty`
`coverage = Σ w[t]·best_sim[t]`, `penalty = Σ w[t](missing)`, `best_sim[t] = max(1−cos_dist) over theme t`.

### A-1. sem(의미유사도 단독항) 제거
- **데이터**: v2 인덱스에서 도시 간 유사도가 **평평**(재검증 similarity median ≈0.274, 도시별 격차 작음)[확인]. sem을 따로 더하면 coverage와 중복 신호가 되어 변별력을 안 줌.
- **결론**: sem 단독항 삭제, coverage−penalty만. (코드 확인: `score_place = base_sim + source_quality − ref_dist`, sem 항 없음.)
- **한계**: coverage가 best_sim(봉우리)에만 의존 → A-3 문제로 이어짐.

### A-2. coverage − missing_penalty (가중 테마 커버리지)
- **데이터**: 재검증에서 penalty 발동 0/53[확인] — 대부분 케이스가 요청 테마를 최소 1개는 커버해 penalty가 실질 비활성. 즉 **coverage가 사실상 순위를 지배**.
- **결론**: 구조는 유지하되, 순위는 coverage(=best_sim 합)가 결정.
- **한계**: penalty가 거의 안 걸리니 "테마 하나라도 있으면 통과" → 얕은 커버(테마당 1곳)도 높은 coverage를 받음(A-3).

### A-3. best_sim = 테마별 *최고 한 곳* (봉우리) — **핵심 한계 지점**
- **데이터**: 실제 `score_city` 재검증(53케이스) + planner 재검증에서 드러남. 강진(coast) 케이스: 바다·해안 **1곳**뿐인데 그 1곳의 sim이 높아 city_score 1위[확인]. 서산(coast): 39개 풀 중 바다·해안 5개, best×0.6 통과 1개[확인].
- **결론(현재)**: best_sim은 "그 테마를 *얼마나 잘* 대표하나"를 재되, **깊이(개수)는 안 봄.** 이게 의도된 소도시 발굴(틈새 매칭)의 대가.
- **한계**: **1곳짜리 도시가 5곳짜리 도시를 이김** → planner 단계서 채울 게 없어 붕괴(§B-1, 27%). depth 미반영이 city_select 최대 미해결(→ V2_26 depth 보정 제안, *미구현*).

### A-4. profile theme-weight (±cap, 하드게이트)
- **데이터**: 20 페르소나 × config 오프라인 그리드[확인]. 게이트 없으면 2건 프로필(P03/P04)이 대조군을 깨뜨림 → **하드게이트(3건 미만 off)** 추가 시 대조군 0. medium range[0.8,1.3]에서 ~10/20 변경, 전부 선호 테마 방향. 1·2건 콜드스타트는 changed 0(P05=3건부터 변화)[확인].
- **결론**: alpha1.5·range[0.8,1.3]·cap0.05·활성3건. profile은 도시점수 ±0.05로 제한.
- **한계**: 평평한 coverage 위에서 cap(0.05)이 거의 non-binding → profile 실효가 작음. art→대도시 누수를 물려받음(데이터/태깅 이슈).

### A-5. distance_penalty (user_location 게이트, 기간 스케일)
- **데이터**: 재검증서 user_location 있는 케이스에서 선택 flip 발생(예: 030 history_nature_userloc 변경)[확인]. daytrip0.08 / 2d1n0.04 / 장기0 / None0.05.
- **결론**: 집에서 먼 여행 억제, 짧은 여행일수록 강하게.
- **한계**: `min(km/300,1)` 선형·도시 *평균좌표* 기준 — 도시 내 분산 무시. 300km는 임의 기준[추론].

### A-6. congestion_penalty (w_cong, 로그정규화)
- **데이터**: 실제 `score_city`로 방문객 stats 넣어 재검증 → **11/53 선택 변경**, 동인이 distance+congestion[확인]. 중립(0.03)에서도 소도시 lean → art 종로구→인제/완주 교정. quiet(0.08)는 024 동해→강진 등[확인].
- **결론**: 조용+0.08 / 중립+0.03(소도시 lean) / 혼잡−0.05. 생존도시 방문객 logMM 정규화.
- **한계**: 광역 구는 STAT 없어 0.5 기본(무차별)[확인]. stats가 구버전(121521)·연도 불일치(2026 요청 vs 2025 stat)로 재검증은 *월만* 매칭[확인]. congestion은 여행월 방문객이어야 하나 검증은 근사.

### A-7. capacity 도시-강등 제거 (`_select_city_rank_index`≡0)
- **데이터/판단**: V1은 후보부족 시 2위 도시로 강등(수량 편향). "V1처럼 되지 말자" 결정에 따라 V2는 **항상 1위 선택**[확인, 코드].
- **결론**: 매칭 1위를 그대로. thin은 planner 폴백이 처리.
- **한계**: A-3와 결합 → **얕은 도시가 1위로 뽑혀 planner에서 27% 붕괴 후 alternative_city로 도시 교체**(사실상 뒤늦은 강등). V2_26에서 "capacity=scope 조정"으로 바꾸자 제안했으나 *미구현*.

---

## B. planner (In-city) 점수·선택식
현재: anchored 풀 → best×0.6 relevance → soft theme-gated(0.7/0.3 블렌드) → 테마 quota → subtype cap → driving 클러스터.

### B-1. relevance 컷의 변천 — 절대컷(폐기) → best×0.6(폐기) → **raw 테마게이트만**
- **1차 데이터**: 절대 컷(sim≥0.20) → **중앙 2곳·빈 풀 2개·33/51이 4곳 미만**[확인]. 풀 안 유사도 가파름(best 0.28→꼬리 0.06). → best×0.6 상대컷으로 전환(median 9곳·빈셋 0)[확인].
- **2차 데이터(반전)**: 실제 `build_in_city_itinerary` 재검증서 **best×0.6도 가파른 풀에서 꼬리 붕괴** — 제주 100개·테마보유 82개인데 통과 **2개**, **14/51(27%) insufficient**[확인]. → **raw best×0.6를 제거**(over-pruning).
- **결론(현재 코드)**: raw는 **활성 테마 게이트만**(유사도 임계 없음) — audit `relevance_ratio: None` / `raw_relevance_policy: "disabled_use_active_theme_gate"`[확인, 코드]. 요청 테마 보유(or seed)면 통과. **soft 채널은 여전히 `best_soft×0.6` 유지**(SOFT_RELEVANCE_RATIO=0.6).
- **효과**: 원인 B(가파른 풀 꼬리붕괴) 해소 — 테마 보유 장소가 임계로 안 잘림. 이후 target_count·테마 quota·subtype cap이 트리머 역할.
- **남은 한계**: (a) 원인 A(테마-빈약 앵커, 서산 해안 5개)는 *희소성*이라 컷 제거로 안 풀림 → city_select depth 문제로 귀결. (b) 유사도 컷이 없어져 **저유사도 테마-보유 장소도 유입** 가능 → 품질 희석 위험, quota/cap/target이 유일 방어 → 모니터링 필요[추론].

### B-2. soft theme-gated 포함 + 0.7/0.3 블렌드
- **데이터**: anchored 51케이스 monkeypatch 그리드[확인]. overlap(raw∩soft) median 2·13/51은 0. soft_w 0.3→17케이스 변경·평균 0.39곳, **0.5 이후 평탄**. 블렌드가 overlap 장소를 안 버리고(candidate loss 해결) 순위만 보정.
- **결론**: raw 0.7 + soft 0.3(부드러운 보정), soft-only는 요청 테마 일치 시만 포함.
- **한계**: overlap이 애초에 적어(median 2) 블렌드는 *소폭 tie-break*[확인]. soft의 place-레벨 실효가 제한적.

### B-3. medoid 용량제약 클러스터링 (farthest 아님)
- **데이터**: 단양·속초·동해 driving matrix로 검증[확인]. 순수 k-medoids는 13+1·12+1+1 **싱글톤 outlier 날** 생성(단양 소백산천문대 1곳짜리 날). 용량제약 넣으면 속초7+7·동해7+7·단양5/5/4 균형, medoid는 항상 중심(평균<군집 최악점).
- **결론**: 용량제약 k-medoids, seed=anchor, 빈 날=medoid(대표), outlier는 흡수.
- **한계**: seed 여러 개면 배치 복잡(테마수≠날수). 단양류 spread 도시는 하루 이동합 큼(150분)[확인].

### B-4. driving 기준 이동시간 모델 (walk=보조)
- **데이터**: ORS 라이브(단양·속초·동해 42곳)[확인]. **snap >1km 0/42**(최대 805m=단양 구담봉 driving, 같은 점 foot 6.5m). 도보 median 속초33·동해121·단양263분 → **walk 성립은 compact 도시 한정**. driving 클러스터 실도로에서 유지.
- **결론**: driving을 모두의 feasibility proxy(대중교통≈driving×1.3~1.5 근사), foot=compact walkable 신호, snap=null만 제외.
- **한계**: **실제 대중교통 라우팅 없음**(GTFS 미보유) — transit는 근사[추론]. snap 게이트는 실측서 한 번도 안 물림(null 1건=청초호 호수)[확인] → "제외"보다 좌표보정이 실제 역할.

### B-5. subtype 다양성 / depth=day_count (단조·붕괴 대응)
- **데이터**: 라이브 생성서 "해변만 8곳" 단조[확인] — 코스트 변주(촛대바위·일출)가 *자연 태그*라 바다·해안 게이트가 다 떨굼. healing 5케이스 전부 붕괴(온천·휴양 태그 극희소)[확인].
- **결론(제안)**: 단일테마 subtype cap + facet 확장(R3) + 테마 depth=day_count(1/day). **대부분 미구현**(subtype cap 50% 단일테마만 존재).
- **한계**: 근본은 **데이터 태깅**(경험 변주가 다른 테마 태그에 있음) — 코드 게이트로 완전 해결 불가, 멀티태깅 필요[추론].

---

## B*. soft query는 왜 planner 전용인가 (city_select 미사용)
- **데이터/근거**: `soft_channel.py` 오프라인 분석 — city 레벨에서 soft는 raw와 overlap 적고 도시 순위를 유의하게 안 바꿈 → "기껏해야 0.05~0.10 약한 tie-break, 강한 요인 아님"[확인]. 그래서 city_select에서 **완전 제외**(그 tie-break가 사실상 noise). 코드 확인: city_select retrieval은 `cleaned_raw_query`만 임베딩, scoring은 거리만 — **soft 참조 0**[확인].
- **mood의 이원화**: city 레벨의 *행동 가능한* mood 축(조용↔활기)은 **구조화된 `congestion_pref`**(quiet→w_cong 0.08 등)가 담당(A-6). 자유텍스트 분위기 임베딩(soft)은 도시를 변별하기엔 너무 분산.
- **soft가 실효인 곳 = place 레벨(planner)**: 고른 도시 안에서 분위기 정합 장소를 살림(anchored: 조용→저수지·철새도래지, 활기→벚꽃길)[확인]. + 0.7/0.3 블렌드로 overlap 보정(B-2).
- **결론**: mood = 구조화 pref(quiet/vibrant)→**city_select**, 자유텍스트 분위기 임베딩→**planner place**. soft는 planner 전용.
- **한계**: (a) soft_channel 분석이 준 *약한(0.05~0.10) city-레벨 tie-break*를 아예 버렸음 — 근소한 개선 여지 포기[추론]. (b) 따라서 city 레벨 mood 정확도는 **전적으로 congestion_pref 품질에 의존** → "조용한 바닷가→동해(붐빔)" 같은 실패는 soft가 아니라 congestion 데이터(A-6 한계)에서 옴. (c) intent가 mood를 congestion_pref로 얼마나 잘 뽑느냐가 병목(현재 intent 파서 스텁).

## C. 남은 한계 (통합 — 우선순위)
1. **best_sim 봉우리 = 깊이 맹목** (A-3 ↔ B-1): 1곳짜리 도시가 이기고 planner에서 27% 붕괴 → alternative_city 뒤늦은 도시교체. *city_select 깊이 신호(depth) + best×0.6 꼬리 완화* 둘 다 미구현. **최대 미해결.**
2. **데이터 태깅 한계**: 해안 변주·healing이 태그에 제대로 안 실려 테마 게이트가 붕괴/단조 유발. 스코어링으론 못 고침(멀티태깅 데이터 과제).
3. **congestion 데이터 품질**: 광역 구 STAT 결여(0.5 무차별), stats 연도·최신성 불일치. 여행월 방문객 입력 필요.
4. **검증 자체의 근사성(정직)**: (a) 오프라인 하네스는 seed를 휴리스틱으로 생성·trip_type 추론 — 실제 city_select seed와 미세차. (b) congestion 재검증은 구 stats·월만 매칭. (c) planner가 리팩터 중 broken이라 블렌드/일부는 *충실 재구현*으로 측정(실모듈 실행 아님). (d) 전 구간 **live e2e가 아니라 노드 단위 재실행**. → 결론의 *방향*은 견고하나 절대 수치는 근사.
5. **sparse 테마(healing)**: 데이터에 후보가 적어 구조와 무관하게 붕괴.
6. **구현 갭(식과 별개)**: confidence 하드코딩(0.76/0.35), 장소수 3중 불일치(5/6/8), deterministic reason "관련도" 누수 — 점수식 결론엔 영향 없으나 산출 품질에 영향.

## D. 한 줄 결론
현재 점수식은 **"틈새 소도시를 vibe로 매칭"(sem 제거·coverage·소도시 lean congestion)** 이라는 방향은 데이터로 뒷받침됨[확인]. 그러나 **coverage가 봉우리(깊이 맹목)** 라서 *채울 수 없는 얕은 도시를 뽑는* 구조적 한계가 남고, 이는 city_select depth 보정 + planner best×0.6 꼬리 완화 + 데이터 멀티태깅으로만 풀린다(현재 미구현).
