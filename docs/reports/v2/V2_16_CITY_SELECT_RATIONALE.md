# V2_16 — city_select 결정 근거 (데이터 기반)

> 목적: city_select 로직을 *왜* 이렇게 정했는지, 실측 근거와 함께 남긴다. 구현 규격은 V2_15, 이 문서는 *이유*.
> 데이터: retrieval 스모크 53케이스(`v2_retrieval_smoke/20260629T184646`, top_k=50, 실메타데이터+좌표) + `city_stats.json`(207도시 방문객) + 함평·경주 S3 원본.
> 작성: 2026-06-29. 표본 53케이스라 **방향성 결론**(절대 보정값 아님)임을 전제.

---

## 0. 확정 수식
```
city_score = Σ_{covered t} w[t]·best_sim[t]      # 가중 테마 coverage
           − Σ_{missing t} w[t]                   # 명시 테마 누락 감점 (pen_coef=1.0)
           − distance_penalty                      # user_location 있을 때만, duration 스케일
           − congestion_penalty                    # logMM × w_cong (중립도 소도시 lean)
           # soft_query는 city_select에서 안 씀(검색·점수 전부) — passthrough로 Planner만
```
`best_sim[t] = 1 − cosine_distance` of 그 도시 테마 t best 장소. `w[t]` = effective theme_weights(없으면 균등).

---

## 1. 전체를 관통하는 1차 사실 — 유사도가 압축돼 있다
- rank-1 유사도 median **0.27**(범위 0.15~0.74). 랭크 깊어져도 distance 0.74→0.85로 완만, **knee 없음**.
- 임베딩 원문은 메타데이터 중심(이름·유형·도시·지역·주소·분류·테마 + 설명). 짧은 쿼리가 이 덩어리와 느슨히 매칭 → 절대 코사인이 낮게 깔림.
- **귀결: 도시들이 coverage상 거의 동점(near-tie).** 이게 아래 거의 모든 결정의 뿌리다. 부차 신호(distance/congestion/soft)를 항상 켜면 평평한 coverage를 이겨버리므로 → **게이트 + 0.0x 스케일이 강제**된다.

## 2. semantic_evidence 제거 → coverage − penalty
- 단일 테마에서 `semantic_evidence`(상위 평균)와 `coverage`(테마 best)가 **동일값**(000·002·026 sem=cov 일치 = 이중계산).
- 멀티 테마에선 둘이 **반대로 당김**(depth vs breadth). depth는 best_sim에 이미 포함 → 정보 손실 0.
- → 별도 sem 항 폐기. (구 정책의 max(seed)/÷budget 분모 논쟁 전부 무효.)

## 3. missing penalty = 안전장치 (튜닝 노브 아님)
- pen 0→0.5→1.0에서 top-1 변경 **0/53**. 선정 도시는 *항상* 전 테마를 커버하므로 winner엔 penalty가 안 물림.
- 수치: 완전커버 ≈ +0.25 vs 한 테마 빠짐 ≈ −0.4 → coverage+penalty가 완전성을 *압도적으로* enforce. penalty는 그 격차를 벌릴 뿐, tie-break까지 갈 일이 없음.
- → "하나라도 빠지면 페널티"는 *이미* 작동 중. 단 이를 하드화하면 = 제거한 **AND 게이트 회귀**(멀티테마 88% 도시 몰살). soft penalty 유지가 정답. **완전커버 도시가 없을 때만** 부분커버를 완전성 순으로 정렬(대안·Plan B용).

## 4. top_k = 50
- M=1(선택만): k50 vs k100 **0/53**, k30 vs k50 4/53.
- M=2(선택+대안1): k50 vs k100 **0/53**, k30 vs k50 **12/53**.
- knee 없으니 유사도 컷 불가 → **노출 도시 수 M으로 N 결정**. M=2 기준 50이 100과 동일·30보다 우수, 비용은 100의 절반.

## 5. congestion — logMM, w_cong 재스케일, 소도시 lean
- 정규화 = **log min-max**(ADR `CONGESTION_INDEX_SCORING_ADR`, rank·logFix 기각). pool-relative, 통계없음→0.5. **207/207 도시 실데이터 적용 확인**(0.5 fallback 0).
- w_cong = V1의 0.35/0.10/−0.25는 budget 인플레 base(~2.5) 기준 → V2 base(~0.2)엔 ÷7: **조용 +0.08 / 중립 +0.03 / 혼잡 −0.05**.
- **중립 +0.03(0 아님) = "소도시 추천" 제품 기본 기조.** 실측: 중립 +0.03 → top-1 변경 4/37 전부 더 한적한 도시로(오작동 0).
- ⚠ **미해결: 입력값.** 분석은 `annual_visitors`(12개월 합)를 썼으나, 설계 의도는 **travel month total_visitors**(`by_month[month]`). 월 편차 큰 도시(양양 여름/겨울)는 결과가 달라짐 → 현 분포는 **month-agnostic 근사**.
- ⚠ **게이트 논점(미확정)**: 명시 pref(조용/혼잡)는 본질적 게이트. **중립 +0.03만 "항상 켜짐"**. 순수유사도 대비 21% 변경 중 **8건은 명시 quiet, 3건만 중립 default-lean**(017·028·030). 중립을 0으로 게이트하면 이 3건이 큰 도시로 복귀. → **"소도시 default 유지 vs 명시할 때만"은 제품 결정으로 열려 있음.**

