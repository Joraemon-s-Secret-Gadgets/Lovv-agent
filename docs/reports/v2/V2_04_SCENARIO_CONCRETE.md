# V2 시나리오 — 구체화 (In-Scope 전체)

> 작성일 2026-06-28 · 입력: `V2_SCENARIO_INSCOPE.md` + `..._ARCH_IMPACT_MAP.md` · 형식 캘리브레이션: `..._CONCRETE_SAMPLES.md`(흡수).
> 각 시나리오 = **실제 입력값 + 턴별 노드 동작 + 기대 출력 + (V1·고도화 표 / V2 검증결정)**.
> 유형: `[V1·고도화]` 기존 지원 → 품질↑ · `[V2·신규]` V1에 없던 것.
> 노드: Profile · Intent · Supervisor(S) · city_select(retrieval+scoring&selection) · FestivalVerifier · Planner(+Pass2) · Packager · Memory.
> 입력 필드: `themes·tripType·travelMonth·destinationId·includeFestivals·country·userLocation·NL`. 테마: sea_coast·nature_mountain·history_tradition·art_sense·healing_rest.

---

# 1. [V1·고도화] — 기존 시나리오의 고도화
> 이 묶음은 "되던 것"이 V2에서 **점수·동선·개인화·수정가능**으로 좋아짐. 각 표가 곧 V2 가치 증명.

## SC-00 · 발견·단일테마 (조용한 동해안)  `[V1·고도화]`
**Given** (V1 case 01)
```
themes=[sea_coast], tripType=2d1n, travelMonth=9, NL="조용한 동해안에서 2박 쉬고 싶어요"(soft="조용")
Profile: 있음/없음
```
**흐름**: Intent(soft="조용") → city_select(해안 검색 · **congestion 한산 가중** · profile 가중) → 도시 확정(예: 삼척) + seed → Planner(Pass2·배치) → Packager(정상 일정).

| 측면 | V1 | V2 고도화 |
|---|---|---|
| 도시 점수 | semantic 단독 지배 | 점수 재설계(테마·profile 실질 반영) |
| 배치 | FIFO, move=null | seed anchor + geo, `move` 값 채움 |
| 개인화 | 없음 | profile theme_weights 가중 |
| 사후 | one-shot | 자연어 수정 가능(resume) |

**출력**: 정상 itinerary(형식 유지, move 채움). status=`completed`.

## SC-G1 · 발견·다중테마 (자연+해안)  `[V1·고도화]`
**Given**
```
themes=[nature_mountain, sea_coast], tripType=3d2n, travelMonth=10, NL="산이랑 바다 같이 보는 2박3일"
```
**흐름**: Intent → city_select: 두 테마 검색·병합 → **soft 충족도 평가(부분 충족 허용)** → 도시 확정(예: 영덕) + seed → Planner → 정상.

| 측면 | V1 | V2 고도화 |
|---|---|---|
| 테마 게이트 | **AND(전 테마 보유 도시만)** → 멀티테마 풀 급감·소도시 탈락 | **soft(부분 충족 허용, 미충족 강한 감점)** → 소도시 생존, no_candidate↓ |
| 테마 점수 | theme_match 0.2 이진 | theme_weights 비례 |

**출력**: 정상 itinerary. **핵심 고도화 = 멀티테마에서 소도시 발견 가능**(V1 최대 약점 해소).

## SC-G2 · 도시 지정 (anchored)  `[V1·고도화]`
**Given**
```
destinationId="gyeongju", themes=[history_tradition], tripType=daytrip, travelMonth=10, includeFestivals=false
NL="경주 역사 명소 당일치기"
```
**흐름**: Intent(`anchored_place_search`) → city_select(검색 풀=경주 고정, 충족도 평가) → 도시=고정 + seed → Planner → 정상.

| 측면 | V1 | V2 고도화 |
|---|---|---|
| 배치/동선 | FIFO | seed anchor + geo |
| 사후 | one-shot | 수정 가능 |

**출력**: 경주 당일 일정.

## SC-G3 · 축제 포함 (festival_seeded)  `[V1·고도화]`
**Given**
```
themes=[history_tradition], tripType=2d1n, travelMonth=10, includeFestivals=true, destinationId=null
NL="가을 전통 축제랑 유적 같이"
```
**흐름**: Intent(`festival_seeded`) → 축제seed 조회(10월) → allowed 도시 → city_select(제한·충족도) → FestivalVerifier(confirmed 검증) → Planner(축제=그 날짜 배치) → 정상.

