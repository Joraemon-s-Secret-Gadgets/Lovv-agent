# V2_17 Profile Theme Persona Fixtures

> 목적: profile 기반 `theme_weights` 튜닝을 위해, 저장 횟수와 테마 선택 이력이 다른 synthetic persona fixture를 먼저 고정한다.

## 1. 산출물

| 파일 | 용도 |
|---|---|
| `docs/tasks/results/v2_profile_personas/profile_theme_personas.json` | profile theme-weight 튜닝용 synthetic persona set |

이 파일은 실제 사용자 DB seed가 아니다. scoring 식과 judge 실험에서 동일한 profile 입력을 반복 사용하기 위한 fixture다.

## 2. 테마 축

V2 Intent 기준의 5개 canonical theme를 사용한다.

| theme id | 의미 |
|---|---|
| `sea_coast` | 바다·해안 |
| `nature_trekking` | 자연·트레킹 |
| `history_tradition` | 역사·전통 |
| `art_sense` | 예술·감성 |
| `healing_rest` | 온천·휴양 |

default profile은 모든 theme weight를 `1.0`으로 둔다.

## 3. Persona 구성

fixture는 저장 횟수 기준으로 다음 구간을 포함한다.

| 구간 | 의도 |
|---|---|
| 0회 | 신규 유저 baseline |
| 1회 | cold-start 단일 신호 |
| 2회 | threshold 이전 반복/복합 신호 |
| 3회 | profile activation threshold 후보 |
| 5회 | 성숙한 단일/복합 선호 |
| 10회 | 장기 이력 기반 복합 선호 |

총 20개 persona를 둔다.

| persona 범위 | 예 |
|---|---|
| `P00` | 신규 유저 |
| `P01`~`P04` | 1~2회 저장 |
| `P05`~`P08` | 3회 저장 threshold 테스트 |
| `P09`~`P15` | 5회 저장 mature profile |
| `P16`~`P19` | 10회 저장 long-history profile |

## 4. 저장 이력 표현

각 persona는 두 정보를 같이 가진다.

```json
{
  "saved_trip_count": 5,
  "saved_theme_counts": {
    "sea_coast": 3,
    "nature_trekking": 0,
    "history_tradition": 0,
    "art_sense": 0,
    "healing_rest": 2
  },
  "saved_trip_theme_history": [
    ["sea_coast"],
    ["sea_coast", "healing_rest"]
  ]
}
```

`saved_trip_count`는 profile 신뢰도 ramp에 사용하고, `saved_theme_counts`는 theme weight 산출에 사용한다. 멀티테마 일정은 하나의 저장 일정이 여러 theme count를 증가시킬 수 있다.

## 5. Reference Formula

fixture에는 튜닝을 시작하기 위한 reference formula가 포함되어 있다.

```text
observed_ratio = saved_theme_counts[theme] / total_saved_theme_count
raw_weight = 1 + alpha * (observed_ratio - 0.2)
learned_weight = clamp(raw_weight, min_weight, max_weight)
confidence = min(saved_trip_count / profile_activation_saved_trip_count, 1.0)
effective_weight = 1 + confidence * (learned_weight - 1)
```

초기 후보:

```text
profile_activation_saved_trip_count = 3
alpha = 1.0, 1.5, 2.0
weight_range = 0.85~1.20 / 0.80~1.30 / 0.70~1.45
profile_score_cap = 0.03 / 0.05 / 0.08
```

이 값은 확정이 아니라 grid search 시작점이다.

## 6. Tuning에서 볼 것

profile-on 결과가 항상 profile-off보다 많이 바뀌는 것이 목표가 아니다.

| query 유형 | 기대 동작 |
|---|---|
| 명시 테마 query | profile이 명시 테마를 뒤집으면 실패 |
| 모호 query | profile 선호가 Top3/seed에 반영되면 성공 |
| 복합/soft query | 동점권 후보를 자연스럽게 기울이면 성공 |
| 균등 profile | profile-on과 profile-off가 거의 같아야 함 |

권장 acceptance 초안:

```text
explicit query:
- profile_on worse <= 10%
- explicit theme coverage drop <= 5%

ambiguous query:
- profile_on B_better >= 40%
- A_better <= 15%

rank churn:
- explicit query Top3 churn <= 30%
- ambiguous query Top3 churn <= 60%
```

## 7. 다음 작업

1. fixture persona를 기존 retrieval smoke task와 cross product로 결합한다.
2. `alpha`, `weight_range`, `profile_score_cap` grid를 돌린다.
3. profile-off vs profile-on pairwise judge input을 만든다.
4. 명시 요청 보존율을 먼저 통과시킨 뒤, 모호 요청 uplift가 가장 큰 config를 고른다.