## 6. distance — 게이트 + duration 스케일
- coverage 평평 → w=0.05만 줘도 top-1 **23/51 flip**(서울 origin). tie-break이 아니라 **주 결정자** → 항상 켜면 안 됨.
- **user_location 있을 때만** 발동. `w_dist · min(km/300, 1)`, **duration 스케일**: 당일 0.08 / 1박2일 0.04 / 2박3일+ ~0(off). (긴 여행은 거리 부담↓.)
- 서울 origin ON(0.08) 시 median 거리 223→104km로 수도권 당김 — 당일치기엔 적절, 다박엔 과함(그래서 off).

## 7. soft_query — city_select에서 완전 제거
- score에서 빼고 + **검색·`soft_distance` 주입도 삭제**. 안정안(soft-only 도시 admission 안 함)이라 soft가 pool도 score도 안 건드리면 **죽은 코드**. raw-only 채점에선 soft가 넣은 장소도 raw_sim 낮아 best_sim 못 됨 → 영향 0.
- 3중 부적합 확인: ① coverage 평평으로 신뢰불가(quiet 5/9·vibrant **0/6**), ② crowd 무드는 congestion 상위호환, ③ HyDE는 **정의상 *장소* 묘사 매칭**(도시는 분위기 불균질 = category 불일치), ④ 설명 텍스트가 사실형(함평·경주 확인) → 자연·경관 편향(place 레벨도 약함).
- soft_query는 **passthrough로 Planner(place 레벨)에만**. atmosphere는 데이터 보강(분위기 요약 임베드) 후 HyDE를 Planner에서 1급으로 — 별건 백로그.

## 8. 분기 — anchored / no_candidate / discovery
- **ANCHORED**(destination 있음): 그 도시 고정. 단 고정 도시 테마 후보 0 → **no_candidate**(다른 도시 바꿔치기 금지. 검증: 영양+바다 ✓).
- **NO_CANDIDATE**: **count(후보 존재) 기반**, 절대 유사도 floor 아님(best median 0.26이라 floor 걸면 다 탈락).
- **DISCOVERY**: top-1 + 대안(런너업) 1개(M=2).
- 검증: 경주 anchored ✓, 영양 no_candidate ✓.

## 9. theme_balance 제외 → Planner
- coverage(합)는 balance에 눈멈((0.3,0.1)=(0.2,0.2)). theme_balance는 별개 신호 *맞음* → 무의미 아님.
- 그러나 ① coverage가 테마별 강도는 이미 반영, ② 극단(부재)은 penalty, ③ 미묘 불균형은 평평 노이즈 속 또 하나의 작은 레버, ④ "실제 채울 수 있나"는 **풀 깊이 = Planner Pass2** 문제. → city_select에서 빼고 Planner로.

## 10. 도시 키 정규화 (임시)
- 인덱스가 같은 도시를 두 casing(`CITY#ANDONG`↔`CITY#Andong`, place_id 교집합 0)으로 적재. 40개 도시 split. **그룹핑 키 = `ddb_pk.upper()`** + alias(`CITY#GOSEONG→-GANGWON`). 재적재로 해소될 임시 처리.

---

## 11. 분포 검증 (53케이스, 락한 로직 적용)
- **30/53 distinct 도시** — 쏠림 없음. 최다 경주 5(전부 역사 = 정상).
- **소도시 lean 작동**: DISCOVERY 선정 방문객 median 30M, 다수 군 단위.
- **약점 2개(주로 데이터 문제)**:
  - **예술·감성이 대도시를 끌어옴**(화성 304M·종로 217M·세종 115M). art subtype이 도시 집중 + 태깅 노이즈(주상절리전망대→예술 등). 소도시 lean으로도 못 누름.
  - **도시 구(區) 누수**: 자연 요청에 구로구(144M) 1위. 구는 관광지 많아 lean으로 안 밀림.

## 12. 점수 요소 분해 (decisiveness / magnitude)
| 항 | top-1 바꾼 횟수 | 선정도시 크기 median |
|---|---|---|
| coverage | 기준(자격심사) | +0.257 (0.15~0.74) |
| missing penalty | 0/51 (무력) | 0.000 |
| congestion | 11/51 (~22%) | ±0.020 |
| distance(서울) | 23/51 (~45%) | +0.028 |

- **역설: coverage는 크지만 평평 → 자격만 부여. 작은 congestion·distance가 실제 결정자**(평평한 동점을 깸).
- 순수유사도 vs 최종: congestion만 **11/51(21%) — 전부 큰→작은, 테마 보존**(서산→옹진, 경주→함평·거창, 종로→인제…). +서울 distance까지면 26/51(50%).
- 해석: 순수유사도면 "유명 대도시" 추천, 우리 로직이면 "숨은 소도시" — 의도된 제품 선택. 이상 flip(엉뚱한 도시) 없음.

---

## 13. 한계 (정직)
1. **표본 53케이스** — 방향성만, 절대 보정값 아님.
2. **congestion = annual**(travel-month 미적용). 월 편차 도시는 달라질 수 있음.
3. **도시 좌표 = 후보 place 평균**(centroid 프록시).
4. **art·구 약점은 데이터(태깅·구 엔트리) 문제** — scoring으로 못 고침.
5. soft/atmosphere는 substrate(설명 텍스트) 부재로 미검증.

## 14. 다음 사이클 백로그
- congestion 입력을 **travel month**로 교체(`by_month`).
- **중립 게이트 결정**: 소도시 default(+0.03) 유지 vs 명시할 때만(0).
- 예술·감성 **테마 태깅 정리** / **구(區) 단위 demote·제외**.
- **선호 subtype 추출**(intent, theme-scoped, 추출+결정론 매핑, soft boost) → place-type. soft HyDE 대체.
- **atmosphere 데이터 보강** → HyDE를 Planner place 랭킹에 1급.
- **Planner Pass2**: 테마별 풀 깊이 체크 → 얇은 도시면 alternative_city 폴백(theme_balance도 여기).
- **seed 설계**(별도 논의).
