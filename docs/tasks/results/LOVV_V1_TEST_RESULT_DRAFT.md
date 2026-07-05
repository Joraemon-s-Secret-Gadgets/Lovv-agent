# LovvAgentV1 테스트 결과서 (Draft / 기능 검증분)

> 작성일: 2026-06-27
> 근거 계획: `docs/tasks/results/LOVV_V1_TEST_PLAN.md`
> 입력 세트: `docs/tasks/results/test_cases/` 20개 fixture
> 수집: 경로 1 — 로컬 live harness (`capture_e2e_state.py --live --profile skn26_final`), 덤프 `test_cases/results/` 20건 (생성 2026-06-27T01:51~01:55Z)
> 상태: **초안 — 기능(파이프라인 실행·구조 정합·가드레일)만 확정.** 추천 품질·데이터 스코프·혼잡도는 §6에서 보류.

---

## 0. 이 결과서가 보증하는 것 / 보증하지 않는 것

이 라운드는 **경로 1(로컬 in-process + 실제 AWS 데이터 서비스)** 만으로 수집했다. 따라서:

- **보증함(§3~§5):** LangGraph 각 노드가 실행되고, structured output을 스키마대로 반환하며, 제어 흐름(라우팅·fallback·validation·마스킹)이 설계대로 동작한다. **이는 벡터 인덱스의 데이터 스코프와 무관한, 코드/메커니즘의 성질이다.**
- **보증하지 않음(§6):** 출력된 추천이 *옳은* 추천인지(품질), 도시 분포(편중), 혼잡도(congestion) 반영, "강원/경북 한정" 전제, 축제 발견 성공. **이들은 데이터 스코프에 종속**되며, 현재 발견된 스코프 불일치(§6 D-SCOPE) 때문에 별도 재검증이 필요하다.

> 한 줄 경계: **기능 PASS = "각 단계가 실행되고 구조·흐름이 옳다"까지다. "추천이 옳다"는 보증하지 않는다.**

비기능(NF/OB — latency·토큰·트레이스)은 경로 2(배포 invoke→트레이스)에서만 측정되며 이 라운드 범위 밖이다.

---

## 1. 요약 판정

| 영역 | 판정 | 근거 |
|------|------|------|
| 기능 정상 경로 (§3.A) | **PASS** | 20건 중 정상 14건 전부 status=ok, 단계별 산출 정상 |
| Fallback·입력검증 (§3.B) | **PASS** | no_candidate 3건·insufficient 2건·validation 거부 1건 모두 graceful |
| 스키마 계약 (§3.E) | **PASS** | CE/Planner/응답 필수 필드 100% 존재, 다운스트림 크래시 0 |
| 그라운딩·안전 (§3.F) | **PASS** | reason이 검색 장소 설명에 그라운딩, 숙소 직접추천 없음, 국가 혼합 없음 |
| 크래시/에러율 | **PASS** | 20건 status=error 0, malformed JSON 0 |
| 추천 품질·스코프·혼잡도 | **보류(HOLD)** | §6 — 데이터 스코프 불일치 해소 후 재검증 |

---

## 2. 케이스 인덱스 및 실행 결과

