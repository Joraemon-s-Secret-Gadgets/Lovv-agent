# V2 Intent 파싱 기준 (확정 명세)

> 작성일 2026-06-28 · 근거: `V2_DECISIONS_LOG.md`(Step 4) · `V2_04_SCENARIO_CONCRETE.md` · `V2_07_ARCHITECTURE_FINAL.md`.
> 목적: Intent가 **어디까지 / 어떻게** 파싱하는지를 확정 기준으로 고정. 초기 생성과 수정(resume)을 분리하고, 공통/생성전용/수정전용을 가른다.
> 표기: ✅ 확정 · ⚠ 경계 확인 필요(임의로 정하지 않음).

---

## 0. 원칙 — Intent는 어디서 멈추나

**Intent = "원시 입력 → 타입된 파싱·검증 객체"까지. 그 이상은 안 한다.**

Intent는 사용자 입력(구조 필드 + 자연어)을 받아 **무엇을 원하는지 구조화하고, 처리 불가/모호/모순을 플래그**하는 데서 끝난다. **검색·스코어·도시 선택·배치·프로필 fallback 결정은 다운스트림**(retrieval/scoring/Planner/Profile)의 몫이다.

| Intent가 한다 | Intent가 안 한다 (다운스트림) |
|---|---|
| 구조 필드 정규화·검증 | S3 Vector 검색 / 임베딩 매칭 |
| `execution_mode` 도출 | 도시 스코어링·선택 (scoring_and_selection) |
| NL → soft 신호 추출(분위기·혼잡도·이동수단) | 장소 배치·동선 (Planner) |
| 모순/모호/범위밖/안전 **플래그** | 모호 입력을 채울지 결정 (Profile fallback) |
| 수정 의도 분류 + `edit_ops` 분해 | 슬롯 재인출·재배치 (Planner 수정 모드) |
| raw/soft **쿼리 텍스트** 산출 | ⚠ 쿼리 임베딩 생성 — retrieval_node 책임으로 둠(경계 확인) |

> 핵심: Intent는 **판정하지 않고 표식만 단다**. 예) 모호 입력에 대해 Intent는 `underspecified=true`만 세팅하고, "프로필로 채울지 되묻을지"는 Profile/Supervisor가 D-K로 결정한다.

산출물 두 종류 — 초회는 `IntentResult(생성)`, resume은 `ModifyResult(수정)`. 분기 라우팅은 Supervisor가 thread/checkpoint 유무로 하되, **어느 분기인지의 1차 판별과 내용 파싱은 Intent**가 한다.

---

## 1. 초기 생성 파싱 (IntentResult)

### 1.1 구조 필드 정규화·검증 ✅
입력 필드: `themes · tripType · travelMonth · destinationId · includeFestivals · country · userLocation · NL`.

| 필드 | 허용/정규화 | 결측·이상 처리 |
|---|---|---|
| `themes` | 5종 enum(sea_coast·nature_trekking·history_tradition·art_sense·healing_rest) 부분집합 → canonical 한글 라벨(바다·해안/자연·트레킹/역사·전통/예술·감성/온천·휴양)로 정규화 | 빈 배열 → `underspecified` 플래그(되묻기/ fallback 후보) |
| `tripType` | daytrip·2d1n·3d2n·(4d3n+ = 한계 고지 대상) | 결측 → 기본값 ⚠(정책 확인) |
| `travelMonth` | 1–12 정수 | 범위 밖(13월 등) → `reject{invalid_value}` |
| `destinationId` | 강원·경북 도시 id | 범위 밖 지명(제주/강남역) → `out_of_scope{region}` |
| `includeFestivals` | bool | 결측 → false |
| `country` | KR 고정 | KR 외 → `out_of_scope{region}` |
| `userLocation` | 좌표(즉흥·거리 계산용) | 결측 허용 |
| `NL` | 자유 텍스트 | §1.3에서 파싱 |

### 1.2 execution_mode 도출 (결정 트리) ✅
> 순서 고정. 위에서 먼저 매칭되는 것 채택.
1. `destinationId != null` → **`anchored_place_search`** (검색 풀 = 그 도시 고정)
2. `destinationId == null && includeFestivals == true` → **`festival_seeded_city_discovery`**
3. else → **`city_discovery`**

`source = map_marker`인데 `destinationId == null` → §1.4 안전 거부.

