# V2_23 — In-city Itinerary Build 설계 (도시 내 일정 구성)

> city_select가 도시를 고른 뒤, 그 도시 안에서 일정을 짜는 단계 (구 "In-city Itinerary" — 명칭 폐기).
> 노드: **`retrieve_places` → `route_days` → `assemble_itinerary`**. 흐름: anchored 풀 → place relevance 필터 → 동선 배치.
> 데이터 근거: anchored_probe(v2, 51케이스). ORS: `5th_final_project/ORS_api_code_with_snap_20260630`. 2026-06-30.

---

## 0. 전체 흐름
```
선택 도시(city_id 고정)
 → anchored 검색: raw + soft 채널, theme-OFF, 도시-scoped (city_id 필터, v2)
 → ① place relevance 필터: best×0.6 상대 컷 + seed 보존
 → ② 분위기 재정렬: soft 채널로 kept set 재정렬
 → ③ 테마 균형 quota(항상 켜짐): 요청 기반 균등 baseline + (있으면) profile 틸트, seed floor·availability cap
 → ④ 도달성: ORS snap(좌표 보정) — null만 제외, 거리는 audit
 → ⑤ 동선: ORS matrix(driving 기준 이동시간) → 용량제약 k-medoids(seed=anchor·빈날=medoid) → 일자 배분
 → (풀 부족/얇은 도시 → alternative_city 폴백)
```

## 1. 핵심 발견 (데이터)
- anchored 풀은 **가변 크기**(min 3, median 37, max 100; 42/51이 top_k 미만). **고정 N 컷 불가.**
- 풀 *안* 유사도는 **가파름**(best 0.28 → 꼬리 0.06, 격차 0.22) — city_select의 평평함과 정반대. **relevance 컷이 작동.**
- soft 채널은 raw와 **top-10 overlap 0.25**(34/42가 절반 이상 다름) + soft-only 장소가 **분위기 정합**(조용→저수지·철새도래지, 활기→벚꽃길). **place 레벨에선 soft가 실효.**

## 2. ① place relevance 필터 = 상대 threshold (확정)
- **`sim ≥ best_sim × 0.6`** (도시별 best 대비 상대). 절대 컷(0.20)은 중앙 2곳·빈 풀 2개라 실패; 상대는 **빈 풀 0**(best 항상 보존), 중앙 9곳.
- **ratio를 duration으로 스케일**: 당일 ×0.7(~5) / 1박2일 ×0.6(~9) / 2박3일 ×0.5(~17). **기본 ×0.6.**
- **seed 보존**: 요청 테마별 best 장소(must-include)는 컷 밑이어도 유지(전수 51/51 풀에 존재 확인).

## 3. ② soft = theme-gated 포함 + 재정렬
- **작업셋 = `raw-kept(best_raw×0.6)` ∪ `soft-add(best_soft×0.6 ∩ 요청 테마)`.**
- 즉 **soft-only 장소도 포함**하되 **요청 theme_tag 일치한 것만**(분위기+테마 둘 다 맞는 장소). raw가 놓친 분위기 장소를 살림.
- **off-theme soft 장소는 제외** — 조용한 "바닷가"인데 저수지(자연)로 새는 것 방지. raw/seed가 테마 정함, soft는 그 테마 *안에서* 분위기.
- 데이터(v2 anchored, soft 42케이스): soft-only 평균 9.5곳 → **on-theme 4.0곳 포함**, off-theme 5.5곳 제외. 포함 예: 활기→선착장/벚꽃길, 고즈넉→고분군/향교.
- 포함 후 soft 유사도로 **재정렬**(분위기 맞는 장소 상위).

## 4. ③ 테마 균형 quota — **항상 켜짐**, profile은 선택적 틸트
- **balance가 주체, profile은 틸트.** quota는 *무조건 실행*되며 baseline = **요청 테마 가중치**(중립이면 균등 1/n). profile(중간 config, V2_22)은 그 baseline을 *기울일 뿐* 균형의 주체가 아님.
- **왜 항상 켜야 하나**: seed floor는 "있음"(테마별 ≥1)만 보장하지 **비율**은 보장 안 함. quota를 profile 조건부로 두면, profile 없는 콜드스타트(대다수 유저)에서 relevance가 한 테마를 독식함. 예) "바다+역사" → 검색 theme-OFF라 바다 8 + 역사 seed 1로 쏠림. **균형은 *요청*이 만든다 — profile 유무와 무관.**
- 배분: 멀티테마 요청에서 테마별 장소 수 = 균등(중립) 또는 요청/profile 가중. 예 바다+역사 12곳 → 중립 6/6, 역사-lover면 4/8.
- **경계**: seed-must = floor(테마 0 불가) · 단일테마면 정규화상 불변 · **availability cap**(희소 테마는 도시에 있는 만큼만) · profile cap으로 독식 방지.
- 각 quota 채우기 = relevance(best×0.6 통과) → soft → subtype 다양성.

