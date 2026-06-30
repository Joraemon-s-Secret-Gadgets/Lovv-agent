# V2_22 — Profile theme-weight config (확정)

> Profile 에이전트가 저장 여행 이력으로 테마 가중치를 학습 → city_select의 effective theme_weights로 반영. 2026-06-30 확정.
> 데이터: `docs/tasks/results/v2_profile_personas/`(personas + rescore comparison). 검증: v2 smoke 52케이스 × 20 페르소나 offline 그리드.
> (※ 문서 번호: 21은 축제 지시서가 선점 → 프로필은 22.)

## 확정값 — "중간(medium)"
| 파라미터 | 값 | 비고 |
|---|---|---|
| **weight range** | **[0.8, 1.3]** (medium) | ★ 실질 유일한 레버 |
| alpha | 1.5 | 포화 영역(1.5↑ 차이 미미), 기본값 |
| profile_score_cap | 0.05 | 거의 non-binding(평평 coverage라 tilt가 작음), 기본값 |
| profile_activation_saved_trip_count | 3 | **3건 미만 → profile 완전 off(하드 게이트)** |

## 학습 공식 (reference)
```
observed_ratio = saved_theme_counts[t] / total_saved_theme_count
raw_weight     = 1 + alpha·(observed_ratio − 0.2)          # 0.2 = 1/5 균등 기준
learned_weight = clamp(raw_weight, 0.8, 1.3)
confidence     = min(saved_trip_count / 3, 1.0)            # 단, trips<3이면 effective=1(off)
effective      = 1 + confidence·(learned_weight − 1)
```
city_select: active 테마에 대해 effective를 **정규화**한 w[t]를 coverage에 사용. profile의 도시점수 영향은 **±cap(0.05) 클램프**.

## 검증된 동작 (offline 그리드)
- **하드 게이트 필수** — 활성 게이트 없으면 2건짜리 프로필(P03/P04)이 선택을 바꿔 대조군이 깨짐. 게이트 추가 시 **대조군 0** ✓.
- **대조군 항상 inert(0)**: 신규(P00)·콜드스타트(P01~04)·무선호 균등(P15·P19) → 어떤 config든 선택 불변.
- **medium에서 ~10/20 페르소나가 변경**, 페르소나당 ≤2케이스. 전부 **선호 테마 방향**(sea-lover→해안, art→art도시, history→history).
- **멀티테마 요청에서만 실효** — 단일테마는 정규화하면 불변.
- **cap·alpha는 거의 비결정적**; weight *범위*가 실질 레버(약 5/20, 중 10/20, 강 13/20).

## 한계·주의
- profile은 city_select의 **art→대도시 누수를 물려받음**(art 선호 프로필이 종로구류로 1건 밈) — scoring 아닌 데이터/태깅 이슈.
- 절대 변경 수는 cap 적용 세부에 따라 repo md(7/20)와 offline 재현(10/20)이 약간 다름; **패턴은 동일**(대조군 inert·범위>alpha>cap·art누수 제한).
- profile은 **active_themes를 절대 안 건드림**(선택 테마 *내*에서만 tilt). raw=결정권, profile=추천권.

## 통합 메모
- Intent→Profile agent가 request_theme_weights + profile effective를 결합 → city_select가 결합된 effective theme_weights를 소비(V2_15 변경 0). city_select는 결합 결과만 봄.