### 1.3 NL 파싱 — 여기까지만 ✅
NL에서 뽑는 것은 **검색·배치를 거들 soft 신호**까지. 의미 판단은 안 한다.
- **raw_query**: NL 핵심 명사구(검색용 원문 쿼리 텍스트).
- **soft_query**: 분위기·감정 신호("조용", "생기 있게", "멍때릴") → soft 검색·가중용.
- **congestion_pref**: 한적/북적 선호("사람 적은", "북적북적") → scoring의 congestion 가중 힌트.
- **transport_pref**: `walk / car / unknown` (D-E, "뚜벅이"·"차로") — 거친 soft 신호. 역·터미널 라우팅 아님.
- **theme_hint**: NL이 암시하는 테마(명시 `themes`가 있으면 그게 우선, NL은 보강만).
- **긴 서사**: 별도 모드 아님 — 위 신호 추출 앞에 **의미 압축 1단계**만 추가하고, 결과는 동일한 raw/soft_query로 귀결. 3단계로 처리(아래 §1.3.1).

> 산출은 **텍스트/enum 수준**. 임베딩 벡터화는 retrieval_node에서(⚠ 경계 확인 — V1 query_vector 생성 위치).

#### 1.3.1 긴 서사 처리 — 정확한 정의 ✅
감정 토로·맥락 설명이 많이 섞인 긴 입력. **별도 경로가 아니라 §1.3 추출 앞단의 압축**이며, 산출물은 동일한 raw/soft_query다.

**1단계 — 분리**: 발화를 의미 조각으로 쪼개 4종 분류 — ① 명시 대상(장소·활동 명사) ② 감정·상태 ③ 부정 제약 ④ 순수 배경/토로.

**2단계 — 매핑(보수적)**: 조각 종류별로 신호 강도를 다르게 준다. **핵심 규칙: 감정으로 테마를 단정하지 않는다**(감정 → 무드·혼잡도 soft까지만, 테마는 명시 대상이 있을 때만).

| 조각 | 예 | 매핑 | 강도 |
|---|---|---|---|
| 명시 대상 | "바다" | `theme_hint=[sea_coast]` | 강(검색 대상) |
| 감정·상태 | "힘들고 외롭고" | mood=위로·조용 · `congestion_pref`=낮음 | 약(가중만) |
| 부정 제약 | "추운 건 싫어" | soft negative(따뜻 선호) | 약(감점, 하드필터 아님) |
| 순수 토로 | "회사가 힘들어" | 폐기 또는 mood 톤에만 | — |

**3단계 — 정합 확인**: ① 추출 신호 상충 → `contradiction` → 되묻기. ② actionable 신호 0(순수 토로뿐) → `underspecified` → fallback/되묻기(테마 단정 금지).

**예시**: "회사도 힘들고 사람한테 치여 외로운데, 바다는 꼭 보고싶고 추운 건 싫어"
→ `raw_query="바다"` · `theme_hint=[sea_coast]` · `soft_query="조용·위로·한적·따뜻"` · `congestion_pref=low` · 모순 없음 → 정상 생성.
**반례**: "그냥 요새 다 싫고 어디든 떠나고 싶어" → 명시 대상 0 → `underspecified`(테마 단정 안 함).

> 구현: 규칙이 아니라 **LLM 의미 압축**(Bedrock Converse). 검증은 judge로 **핵심 보존 + 과해석 0**(없는 테마 false-add = 0 목표). 긴서사·모호·모순은 동시 발생 가능하며 위 3단계가 순서대로 거른다.

### 1.4 검증·분기 플래그 (판정 아님, 표식) ✅
| 상황 | 예시 | Intent 산출 | 다음 행동(다운스트림) |
|---|---|---|---|
| 모순 | "조용한데 사람 많은 데" | `contradiction=true` | **무조건 되묻기** `needs_clarification` (창의 절충 안 함, 확정) |
| 모호 | "나한테 맞는 데로" | `underspecified=true` | Profile fallback or 되묻기 (D-K가 결정) |
| 범위 밖(지역) | "제주/일본/강남역" | `out_of_scope{region}` | 강원·경북 한정 재질의 |
| 범위 밖(기능) | "숙소 잡아줘"·"예약"·"실시간 혼잡" | `out_of_scope{feature}` | graceful 안내(기능 구현 X) |
| 이상값 | "영하 100도"·"9999년 13월" | `reject{invalid_value}` | 안전 정정 안내 |
| 필수 누락 | map_marker인데 도시 없음 | `reject{missing_field}` | 안전 거부 `END_WAIT_USER` |