## 5. ④ 도달성 = ORS snap — **null만 제외** (거리는 audit)
- 벡터 메타 lat/lon은 *POI 중심점* → 도로/보행망에서 떨어질 수 있음(산봉우리·전망대·호수). snap으로 **matrix용 routable 좌표**를 얻는 게 목적(제외용 아님). trekking 태그 POI는 **foot 계열로 snap**(봉우리는 차도엔 멀어도 등산로엔 붙음).
- **제외 = null/unroutable(모든 profile snap 실패)일 때만** → haversine fallback. `snapped_distance` 값은 **제외가 아니라 audit/penalty**로만.
- 근거(라이브, 단양·속초·동해 42곳, radius 1km): **>1km 0건**(최대 805m=단양 구담봉 driving / *같은 점 foot 6.5m* — profile 의존성 실증). 실패 모드는 거리 아닌 **null 1건**(청초호=호수 중심점). → 기존 ">1km 제외" 게이트 폐기, **null-only**로.

## 6. ⑤ 이동시간 모델 = **driving 기준선 + 용량제약 클러스터링**
- **기본 이동시간 = driving(ORS matrix duration)** — 차·대중교통 모두 도로 기반이라 driving이 *모두의* feasibility proxy. 대중교통은 driving×~1.3~1.5 근사(ORS에 transit profile 없음 → 추후 GTFS 과제).
- **foot = compact 도시에서만 결정적인 walkable-leg 신호**, feasibility 게이트 아님. 근거: 도보 median **속초33 / 동해121 / 단양263분** → 도보 동선은 compact(속초류)에서만 성립.
- **기준은 시간(duration), 거리 아님** — 같은 거리가 모드·지형 따라 feasibility 다름(속초 같은 쌍 도보33 vs 차5.8분). 거리는 fallback 환산·audit만. *(도시레벨 distance_penalty는 별개: user_location→도시 km.)*
- **장소 수는 기간 고정**(당일~4/1박~8/2박~12), 체류 미고려. 작업셋(>스케줄 수)의 잉여는 reserve.
- **동선 = driving-time 용량제약 k-medoids**:
  - 작업셋을 **D일**(당일1/1박2/2박3)로 군집, 각 군집 slot≤S · 내부 max-leg≤상한.
  - **seed = 강제 anchor**(테마별 must-include). **K=D** 1:1 / **K<D** 빈 날은 **군집 medoid**(밀집중심)가 대표 — *outlier(가장 먼 점)를 대표로 쓰지 않음* / **K>D** seed가 가까운 날에 흡수(weight 높은 seed가 헤드라인, **버림 없음**).
  - **날 배정 = 각 후보를 *가장 가까운 anchor의 날*에**(candidate↔anchor **driving-time**). 거리 기준점: seed-day는 seed, 빈 날은 medoid. ← 사용자 모델 "seed별 후보군 분리 + 거리 계산"이 여기 구현됨. *단, 순수 최근접만으론 불균형 → 아래 용량제약 필수.*
  - **순수 k-medoids 금지** — outlier를 싱글톤 날로 격상시킴(검증서 확인). **용량제약 필수.**
  - **max-leg/하루상한 초과 날 → 가장 먼 *비-seed* 멤버 트림** 또는 "날 추가" 고지.
  - **날 *내부* 순서 = 직전 장소부터 최근접**(backtrack 최소). 일출/낙조·야경 키워드면 **시각대 보정**(일출→아침, 낙조·야경→저녁), seed=그 날 하이라이트. **sim으로 재정렬 ❌**(내용은 *선택*에서 이미 반영, 순서엔 잘못된 신호). 하루 ~4곳이라 저-stakes — 시각대만 가볍게.
- **max-leg drive ≤60분 / 하루상한 drive ~150분.** (foot 동선은 compact 도시 한정 walk30 / day90.)
- **점수 = 총 이동시간**(낮을수록 좋은 동선). ORS 실패/키 없음 → **haversine fallback**(거리→모드속도로 시간 환산).

## 7. transport_pref & 얇은 도시
- **transport_pref=walk = 선호+안내**, feasibility 게이트 아님. compact 도시(속초류 medpw<~3km, 도보 leg<30분)면 도보 동선, 흩어진 도시(동해·단양)면 driving 동선 + **"도보만으론 어려워 대중교통/차 권장" 고지**. (기존 "한 클러스터만" 폐기 — 도보객도 대중교통 이용.)
- 컷 후 기간 장소 수 미달(healing/동두천 등 <4곳) → **alternative_city 폴백**(city_select M=2 대안).

