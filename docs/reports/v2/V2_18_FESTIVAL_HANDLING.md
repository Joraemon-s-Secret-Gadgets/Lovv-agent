# V2_18 — 축제(festival) 처리 설계

> 목적: V2에서 축제를 어떻게 다루는지 확정. city_select·Planner·Festival Verifier 경계.
> 작성: 2026-06-29.

---

## 0. 핵심 — 축제는 관광 테마와 범주가 다르다
- 관광지(바다·역사·자연·예술·온천) = 정적 장소 → **vector 유사도 → best_sim → coverage**.
- 축제 = **시간(월)에 묶인 이벤트** → "여행 *월*에 그 축제가 열리나"가 핵심 → **유사도 아님, 월×위치 join.**
- 그래서 축제는 **vector 검색·city_score에서 제외**(EXCLUDED_THEMES). DynamoDB(`FESTIVAL#id`, `visit_months`/season)로 해결.

## 1. include_festivals = 명시적·절대적 토글
- 챗봇이 "축제 포함할까요?"를 **직접 물어 사용자가 답한 boolean**. 추론·강도 판정 없음.
- **false → 축제 경로 전부 off.** true → 축제는 **하드 요구**.

## 2. 매칭 단위 = 월 (날짜 아님)
- 여행 **월**에 개최되는 축제만 매칭. (congestion도 travel-month → 월이 공유 신호.)

## 3. 흐름 — Festival Verifier가 city_select **앞단 게이트**
```
include_festivals=true
  → Festival Verifier (먼저, 1회)
       : DynamoDB city×여행월 축제 검색 → 검증 → '검증된 축제 도시' 집합 F
  → city_select : F 안에서만 관광 coverage+congestion 점수 (allowed_city_ids = F)
       F ≥ 2 → 점수로 선택
       F = 1 → 그 도시 (단 관광 테마 missing은 정직하게 보고)
       F = 0 → no_candidate / 되묻기
```
- **검증이 선택 *전*에 끝남** → "축제 보러 골랐는데 안 열림" 사고 차단. 선택 후 재검증·폴백 불필요.
- **"검증된 축제 도시 우선시" 구조적 보장** — 미검증은 F에 못 듦.
- **city_select는 축제를 몰라도 됨** — Verifier가 준 allowed set만 받음(retrieval_node 슬림화와 일치, festival은 별도 노드).
- 그래프: `Supervisor → (include_festivals면) Festival Verifier → city_select`.

## 4. Festival Verifier가 모든 축제-가용성 fallback을 한 곳에서 처리
- **discovery + 축제**: F 산출. **F=0 → 되묻기**("그 달엔 검증된 축제가 없어요. 축제 빼고 볼까요?").
- **anchored(도시 고정) + 축제**: 고정 도시 ∈ F 인지 검사.
  - 들면 → 진행.
  - **안 들면 → city↔festival 충돌**(둘 다 사용자 지정, 그 달 양립 불가) → **되묻기**("경주엔 그 달 축제가 없어요. 축제 빼고 경주로? 아니면 축제 있는 다른 도시?").
- → 축제 불가 상황이 전부 **city_select 이전, Verifier 단에서** 통일 처리. city_select는 깨끗한 F만 받음.

### 4-a. 되묻기 해소 = anchored 진입 (통일 규칙)
되묻기는 **구체 도시를 제시**하고, 사용자가 "그대로 간다(이 도시로)"고 하면 → **그 도시로 anchored 모드 진입.** 어느 해소 경로든 결국 *확정 = anchored*:
- "축제 빼고 경주로" → **anchored 경주**, `include_festivals=false`.
- "축제 있는 다른 도시로" → **anchored 그 축제 도시**, festival on(이제 도시 고정).
- discovery F=0도 "축제 빼면 OO 추천, 거기로?"로 **구체 제시** → 확인 → **anchored OO**.
- 메커니즘: 되묻기 = **interrupt**, 사용자 응답 = **resume**(memory checkpointer). resume 시 state가 `destination_id=확정도시` + `include_festivals` 갱신 → 이후 **anchored 경로**(Planner In-city Itinerary city-fixed).
- 효과: 확정된 도시는 **재선택 안 함** — city_select 점수 우회, 바로 그 도시로 In-city Itinerary.

