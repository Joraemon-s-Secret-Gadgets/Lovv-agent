# V2_16 City Monthly Weather Risk Table

> 목적: 최신 수집본 `C:\Users\Playdata\Downloads\cities.json`의 `climate_table.wikitext`가 존재하는 도시를 대상으로, `city_id + month` 단위의 월별 기후 리스크를 사전 계산해 V2 런타임에서 조회 가능하게 만든다.

## 1. 산출물

| 파일 | 용도 |
|---|---|
| `src/lovv_agent_v2/resources/city_monthly_weather_risks.json` | `city_id + month`별 월별 기후 metric과 risk 결과 |
| `src/lovv_agent_v2/resources/city_monthly_weather_thresholds.json` | risk 계산에 사용한 전체/월별 분위수 threshold와 산식 |

이 데이터는 실시간 예보가 아니라 월별 평년 기후 기반 risk table이다. 따라서 사용자-facing 문구는 "비가 온다"가 아니라 "해당 월은 평년 기준 비/더위/추위 리스크가 높은 편"으로 표현해야 한다.

## 2. 입력 데이터 범위

최신 수집본 기준:

| 항목 | 개수 |
|---|---:|
| 전체 도시 | 229 |
| `climate_table.wikitext` 존재 | 68 |
| 파싱 성공 도시 | 68 |
| 생성된 risk row | 816 |

metric별 coverage:

| metric | 도시 수 |
|---|---:|
| `avg_high_c` | 68 |
| `avg_mean_c` | 66 |
| `avg_low_c` | 68 |
| `precip_mm` | 68 |
| `precip_days` | 65 |
| `snow_days` | 12 |
| `humidity_pct` | 65 |
| `sunshine_hours` | 64 |

`snow_days`는 coverage가 낮으므로 보조 signal로만 취급한다. 또한 `snow_days == 0`은 같은 월 분위수 threshold가 0인 경우에도 risk point를 부여하지 않는다.

## 3. Risk 계산 원칙

기준은 절대 임계값이 아니라 현재 보유한 climate table 분포에서 만든 상대 기준이다.

두 종류의 threshold를 함께 사용한다.

| threshold | 의미 |
|---|---|
| global percentile | 68개 도시 x 12개월 전체 city-month 분포에서 p10/p25/p50/p75/p90 |
| same-month percentile | 같은 월에 해당하는 68개 도시 분포에서 p10/p25/p50/p75/p90 |

global threshold는 "한국 여행에서 이 달 자체가 까다로운가"를 잡고, same-month threshold는 "같은 달 다른 도시보다 이 도시가 더 까다로운가"를 잡는다.

## 4. 주요 Global Threshold

| metric | p10 | p25 | p50 | p75 | p90 |
|---|---:|---:|---:|---:|---:|
| `precip_mm` | 26.15 | 42.075 | 78.35 | 147.0 | 274.65 |
| `precip_days` | 5.4 | 6.7 | 8.5 | 9.9 | 14.1 |
| `avg_high_c` | 5.5 | 9.9 | 19.5 | 26.1 | 29.1 |
| `avg_low_c` | -5.4 | -0.6 | 7.4 | 16.525 | 21.2 |
| `humidity_pct` | 56.8 | 62.2 | 68.65 | 75.0 | 79.4 |
| `sunshine_hours` | 151.5 | 163.7 | 181.65 | 202.875 | 219.59 |
| `snow_days` | 0.0 | 0.0 | 0.0 | 2.2 | 6.44 |

## 5. Dimension별 산식

### Upper-tail metric

값이 높을수록 risk가 커지는 metric에 적용한다.

대상:

- `precip_mm`
- `precip_days`
- `avg_high_c`
- `humidity_pct` 보정
- `snow_days`

점수:

| 조건 | 점수 |
|---|---:|
| global p90 이상 | +2.0 |
| global p75 이상 | +1.0 |
| same-month p90 이상 | +1.0 |
| same-month p75 이상 | +0.5 |

### Lower-tail metric

값이 낮을수록 risk가 커지는 metric에 적용한다.

대상:

- `avg_low_c`
- `sunshine_hours`

점수:

| 조건 | 점수 |
|---|---:|
| global p10 이하 | +2.0 |
| global p25 이하 | +1.0 |
| same-month p10 이하 | +1.0 |
| same-month p25 이하 | +0.5 |

## 6. Risk Dimension

| dimension | 사용 metric |
|---|---|
| `rain` | `precip_mm`, `precip_days` |
| `heat` | `avg_high_c`, `humidity_pct` |
| `cold` | `avg_low_c` |
| `low_sunshine` | `sunshine_hours` |
| `snow` | `snow_days` |

dimension severity:

| 점수 | severity |
|---:|---|
| 3.0 이상 | `high` |
| 1.5 이상 | `medium` |
| 그 외 | `low` |

overall severity:

| 조건 | severity |
|---|---|
| 하나 이상의 dimension이 `high` 또는 total score >= 4.0 | `high` |
| total score >= 2.0 | `medium` |
| 그 외 | `low` |

최신 생성 결과의 overall 분포:

| severity | row 수 |
|---|---:|
| `low` | 354 |
| `medium` | 227 |
| `high` | 235 |

## 7. 런타임 사용 방식

V2 런타임에서는 매번 climate table을 파싱하지 않는다.

권장 흐름:

```text
selected_city_id + travel_month
→ city_monthly_weather_risks.json lookup
→ overall/dimension/reason_codes 확인
→ itinerary outdoor ratio와 결합
→ weatherNotice 여부 결정
```

notice trigger 초안:

| 조건 | 동작 |
|---|---|
| `overall == medium` + outdoor/mixed slot >= 40% | 약한 `weatherNotice` |
| `overall == high` + outdoor/mixed slot >= 25% | 강한 `weatherNotice` |
| `overall == high` + outdoor/mixed slot >= 50% | 실내 대체 일정 추천 |

V2.0에서는 primary itinerary를 자동 변경하지 않는다. 사용자가 동의하면 modification loop에서 affected outdoor slot만 실내/저위험 subtype 후보로 교체한다.

## 8. 해석 예시

수원시 7월은 다음 signal로 `overall: high`가 된다.

```text
precip_mm = 385.1
precip_days = 15.4
avg_high_c = 29.3
humidity_pct = 79.9
sunshine_hours = 138.2
```

해석:

```text
7월 수원은 평년 기준 강수량과 강수일수가 높은 편이고, 습도가 높은 더위 및 낮은 일조시간 리스크도 있어 야외 일정에는 실내 대체 후보를 준비하는 것이 좋다.
```

## 9. 주의사항

- `climate_table.wikitext`가 없는 도시는 이 table에 포함하지 않는다.
- 이 값은 월별 평년값이므로 특정 여행일의 실제 날씨를 보장하지 않는다.
- `reason_codes`는 사용자-facing 문구에 그대로 노출하지 않고, 설명 생성 또는 judge/debug 용도로 사용한다.
- 추후 live forecast를 붙이더라도 이 table은 "월별 기본 리스크" 역할을 유지한다.