## 7-a. Planner = **subgraph** (루프 때문)
city_select(2노드 subgraph)와 평행하게 Planner도 subgraph. **이유는 단계 수가 아니라 *내부 루프/체크포인트*:**
- **수정 루프(modification) — *로컬·안정* 필수.** edit_ops로 재계획하되: **(1) state에 pool+working set+matrix 캐시 재사용**(재임베딩/재검색 금지), **(2) 편집은 해당 (day,slot)만 교체 + 미변경 날 freeze**(전체 재배치 ❌), **(3) 풀에 만족 후보 없을 때만 `retrieve_places` 재호출**. interrupt/resume 재진입은 `route_days`/`assemble_itinerary`부터.
- **얇은-도시 폴백** — alternative_city로 재anchor·재실행(조건부 루프).
- **clarification(되묻기)** — walk 충돌·축제 충돌 → interrupt.
- **ORS 외부호출 격리** — S3 Vectors와 다른 실패 모드(strict/fallback 분기).
- **노드(라우팅·외부·체크포인트만):** `retrieve_places`(anchored S3) · `route_days`(ORS snap+matrix+동선, fallback) · `assemble_itinerary`(**구조화 일정 + rationale *재료*만**, 결정론) + 조건부 엣지(thin→재anchor / walk→재클러스터·되묻기 / modify→재진입).
- **자연어 최종 설명은 subgraph 밖 response 노드(supervisor)** — 산문 LLM을 루프 안에 넣지 않음(수정마다 전체 재narration 방지, 대화 맥락 필요, 슬롯 단위 로컬 갱신 가능). assemble은 *왜 이 장소냐*(seed/테마/soft/sim 근거)를 필드로만 남김.
- **함수(노드 안, 결정론):** place relevance 필터(best×0.6) · soft theme-gate · **테마 균형 quota(요청 baseline + profile 틸트, 항상)** · **용량제약 k-medoids(seed anchor·medoid·비-seed 트림)** · max-leg/상한 게이트 · 총이동시간 점수. → 별도 노드 ❌(과분해 금지).
- Supervisor 라우팅: `city_select subgraph → planner subgraph`, 수정은 planner subgraph 재진입.

## 8. 확정 파라미터
| 항목 | 값 |
|---|---|
| 구조 | **Planner = subgraph** (수정·폴백·되묻기 루프), 노드 retrieve_places→route_days→assemble_itinerary |
| place relevance 필터 | **sim ≥ best × 0.6** (duration: 당일0.7/1박0.6/2박0.5) |
| seed | 테마별 best, must-include(floor) |
| soft | **theme-gated 포함**(raw-kept ∪ soft∩요청테마) + 재정렬 |
| 테마 균형 quota | **항상 켜짐** · baseline=요청 가중치(중립=균등) · profile=선택적 틸트(중간 config) · seed floor·availability·cap |
| 이동시간 기준선 | **driving(모두의 proxy)**, 시간 기반 · foot=compact만 walkable 신호 · transit≈drive×1.3~1.5 근사 |
| snap | **null/unroutable만 제외**(거리는 audit) · trekking은 foot snap |
| 동선 | **driving-time 용량제약 k-medoids**(seed=anchor, 빈 날=medoid, outlier≠대표) · 초과날 비-seed 트림 |
| 한계 | drive max-leg ≤60분 · 하루 ~150분 (foot: compact 한정 walk30/day90) · 점수=총이동시간 |
| 장소 수 | 기간 고정(당일4/1박8/2박12), 체류 미고려 |

## 9. 검증 결과
**오프라인(anchored v2 51케이스):**
- 1차필터 best×0.6: median 9곳, 빈셋 0, **seed 전수 생존 51/51** ✓.
- soft theme-gated 포함: on-theme +4곳, off-theme 5.5곳 제외 ✓.
- 테마 균형 quota: 중립=균등(6/6), profile 있으면 기움(018 역사8/바다4), 희소는 availability 캡 ✓.

**라이브 ORS(단양·속초·동해 각 14곳, snap radius 1km + driving/foot matrix):**
- **snap >1km 0건/42곳.** 최대 단양 구담봉 805m(driving)인데 *foot 6.5m* → profile 의존성 실증. 실패는 거리 아닌 **null 1건**(청초호=호수 중심점). → snap=null-only 제외 확정.
- **walk 가능성 도시 의존**: 도보 median 속초**33**/동해**121**/단양**263**분. driving median 5.8/11.6/35.6분. → 도보는 compact(속초)에서만 성립, 나머진 대중교통/차.
- **용량제약 클러스터링 검증**: 순수 k-medoids는 13+1·12+1+1 *싱글톤 outlier 날* 생성(단양 소백산천문대 1곳짜리 날). 용량제약 넣으면 **속초7+7·동해7+7·단양5/5/4 균형**, medoid 항상 중심(평균<군집 최악점), **outlier는 medoid 안 됨**(흡수). max-leg는 spread 도시(단양 53~62분)에서만 발동 → 비-seed 트림 신호. compact(속초 max 9.6분)는 게이트 무의미.