| # | fixture | 진입 | 테마 | trip | 상태 | 선택 도시 | 후보 도시 수 |
|---|---------|------|------|------|------|-----------|------|
| 01 | coast_quiet_2d1n | chat | 바다·해안 | 2d1n | ok | 양양군 | 8 |
| 02 | coast_vibrant_2d1n | chat | 바다·해안 | 2d1n | ok | 양양군 | 8 |
| 03 | nature_quiet_2d1n | chat | 자연 | 2d1n | ok | 원주시 | 20 |
| 04 | nature_vibrant_2d1n | chat | 자연 | 2d1n | **insufficient_candidates** | 포항시 | 31 |
| 05 | history_2d1n | chat | 역사 | 2d1n | ok | 안동시 | 22 |
| 06 | art_2d1n | chat | 예술 | 2d1n | ok | 강릉시 | 24 |
| 07 | healing_2d1n | chat | 힐링 | 2d1n | **insufficient_candidates** | 원주시 | 28 |
| 08 | nature_coast_3d2n | chat | 자연+해안 | 3d2n | ok | 영덕군 | 8 |
| 09 | history_nature_2d1n_seoul | chat | 역사+자연 | 2d1n | ok | 안동시 | 15 |
| 10 | coast_healing_daytrip_daegu | chat | 해안+힐링 | daytrip | ok | 영덕군 | 7 |
| 11 | home_nature_healing_3d2n | home | 자연+힐링 | 3d2n | ok | 양양군 | 13 |
| 12 | history_festival_2d1n | chat | 역사 | 2d1n | **no_candidate** (no_festival_city_seed) | — | 0 |
| 13 | sea_festival_2d1n | chat | 바다·해안 | 2d1n | **no_candidate** (no_festival_city_seed) | — | 0 |
| 14 | mapmarker_history_festival_daytrip | map_marker(경주) | 역사 | daytrip | ok | 경주시 | 1 |
| 15 | wrapped_agentcore_history_art_2d1n | agentcore wrap | 역사+예술 | 2d1n | ok | 경주시 | 17 |
| 16 | wrapped_http_nature_festival_daytrip | http body | 자연 | daytrip | **no_candidate** (no_festival_city_seed) | — | 0 |
| 17 | rare_combo_art_healing_clarify | chat | 예술+힐링 | 2d1n | ok | 인제군 | 20 |
| 18 | invalid_mapmarker_missing_destination | map_marker | 바다·해안 | daytrip | **invalid** (destinationId 누락 거부) | — | N/A |
| 19 | intent_short_query | chat | 바다·해안 | daytrip | ok | 동해시 | 11 |
| 20 | intent_long_complex_query | chat | 자연+해안+역사 | 3d2n | ok | 동해시 | 7 |

상태 분포: **ok 14 · insufficient_candidates 2 · no_candidate 3 · invalid 1.** 크래시 0.

후보 도시 수: min 1(14, 앵커) / median 14 / max 31(04). 단일 광범위 테마(03·04·05·06·07)는 풀이 크고, 해안·다중테마(01·02·08·10·20)는 지리적으로 작다.

---

## 3. 기능 검증 결과 (계획 §3 매핑)

### 3.A 정상 경로

| TC | 검증 기준 | 결과 | 증빙 |
|----|-----------|------|------|
| FN-02 Intent structured output | Converse 호출·파싱·mode 기록 | **PASS** | 17건 `intent_mode=bedrock_structured_output`, 19 `deterministic_short_query`, 14 `deterministic_llm_fallback` — 3경로 모두 동작 |
| FN-03 도시 발견 정상 | status=ok, selected_city, places≥3 | **PASS** | 정상 14건 모두 충족 (01: 양양, 후보 8, primary 11) |
| FN-04 축제 시드 모드 | 시드 조회 실행·CE 패키지 처리 | **부분 / 보류** | 시드 조회 노드는 실행되나 시드 0 반환 → no_candidate(12·13·16). 메커니즘 PASS, 발견 성공은 §6 D-FEST |
| FN-05 Planner 일정 생성 | 일정 항목·validation passed | **PASS** | 01 itinerary 5슬롯, `validation_result.status=valid`, `checked_item_count=5` |
| FN-06 Planner copy 생성 | reason 텍스트 생성 | **PASS** | 01 reason 3건 생성. `planner_copy_generation_used_llm=false`(grounded builder 경로), 내부어 누출 0 |
| FN-07 Supervisor 라우팅 | visited_nodes = 설계 순서 | **PASS** | 01: intent→supervisor→candidate→supervisor→planner→supervisor→packager |
| FN-08 응답 마스킹 | 내부 필드 미노출 | **PASS** | `candidate_reason_claims`(내부, state L841)가 공개 응답(L1375 recommendationReasons)에 미포함 |
| FN-09 E2E 응답 스키마 | 응답 계약 필드 완전 | **PASS** | selectedDestination·itinerary·recommendationReasons·confidence·links·userNotice 존재 |
| FN-입력추출 wrapper 파싱 | AgentCore/HTTP wrapper 정규화 | **PASS** | 15(agentcore wrap)·16(http body) payload 추출 정상 |
| FN-거리 distance 감점 | userLocation 있을 때 penalty>0 | **PASS** | 09(서울): 안동 0.0966·경주 0.1406, 10(대구)·20(서울) 반영 |