---

## 2. 수정 파싱 (ModifyResult · resume)

전제: checkpoint 존재(thread_id). 입력은 NL 중심.
> ModifyResult 형식화 + **수정 처리·응답 출력 스키마 정본 = `V2_11_MODIFY_IO_CONTRACT.md`**. 본 절은 Intent 파싱 관점만.

### 2.1 수정 의도 분류 ✅ (1차 / 경로만 / 백로그)
| 분류 | 발화 예 | 1차 처리 여부 |
|---|---|---|
| **슬롯 교체(+조건)** | "2일차 오후 바다 보이는 데로" | ✅ V2.0 핵심 |
| **다건 슬롯 교체** | "2일차는 카페, 3일차는 바다로" | ✅ V2.0 (§2.2) |
| **전면 리셋** | "다 별로야, 다른 도시로" | ✅ 세션 avoid 재생성 |
| **날씨 동의** | (weatherNotice에) "응 실내로" | ✅ on-demand Plan B 트리거 |
| **발견감 강화** | "더 안 알려진 곳으로" | ✅ (대중지→숨은 후보) |
| **도시 변경** | "속초로 바꿔" | 🟡 경로만 설계(V2.1) |
| **무드/길이/날짜/맥락** | "쉬엄쉬엄"·"1박2일로"·"10월로"·"친구랑 가게 됨" | ⛔ 백로그 → `userNotice` 한계 고지 |

### 2.2 edit_ops 분해 (다건·배치) ✅
한 입력의 복수 편집을 op 리스트로 분해한다.
```
edit_ops: [
  { target: {day, time_slot}, op: REPLACE, condition: {mood?, place_type?, location?} },
  ...
]
```
- **op = REPLACE만**(1차). 추가/삭제로 배치 개수(≤3) 변경 안 함.
- **condition** = 슬롯에 거는 추가 query(무드·타입·위치) — 전체 재구성이 아니라 그 슬롯 한정.
- **seed 보호**: target이 seed 슬롯이면 → 교체 거부 + 안내(seed는 도시 선택 이유라 고정).
- **모순 처리**: 같은 슬롯에 상충 조건, 또는 op 간 모순 → 전체 멈추고 `needs_clarification`(§1.4 모순 정책과 동일).

### 2.3 특수 수정 신호 ✅
- **reset**: `reset{avoid: [city|theme]}` → 세션 avoid 설정(TTL까지 유지, 영구 profile 아님).
- **confirm_plan_b**: weatherNotice 후 동의 → 실내 대안 생성 트리거.
- **change_city**: `change_city{target?}` → 유일하게 city_select 되감기 경로(V2.1).

### 2.4 백로그 의도 처리 ✅
무드/길이/날짜/맥락 변화는 인식은 하되 **실행 대신 `userNotice`로 한계를 고지**("지금은 슬롯 단위 교체만 가능해요"). 인식조차 못 하면 안 됨 — graceful이 핵심.

---

## 3. 공통 / 생성 전용 / 수정 전용

| 파싱 항목 | 공통 | 생성 전용 | 수정 전용 |
|---|---|---|---|
| 모순 감지 → 되묻기 | ● | | |
| 범위 밖(지역·기능) 인식 → 안내 | ● | | |
| 안전/이상값/필수누락 → 거부 | ● | | |
| NL soft 신호(soft_query·congestion·무드) | ● | | |
| theme_hint 추출 | ● | | |
| 긴 서사 키워드 압축 | ● | | |
| 구조 필드 정규화(themes·tripType·month…) | | ● | |
| `execution_mode` 도출 | | ● | |
| `includeFestivals` / `destinationId` 처리 | | ● | |
| 모호 입력 → `underspecified` 플래그(fallback 후보) | | ● | |
| `transport_pref` 추출 | ◐ 추출은 공통 | 적용 ● | ⚠ 수정 적용은 백로그(무드 전환) |
| 수정 의도 분류 | | | ● |
| `edit_ops` 분해(다건) | | | ● |
| seed 슬롯 보호 | | | ● |
| `reset`/avoid · `confirm_plan_b` · `change_city` | | | ● |