## 5. 검증 비용 — 전수 검증이 성립하는 이유
- Verifier는 F의 **모든 후보를 검증**하지만, F는 이미 **월 필터로 좁혀진 집합**(그 달 축제 있는 도시만)이라 작음 → 전수 검증 감당 가능.
- (만약 검증이 *극도로* 무겁고 F도 크면 그때만 2단계로: 싼 date_status 필터로 게이트 + 선택 도시 1개만 깊은 검증.)

## 6. Planner
- 검증된 축제 = **must-include seed**. 그 달/날짜에 일정 배치(시간 묶인 이벤트).
- seed-must 제약에 축제 seed 포함.

## 7. 정리
| 항목 | 처리 |
|---|---|
| 데이터 | DynamoDB `FESTIVAL#id` (vector 아님) |
| 매칭 | 여행 **월** |
| 토글 | `include_festivals`(명시·절대) |
| 위치 | **city_select 앞단 게이트 노드**(Festival Verifier) |
| 선택 기여 | F로 후보 제한(하드), F 내부는 관광 coverage로 랭킹 |
| fallback | Verifier 단에서 통일 — discovery F=0 / anchored 충돌 → 되묻기 |
| Planner | 검증 축제를 must-include seed로 월/날짜 배치 |

## 8. 확정 — Verifier 출력 계약 + date_status 정책 (2026-06-29)

### 8-a. Festival Verifier → city_select 출력 (검증된 도시 집합 F)
기존 데이터·스키마 대부분 준비됨: festival에 `visit_months`·`event_start/end_date`·`season`; intent에 `include_festivals`·`travel_month`·`execution_mode`(`festival_seeded_city_discovery`/`festival_anchor`); 코드에 `FestivalVerification`·`FESTIVAL_DATE_STATUSES`. **신규는 도시-묶음 wrapper 하나:**
```
FestivalGateResult {
  status:  ok | no_candidate | needs_clarification
  tier:    confirmed | tentative | none
  verified_festival_cities: [
    { ddb_pk(canon upper), city_id, festivals: [ FestivalVerification, ... ] }   # 월-매칭·검증 축제 ≥1
  ]
  clarification: {...} | null
}
```
- city_select: `allowed_city_ids = verified_festival_cities[].ddb_pk`. 도시 랭킹은 평소대로(관광 coverage+congestion) — 축제는 **게이트지 랭커 아님**.
- Planner: 선택 도시 `festivals[]` → **must-include seed**(FestivalVerification의 날짜·`planner_policy`로 배치).

### 8-b. date_status 자격 + 2단 tier
1. **월 게이트(1차)**: `travel_month ∈ festival.visit_months`(주 매칭).
2. **status tier(2차)**:
   - **Tier 1 `confirmed`** — confirmed 도시 ≥1이면 **F=confirmed만**.
   - **Tier 2 `tentative`** — confirmed 전무할 때만 fallback. F=tentative + "날짜 미확정" 플래그(planner_policy note, 되묻기 안 함).
   - **제외(항상)**: `unknown`·`outdated`·`skipped`·`no_candidate`.
3. **F=0**(confirmed·tentative 둘 다 없음) → 되묻기. anchored 고정도시가 tier1/2 아니면 충돌 → 되묻기(§4-a).
- `is_applicable_to_trip` = (월 매칭 ∧ status∈{confirmed,tentative}). "검증된 우선"은 confirmed-우선 tiering으로 구현.

## 9. 남은 refinement (구현 차단 아님)
- 축제의 **테마 적합도 가산**(F 내 랭킹 우대) — 축제 theme_tags 활용, 향후.
- 되묻기 응답(축제 빼기/도시 바꾸기)의 **modification 루프** 연결.
- 검증의 외부 확인(웹) 필요 여부 — 현재는 DynamoDB date_status로 충분 가정.