### 3.B Fallback / 입력검증

| TC | 검증 기준 | 결과 | 증빙 |
|----|-----------|------|------|
| FB-03 no-candidate | needs_clarification 또는 빈 itinerary, 신호 기록 | **PASS(경로)** | 12·13·16 `status=no_candidate`, `no_festival_city_seed`, needs_clarification=true. (희소 조합 17은 인제 발견 → 정상 처리) |
| FB-05 insufficient candidates | 축소·상태 기록 | **PASS** | 04·07 `status=insufficient_candidates` — 도시 풀은 크나(31·28) 선택 도시 장소 밀도 부족, 안전 강등 |
| FB-검증 validation negative | 안전 거부·에러 미전파 | **PASS** | 18 map_marker+destinationId 누락 → 패키지 null, 거부, needs_clarification=true, 크래시 없음 |

### 3.E 스키마 계약

| TC | 결과 | 증빙 |
|----|------|------|
| SC-CE CE 패키지 | **PASS** | 01 `status`·`selected_city`·`recommended_places`·`failure_signals` 존재 |
| SC-PLAN Planner 출력 | **PASS** | `itinerary`·`recommendationReasons`·`confidence`·`validation_result` 존재 |
| SC-FEST 축제 검증 | **PASS(공백 정상)** | 비축제 케이스 `festival_verifications=[]`, gate 정상 |
| SC-API 응답 | **PASS** | `selectedDestination`·`itinerary`·`confidence`·`links` 완전 |

### 3.F 그라운딩 · 안전

| TC | 결과 | 증빙 |
|----|------|------|
| SF-GROUND 설명 그라운딩 | **PASS** | 01 recommendationReasons 3건 모두 검색 장소 description 인용("…배치된 대표 장소 설명도 '…'로 확인됩니다"), `evidence_refs`로 place id 연결. 환각 없음 |
| SF-FEST 미확정 축제 배치 금지 | **PASS(해당없음)** | 비축제 케이스 `festival_placed_count=0` |
| SF-ACCOM 숙소 직접추천 금지 | **PASS** | 01 `links.staySearch`는 검색 링크(google search), 호텔명·예약정보 생성 없음 |
| SF-COUNTRY 국가 혼합 금지 | **PASS** | 전 케이스 KR 단일, 지도·검색 링크 KR 일관 |

---

## 4. 판정 기준 대비

| 기준 (계획 §4) | Pass 조건 | 결과 |
|------|-----------|------|
| 기능 정상 경로 | §3.A 전 TC Pass | **PASS** (FN-04만 데이터 의존 부분 보류) |
| Fallback·입력검증 | §3.B 의도된 fallback·격리 | **PASS** |
| 스키마 계약 | 필수 필드 100% | **PASS** |
| 그라운딩·안전 | 위반 0 | **PASS** |
| 에러율 | 정상 시나리오 status=error 0 | **PASS** (error 0건) |

> LLM 노드(FN-02·06) Pass는 **구조·존재 검사**다(파싱 성공·필드 존재). 내용 품질은 §6.

---

## 5. 노드별 실행 상세 — 대표 케이스 01 (coast_quiet_2d1n)

계획 §6 기록 항목을 한 케이스로 완전 추적한 예시.