> 읽는 법: **공통 = 입력이 생성이든 수정이든 똑같이 도는 안전·해석 레이어**(모순·범위밖·soft 추출). **생성 전용 = "처음부터 무엇을 만들지"**(필드·mode·모호). **수정 전용 = "기존 결과를 어떻게 바꿀지"**(edit_ops·seed 보호·특수 신호).
> `transport_pref`는 추출 자체는 공통이지만, 수정에서 "차로 다니게 바꿔"는 무드 전환 = 백로그라 **수정 적용은 제한**한다.

---

## 부록 A. 검증 방법 (어떤 항목을, 어떻게)

검증 유형 4종으로 나눈다.
- **(U) 단위·결정론**: 입력→출력이 규칙으로 고정. 100% 일치 기대.
- **(G) 라벨셋/골든셋**: 분류·추출 품질. confusion matrix, precision/recall.
- **(J) LLM-judge + 휴먼 스팟체크**: 의미 추출의 정성 품질.
- **(R) 회귀**: V1 입력 코퍼스 재생으로 동치/개선 확인.

| 항목 | 유형 | 방법 | 합격 기준(초안) | 오류 방향 비용 |
|---|---|---|---|---|
| `execution_mode` 도출 | U | 입력 조합 표 → 기대 mode 단위테스트 | 100% | 오도출 시 경로 통째로 틀림 → **0 허용** |
| 구조 필드 정규화·경계값 | U | 13월·영하100도·빈 themes·KR외 등 경계 케이스 | 100% | 안전 직결 |
| `edit_ops` 분해(구조) | U+G | 발화→기대 ops 골든셋. slot-level **exact match / F1** | exact ≥ 0.9 | 슬롯 오지정 = 엉뚱한 곳 교체 |
| seed 슬롯 보호 | U | seed 지정 발화 → reject/안내 단위테스트 | 100% | seed 깨지면 일정 정체성 붕괴 |
| 안전 거부/필수 누락 | U | map_marker+무 도시 등 | 100% | 안전 |
| **모순 감지** | G | 모순/비모순 라벨셋, confusion matrix | **recall(모순) ≥ 0.95** 우선 | **false negative(모순 통과)** = 엉뚱 생성 → recall 우선 |
| 모호 감지 | G | 모호/충분 라벨셋 | precision·recall ≥ 0.85 | false positive = 멀쩡한데 되묻기(UX 마찰) |
| 범위밖 인식(지역·기능) | G | 숙소·예약·제주·강남역… 라벨셋 | **recall ≥ 0.95** 우선 | miss → 못 하는 걸 시도/헛생성 |
| 수정 의도 분류 | G | 슬롯교체/도시변경/리셋/plan_b/백로그 라벨셋, confusion matrix | macro-F1 ≥ 0.85 | 백로그를 슬롯교체로 오인 → 잘못 실행 |
| `transport_pref` 3-class | G | walk/car/unknown 라벨셋 | accuracy ≥ 0.85 | 약신호라 비용 낮음 |
| soft_query·무드 추출 | J | LLM-judge 적합성 + 휴먼 스팟체크(주 N건) | judge 평균 ≥ 4/5 | 정성, 회귀 모니터 |
| 긴서사 키워드 압축 | J | 원문 핵심 보존율 judge | 핵심 누락 0 목표 | 정보 손실 |
| 전체 파싱 회귀 | R | V1 입력 코퍼스 재생 → 파싱 diff | 의도된 변경 외 0 회귀 | 무회귀 보장 |

**우선순위 한 줄**: 비용이 큰 쪽부터 — **모순·범위밖은 recall 우선(놓치면 헛생성)**, `execution_mode`·seed 보호·안전은 **0 허용 결정론**. soft/무드는 정성이라 judge+스팟체크로 흐름만 감시.

### 검증 데이터 소싱
- 라벨셋: `V2_04_SCENARIO_CONCRETE.md`의 SC-* 발화를 시드로, 변형 증강(같은 의도 다른 표현). 모순·범위밖은 **부정 예시를 의도적으로** 채운다.
- 회귀: V1 트래픽/덤프 입력(가능 범위) 재생.

---

## 부록 B. 열린 경계(임의로 안 정함 — 확인 필요)
- ⚠ **쿼리 임베딩 생성 위치**: Intent(텍스트까지) vs retrieval_node(벡터화). 본 명세는 retrieval로 가정.
- ⚠ **tripType 결측 기본값**: 되묻기 vs 기본 2d1n.
- ⚠ **transport_pref 수정 적용**: 현재 백로그. V2.1에서 무드 전환과 함께 열지 여부.