**남은 라이브 검증:** 추가 regime — 거제(해안 흩어짐, `examples/geoje_in_city_itinerary_set.csv`)·부여(평지 유적 밀집, `examples/buyeo_in_city_itinerary_set.csv`) 세트 생성됨, repo에서 `--snap-radius-m 1000`로 실행 후 분석 예정. 광역 구 STAT 결여는 별도.

---

## 10. 구현 지시 (Implementation Handoff)
> 단계명: **In-city Itinerary Build**(구 In-city Itinerary). 노드 `retrieve_places → route_days → assemble_itinerary`(subgraph).

### A. 확정 — *재논쟁 금지* (데이터·검증 근거 있음)
- place relevance 필터 **best×0.6**(duration 0.7/0.6/0.5) + **seed 보존**.
- soft = **theme-gated 포함**(raw-kept ∪ soft∩요청테마) + 재정렬.
- **테마 균형 quota = 항상 켜짐**(요청 baseline, profile은 틸트). seed floor=비율 아닌 존재 보장이므로 quota 필수.
- snap = **null/unroutable만 제외**(거리는 audit), trekking은 foot snap.
- 이동시간 = **driving 기준선(시간 기반)**, foot=compact만 walkable 신호, transport_pref=선호+안내(게이트 ❌).
- 동선 = **driving-time 용량제약 k-medoids**(seed=anchor, 빈날=medoid, outlier≠대표, 순수 k-medoids 금지), 초과날 비-seed 트림.
- 날 배정 = 최근접 anchor / 날 내부 순서 = 최근접 + 시각대 보정, **sim 재정렬 금지**.
- assemble = **구조화만**, NL은 subgraph 밖. 수정 = **로컬·안정**(캐시 재사용 + 미변경 날 freeze).
- 장소 수 기간 고정(당일4/1박8/2박12), 체류 미고려.

### B. 구현 에이전트가 정할 것 — *내 권고를 비준*(처음부터 재설계 ❌)
1. **입력 state 계약(PlannerInput)** — 필수 필드: `selected_city(+ddb_pk)`, `cleaned_raw_query`, `soft_query`, `active_themes`, `effective_theme_weights`, `trip_duration`, `transport_pref`, `user_location`. *출처*(city_select passthrough vs intent/profile)를 V2_15 출력·intent 스키마에 맞춰 확정.
2. **query_vector 배선** — Planner가 `embed_query(cleaned_raw)`·`embed_query(soft)` 직접 호출(city_select V2_15 ⚠#1과 동일 어댑터 `BedrockEmbeddingAdapter`). 캐시 공유.
3. **profile 결합 위치(미해결 #5)** — **권고: 상류 1회 결합**(intent→profile이 effective_theme_weights 생성, city_select·Planner가 동일 소비). 재결합 ❌.
4. **assemble 출력 스키마** — 초안: `Itinerary{ days:[{day, anchor_place_id, anchor_type(seed|medoid), places:[{place_id, title, theme, order, leg_min_from_prev, reason_code, evidence}], day_travel_min}], reserve[], notices[](walk/transit·thin·trim·축제), audit{score_breakdown, snap, fallback_used, trimmed[]} }`. 필드명 확정은 에이전트.
5. **수정 캐시 메커니즘** — pool+working set+matrix를 LangGraph checkpoint/state 어디에 둘지(구현 자유), 규칙(§7-a)은 고정.
6. **시각대 휴리스틱** — 일출/낙조/야경 키워드 사전, DRAFT 포함 여부.

### C. DRAFT 범위 — *결정론 happy-path만*
- **포함**: retrieve_places → route_days → assemble_itinerary 직선 흐름.
- **제외(후속)**: modification 루프, 전체 clarification interrupt 기계(walk·thin은 *notice 문자열*로), avoid/include constraint(최소판도 후속), GTFS transit.

### D. 검증 기준 (PR 전)
- offline: seed 전수 생존, 멀티테마 **균형**(중립=균등) 확인, best×0.6 빈셋 0.
- live ORS: 용량제약 군집 균형 + medoid 중심성, snap null-only, 추가 regime(거제·부여).
- 단위 검증: `duration_min`은 *분* (초 환산 금지 — 과거 버그).