| 측면 | V1 | V2 고도화 |
|---|---|---|
| 축제 배치 | **전부 day-1 afternoon 고정** | **실제 날짜·다일/다중 분산**(확장 高) |
| (옵션) 축제 정합 | month+city만(테마 무관) | 테마 정합 필터(데이터 적재 시) |

**출력**: 축제 낀 일정. confirmed 축제만, 미확정은 userNotice.

---

## 1-R. [V1·고도화] 결과(5종) — 유지 + 일부 완화
## SC-R1 · 후보 부족 → 축소  `[V1·고도화]`
**Given**: `themes=[healing_rest], tripType=3d2n` 인데 선택 도시 장소가 슬롯보다 적음.
**흐름**: city_select→도시 확정 → **Planner Pass2 재인출(theme off·top_k 확대)** → 그래도 부족 → 축소 일정 + userNotice.
| V1 | V2 고도화 |
|---|---|
| insufficient 강등만(재인출 없음) | **Pass2 재인출로 먼저 채움** → 축소 빈도↓ |

**출력**: 축소 일정, status=`completed`, userNotice("후보가 적어 축소").

## SC-R2 · 축제 시즌 불일치 → skip  `[V1·고도화]` · 유지
**Given**: 축제 포함인데 축제 날짜가 여행기간과 불일치.
**흐름**: FestivalVerifier → not_placeable → Planner는 축제 제외 배치 + userNotice. (V1과 동일, 분산 배치만 개선)
**출력**: 일정 정상 + 축제만 빠짐 고지.

## SC-R3 · 추천 불가(no_candidate) → 재질의  `[V1·고도화]`
**Given**: 희귀 테마 조합인데 **완전 0매칭**(soft여도 어느 도시도 매칭 없음).
**흐름**: city_select(생존 0) → S → Packager(안내) → `END_WAIT_USER`.
| V1 | V2 고도화 |
|---|---|
| AND 게이트로 **빈발** | soft → **완전 0매칭일 때만**(빈도 급감) |

**출력**: 재질의 안내.

## SC-R4 · 안전 거부(필수 누락) → 거부  `[V1·고도화]` · 유지
**Given**: `source=map_marker` 인데 `destinationId=null`.
**흐름**: Intent/입력검증 → validation negative → 안전 거부. (V1 유지)
**출력**: 거부 안내, `END_WAIT_USER`.

---

# 2. [V2·신규] — V1에 없던 것

## SC-01 · 모호 입력 + 기존 프로필  `[V2·신규]`
**검증 결정**: D-K(모호입력 profile fallback) · X3 · soft 게이트
**Given**
```
themes=[], tripType=2d1n, travelMonth=10, NL="그냥 요즘 나한테 맞는 데로 한 곳"
Profile(ab12): {healing_rest:0.5, nature_mountain:0.3, sea_coast:0.2}, trip_count=3
```
**흐름(분기 = D-K)**: Profile read →
- (A) profile fallback: active_themes=[healing_rest, nature_mountain] → 정상 생성, reason="이전에 즐겨 찾던 힐링·자연 위주".
- (B) 되묻기: needs_clarification → END_WAIT.
**출력**: (A) 정상 일정 / (B) 질문. **결정 D-K: 모호+profile → 채울지 물을지.**

## SC-02 · 날씨 Plan B 동반 생성  `[V2·신규]` ⚠️
**검증 결정**: D-A(출력 스키마) · D-J(임계)
**Given**
```
themes=[nature_mountain, sea_coast], tripType=2d1n, travelMonth=7, NL="강원도 바다랑 산"
Profile: 없음(균등)
```
**흐름**: city_select → 도시 확정(예: 삼척)+seed → Planner: primary 생성 → 7월 강수 ≈ 12mm/day(strong) → **야외 슬롯→실내 대안 전체 Plan B 생성** → Packager.
**출력 — 결정 D-A**:
- (a) `itinerary` + **`alternativeItinerary`(Plan B)** + userNotice → **출력 스키마 변경**.
- (b) primary만 + userNotice("비 오면 실내로 바꿔드릴게요"), Plan B는 수정 루프에서만.

## SC-N1 · 이동수단 거친 구분  `[V2·신규]`
**검증 결정**: D-E(transport_pref) · 동선
**Given**
```
themes=[sea_coast], tripType=daytrip, travelMonth=8, NL="차 없이 뚜벅이로 다니기 좋게"
```
**흐름**: Intent → `transport_pref=walk`(거친 신호) → city_select(기존) → Planner: **도보 집약 동선**(슬롯 간 거리 더 강하게 페널티) → Packager.
**출력**: 도보 집약 일정. *(차량중심이면 거리 페널티 완화)* **결정 D-E: 신호 정의·반영 강도.**