**요청 Payload:** entryType=chat, themes=[sea_coast], tripType=2d1n, travelMonth=7, includeFestivals=false, userLocation=null, NL="바다 풍경을 천천히 보며 해안 산책로를 걷고 싶어요. 사람이 적고 조용하고 한적한 바닷가 마을이면 좋겠어요."

**① Intent** (`intent_mode=bedrock_structured_output`)
- `cleaned_raw_query`(enrich): "바다 풍경을 천천히 보며 해안 산책로를 걷고 싶다. 사람이 적고 조용하고 한적한 바닷가 마을을 원한다."
- `soft_preference_query`: "조용하고 한적한 분위기" (분위기만 정제 — 누출 없음)
- `active_required_themes`: ["바다·해안"], `unsupported_conditions`: [], `execution_mode`: city_discovery

**② Supervisor → ③ Candidate Evidence** (`status=ok`, `execution_mode=city_discovery`)
- 후보 도시 8 (점수순): 양양·강릉·삼척·영덕·고성·동해·울릉·속초
- `selected_city`: KR-Yangyang, `selected_city_rank`: 1
- primary 11 / reserve 다수, `recommended_places` 충족
- city score(양양) breakdown: semantic 0.6878, theme_coverage 1.0, theme_balance 1.0, scale_correction 0.0480, candidate_sufficiency 0.1, distance_penalty 0.0, congestion_penalty 0.175(=0.5×0.35 — **혼잡도 중립 기본값, §6 D-CONG**)

**④ Festival Verifier:** `festival_verifications=[]` (비축제, skip 정상)

**⑤ Planner** (`validation_result.status=valid`, `checked_item_count=5`)
- itinerary day1: 잔교리해변(morning) → 죽도정·죽도 전망대(afternoon) → 설악해변(evening) … (5슬롯)
- `itineraryFlowReason`: "관광지 5곳을 tripType 기본 시간대에 맞춰 간결하게 배치했습니다."
- `planner_copy_generation_used_llm=false` (grounded 경로), `food_search_link_required=true`

**⑥ Supervisor:** `fulfilled_matrix={evidence:O, festival:N/A, planning:O}`, `validation_retry_count=0`

**⑦ Response Packager** (`response_status=completed`, `confidence=0.72`)
- `recommendationReasons`(공개) 3건 — 전부 장소 설명에 그라운딩:
  - "잔교리해변은 사람의 발길이 적고 고요한 풍경을 제공해 조용한 해안 산책을 즐기기에 적합합니다. 배치된 대표 장소 설명도 '38선 휴게소에서 남쪽으로 1km…'로 확인됩니다."
- `matchedConditions`: [sea_coast, travelMonth:7], `unsupportedConditions`: []
- `links`: map/staySearch/foodSearch (검색 링크), `userNotice`: ""
- **마스킹 확인:** 내부 `candidate_reason_claims`는 공개 응답에 미포함

> 나머지 19건의 노드별 슬라이스는 `test_cases/results/`의 각 덤프에서 동일 항목으로 추출 가능.

---

## 6. 보류 항목 — 데이터 스코프 종속 (재검증 필요)

이 라운드 수집 중 발견된, **기능과 분리되는 데이터/스코프 결함.** 결과서의 품질·비기능 섹션은 이 해소 후 작성한다.

### D-SCOPE (상) — S3 Vector ↔ DynamoDB 스코프 불일치
- 검색 필터(`build_attraction_filter`)에 **지역 제약 없음**. 그런데 20개 덤프 전체에 강원/경북 외 도시 **0건**(grep 확인).
- DynamoDB는 전국 확장 적재됨(운영 확인). → **S3 Vector 인덱스가 전국으로 재임베딩되지 않았거나, 덤프가 확장 이전 상태**. 어느 쪽이든 현재 덤프는 의도된 전국 스코프를 대표하지 못함.
- **영향:** 추천 품질·도시 분포·"강원경북 한정" 전제 모두 이 해소 전까지 무효.
- **다음:** 케이스 01·03 live 재실행으로 (a) 타지역 도시 등장 여부 (b) congestion_index 분산 여부 동시 확인 → stale vs desync 확정.

### D-CONG (중→상) — 혼잡도 신호 비활성
- 20케이스 전 도시 `congestion_index=0.5`(코드상 "통계 없음→중립 기본값"). congestion_penalty가 전부 `0.5×w_cong`로 동일 → 순위에서 상쇄, **혼잡도 변별력 0**.
- visitor stats 조회가 빈손 반환. 원인: 전국 재적재 과정의 **키/SK/속성 미스매치 또는 미적재**(D-SCOPE와 동근).
- 단, **quiet/vibrant 의도 자체는 임베딩 경로로 부분 작동**: 01(soft "조용하고 한적한")↔02("활기찬…핫플")의 cleaned/soft가 정상 분기 → semantic_evidence에 반영(02에서 강릉이 양양에 0.006까지 근접). congestion은 이를 *강화*하는 보조 신호이며 0→1이 아니라 보강 대상.

### D-FEST (중) — 축제 시드 발견 전무
- 12·13·16(축제 시드 모드) 모두 시드 0 → no_candidate. 가드레일은 정상 발화하나 **발견 기능은 데이터(FESTIVAL_MONTH) 의존으로 미작동**. 14(앵커 경주)는 정상 → 앵커 경로와 시드 발견 경로가 갈림.

### D-INTENT-14 (중) — soft non-empty 강제 → fallback 유발
- 14: mood어 없는 쿼리에서 스키마가 soft 비강제를 막아 3회 재시도 실패 → deterministic_llm_fallback(soft="" , cleaned 미정제). soft를 **empty 허용**으로 바꾸면 재시도 낭비 제거.

### D-INTENT-SOFT (하) — soft 분위기 외 누출
- 04 soft "사람 많고 활기찬 **인기 관광지**"(장소 유형 누출), 02·13 경계선. 프롬프트 미세조정 대상.

### D-COPY (하, 조치됨) — claim 내부어 누출 → planner_copy generic fallback
- 이전 덤프에서 claim이 "1위 점수" 등 내부어 생성 → `_safe_public_text` 거부 3회 → generic 문구. claim 프롬프트 금칙어 강화 적용. **현재 01 덤프는 grounded 경로로 clean**(used_llm=false). 재발 여부는 재실행으로 확인.

### D-SCALE (하) — scale_correction 의도-구현 불일치
- "도시 규모 보정" 명칭과 달리 후보 개수(budget cap) 기준이라 |Δ|≈0.005, 사실상 무영향. 정리는 고도화.

---

## 7. 결론 및 다음 단계

- **기능 출하 판정: PASS.** LangGraph 파이프라인은 정상·fallback·검증·마스킹·그라운딩을 설계대로 수행하며, 20케이스에서 크래시·스키마 위반·에러 0. 이 결과서의 §1~§5는 현재 덤프로 확정 가능.
- **품질·비기능 출하: 보류.** §6 D-SCOPE(벡터/Dynamo 스코프) 해소가 선행. 해소 후: (1) 20케이스 재실행 → 품질·분포·congestion 재측정, (2) 경로 2(배포 invoke→트레이스)로 NF/OB 채움.
- **즉시 액션:** 01·03 live 재실행으로 스코프 stale/desync 확정 → 분기에 따라 재임베딩 또는 전체 재수집.

---

## 부록 A — 알려진 갭 (계획 §8 유지)
- FB-01/04/06·FN-01은 입력만으로 재현 불가 → fault injection/전용 fixture(별도 라운드).
- FB-VAL-*(month/year/theme/country 경계)는 신규 negative fixture 필요 — 본 20케이스에 미포함.
- NF/OB는 경로 2(배포 트레이스) + OTel 계측 선행.
- 본 결과서 입력은 **기능 검증용**이며 추천 품질 oracle이 아니다.