## SC-N2 · 모순/긴서사 입력  `[V2·신규(고도화)]`
**검증 결정**: 되묻기 경계 · soft 추출
**Given**: NL="활동적인 숲 트래킹 원하는데 몸 움직이긴 싫어 실내만" (모순) / "회사도 힘들고 외롭고… 바다는 보고싶고 춥긴 싫고" (긴서사).
**흐름**: Intent → 모순 감지 → (창의 절충: 실내서 숲 조망 / 핵심 키워드 추출 "바다·따뜻") 또는 needs_clarification. → 생성 or END_WAIT.
**출력**: 절충 일정 또는 되묻기.

## SC-03 · 수정: 장소 교체(+조건)  `[V2·신규]`
**검증 결정**: M1 · S3 재인출 · 응답상태 · D-K(누적?)
**Given**: (checkpoint) 강릉 2d1n, 2일차 오후=○○카페. 발화="2일차 오후 바다 보이는 조용한 데로".
**흐름**: resume → Intent(modify: 대상=2일차 오후, REPLACE, soft="바다·조용") → Planner(비-seed 슬롯만 재인출: S3 캐시 vector+top_k, city 고정, +seed 거리·타입 균형) → Packager(갱신+interrupt, status=수정대기).
**출력**: 2일차 오후만 교체. **결정: 수정 신호 profile 누적 여부(D-K).**

## SC-M1 · 수정: 도시 변경  `[V2·신규]`
**검증 결정**: 수정 범위(확장) · city_select 재실행
**Given**: (checkpoint) 강릉 일정. 발화="강릉 말고 속초로 바꿔줘".
**흐름**: resume → Intent(modify: 도시 변경) → S → **city_select 전체 재실행**(query_vector 재사용, 도시=속초/재선정) → (FestivalVerifier) → Planner → Packager(재생성+interrupt).
**출력**: 속초 일정. 수정 중 **유일하게 city_select까지 거슬러 올라감**.

## SC-M2 · 수정: 무드/길이/날짜 변경  `[V2·신규]`
**검증 결정**: 수정 범위 · trip_type/4d3n · 의미적 변경
**Given**: 발화 예: "좀 더 생기 있게"(무드) / "1박2일로 줄여"(길이) / "10월로"(날짜).
**흐름**:
- 무드 → Intent(새 의미, 새 embedding 가능) → 비-seed 재인출·재배치.
- 길이 → 골격 재생성(trip_type 변경; **4d3n이면 미검증** → 정책).
- 날짜 → travel_month 변경 → 축제·기상 재반영.
**출력**: 변경 반영 일정. **결정: 의미적 변경 처리 범위 · 4d3n 정책.**

## SC-M3 · 수정: 맥락 변화 후 재요청  `[V2·신규]`
**검증 결정**: 멀티턴 컨텍스트 · D-9(조건 적용 범위)
**Given**: 1턴 "혼자 힐링" → 일정. 2턴 "친구랑 가게 됐어, 더 활발하게".
**흐름**: resume → Intent(동행·무드 변화 감지) → 재배치(활발 쪽). 누적 조건 vs 슬롯 일시(D-9).
**출력**: 활발해진 일정. **결정: 변경 신호의 세션 누적 범위.**

## SC-M4 · 수정: 전면 리셋  `[V2·신규]`
**검증 결정**: 기피 재생성
**Given**: 발화="다 별로야, 완전 다른 도시로".
**흐름**: resume → Intent(전면 불만) → 기존 도시·테마 **기피(avoid) 설정** → city_select 재실행(차순위) → 재생성.
**출력**: 다른 도시 새 일정.

---

# 3. 이 문서가 거는 결정 (요약 → Step 4)
- ⚠️ **D-A 출력 스키마**(SC-02) — Plan B 노출 방식. **선결.**
- **D-B 수정 처리 범위 / 1차 vs 백로그**(SC-03·M1·M2·M3).
- **D-K profile write·모호 fallback**(SC-01·03·M3).
- **D-C 동선/move**(SC-00·G1·N1), **D-E transport_pref**(N1), **D-J 날씨 임계**(02), **4d3n 정책**(M2), **응답상태 확장**(03·M*).
- (이미 확정) 테마 게이트 soft(G1·R3) · capacity 제거 · 재인출 S3 Vector(03).
