# V2 아키텍처 검증 계획 (전반)

> 작성일 2026-06-28 · 대상: 확정 아키텍처 전체(`V2_07_ARCHITECTURE_FINAL.md`) — 노드 · 데이터 계약 · 결정(Decision) · E2E.
> Intent 노드 세부 검증은 `V2_09_INTENT_PARSING_SPEC.md` 부록 A에 있고, 본 문서는 그것을 **아키텍처 전반으로 확장**한다(중복은 참조로 대체).

---

## 0. 먼저 — 검증의 전제는 "계측"이다
**측정할 수 없는 것은 검증할 수 없다.** 스코어링·배치처럼 가장 중요한 부분이 정확히 그래서 검증이 어렵다. 아래 계측이 **선결**(없으면 검증 자체가 불가):

| 계측 항목 | 어디서 | 검증에 쓰는 곳 |
|---|---|---|
| **점수 분해 로깅**(score_city/score_place의 각 항: semantic·theme_weights·congestion·geo·scale 등 개별값) | scoring_and_selection / Planner | 스코어 회귀·단조성·분포 |
| **seed id 기록**(어떤 장소가 seed로 뽑혔는지) | scoring_and_selection | seed 결정성·보존 |
| **response_status + userNotice 사유 코드**(enum) | Packager | E2E 상태 단언·엣지 |
| **재인출 파라미터**(top_k·거리 페널티·필터 조건) | retrieval / Planner 수정 | 수정 루프 검증 |
| **execution_mode·플래그**(contradiction/underspecified/out_of_scope) | Intent | 분기 검증 |
| **LLM 비결정 통제**(temperature·seed 고정 or 호출 캡처) | LLM 노드 전반 | 결정성 확보 |

> 결론: **착수 1순위에 "구조화 로깅 + 사유 코드 enum"을 넣는다.** 이게 깔려야 나머지 검증이 성립한다.

---

## 1. 검증 유형 (전반 공통 어휘)
- **U 단위·결정론**: 규칙 입출력 고정, 100% 일치.
- **G 라벨셋/골든셋**: 분류·추출·선택 품질. confusion matrix·P/R·exact match.
- **M 메트릭·분포**: 스코어/배치 같은 연속값의 단조성·분포·기준선 대비 개선.
- **J LLM-judge + 휴먼 스팟체크**: 의미 품질(정성).
- **I 통합**: 노드 간 계약(입출력 스키마·상태 전이) — 의존(S3/DDB/Bedrock)은 mock/local.
- **E E2E**: 시나리오 입력→최종 출력 골든 트레이스.
- **R 회귀**: V1 입력 재생, 무회귀 + 의도된 개선 확인.

---

## 2. 노드별 검증

| 노드 | 검증 항목 | 유형 | 방법 / 합격기준(초안) | 검증난이도 |
|---|---|---|---|---|
| **Intent** | 파싱·분기·플래그 | U+G+J | V2_09 부록 A 참조(mode 100%, 모순 recall≥0.95 등) | 중 |
| **Supervisor** | 초회/resume 분기, 수정 의도 라우팅, response_status 결정 | U | thread/checkpoint 유무·플래그 조합 → 기대 라우팅 단위테스트. **100%** | 하 |
| **retrieval_node** | S3 Vector 검색·merge·prune, 수정 시 슬롯 재인출 | I+U | mock S3로 top_k·중복 제거·prune 규칙 단위. 재인출 파라미터 단언 | 중 |
| **scoring_and_selection** ★ | score_city 각 항, **soft 게이트 효과**, capacity 제거, seed 추출, transport/geo | M+U+G | ① 항별 단위(단조성: congestion↑→점수↓ 등) ② **골든 도시셋**(입력→기대 top-1/top-k, 허용오차) ③ **soft vs AND 기준선**: 멀티테마 소도시 생존율↑ 입증 ④ seed 결정성(동일 입력→동일 seed) | **상** |
| **Festival Verifier** | 날짜 검증(confirmed/not_placeable), 테마 정합 필터 | U+G | 날짜·기간 교차 단위테스트 100%. 정합 필터는 라벨셋(데이터 적재 후) | 중 |
| **Planner** ★ | 2-pass, seed 라운드로빈 배치, geo 동선, **다건 일괄 재배치**, on-demand Plan B, weatherNotice 임계 | U+M | ① 구조 단언(seed=day anchor, ≤3, 추가 없음) ② **동선 품질**: 총 haversine이 FIFO 기준선보다↓ ③ **배치 결정성**: op 순서 바꿔도 동일 결과(순서 독립) ④ weatherNotice 룰 단위(임계 초과 iff 발동) | **상** |
| **Response Packager** | 출력 스키마, status enum, interrupt 발행 | U | 스키마 validation 100%. 평시 alt/notice=null. interrupt→checkpoint 호출 단언 | 하 |
| **Profile Agent** | read 주입, **저장 기반 write**, fallback(saved_trip_count≥n) | U+I+G | write는 "저장" 이벤트에서만 발생(수정 중 발화로는 변화 0) 단언. fallback 경계(n-1/n) 단위. 추천 이유 문구 포함 | 중 |
| **Memory** | checkpoint 저장/resume 복원, TTL, **세션 avoid 유지** | I | resume 왕복(저장→복원 동치) 통합테스트. avoid가 세션 끝까지 유지·TTL 후 소멸 | 중 |

---

## 3. 데이터 계약 검증 (I + U)
- **스키마 validation**: CitySelectionResult(`candidate_sufficiency` 부재·`theme_weights`·`seed` 존재), PlacePool(seed-only·세부타입·indoor/outdoor 태그), PlannerInput(`transport_pref`), 응답 스키마(`alternativeItinerary`·`weatherNotice` nullable·`response_status` enum에 `modification_pending`), LovvUserProfile(`saved_trip_count`).
- **직렬화 왕복**: checkpoint 저장/복원 후 동치.
- **front 호환**: 응답 스키마는 front 협의 계약 — 계약 테스트(필드 추가가 기존 파서 안 깨는지), `move`는 에이전트 미채움 단언.

---

## 4. 결정(Decision) 준수 테스트
각 결정이 "코드에서 실제로 지켜졌는가"를 직접 단언한다(설계≠구현 갭 방지).

| 결정 | 준수 단언 | 유형 |
|---|---|---|
| D-A on-demand Plan B | 평시 alternativeItinerary=null, **자동 사전 생성 0**. 동의 시에만 채움 | U+E |
| D-B 수정 범위 | seed 불변 · 배치 ≤3 · 추가/삭제 없음 · 도시변경은 city_select 경로만 | U |
| 배치 편집 | 다건 분해, **부분 실패=부분 적용+안내**, 모순→되묻기 | U+E |
| D-K profile write | **저장 시에만** write, 수정 발화 누적 0, fallback n 경계 | U |
| D-E transport | walk→거리 페널티↑ / car→완화 (방향성) | M |
| D-J weatherNotice | 임계 룰대로 발동(수치는 데이터 후 튜닝 → 룰 구조만 고정 검증) | U |
| soft 게이트 | 부분 충족 생존 · 미충족 강감점 · 완전 0매칭만 no_candidate | M+G |
| capacity 제거 | candidate_sufficiency 미사용(항상 rank 0), 부족은 In-city Itinerary로 | U |
| 기피 | 세션 avoid 유지(TTL), 영구 profile 미반영 | I |
| 응답상태 | modification_pending 1개만 추가 | U |
| 되묻기 | 모순 → 무조건 needs_clarification(절충 생성 0) | G |

---

## 5. E2E 시나리오 검증 (SC-* 골든 트레이스)
각 시나리오를 입력→최종 출력까지 한 트레이스로 고정하고 핵심 포인트를 단언.

| SC | 검증 포인트 | 유형 |
|---|---|---|
| SC-00/G2 | move 채움(front 계약)·seed=anchor·status=completed | E+U |
| **SC-G1 멀티테마** | soft 게이트로 소도시 생존(AND 기준선 대비 생존율↑) | E+M |
| SC-G3 축제 | confirmed만 배치·실제 날짜 분산·미확정 userNotice | E |
| SC-R1/R3 | In-city Itinerary로 축소 빈도↓ / 완전 0매칭만 END_WAIT | E+M |
| SC-02 날씨 | 임계 초과 → weatherNotice 발동, primary는 유지, 자동 Plan B 0 | E+U |
| **SC-03 슬롯 교체** | 해당 슬롯만 변경·seed/나머지 불변·status=modification_pending | E+U |
| 다건 동시 | op 분해·일괄 재배치·일부 실패 시 부분 적용+안내 | E |
| SC-M4 리셋 | 기존 도시/테마 avoid·차순위 재생성 | E+I |
| SC-N2 모순 | 절충 없이 되묻기 | E+G |

> E2E는 비용이 크므로 **핵심 8~9개만 골든**으로 고정하고, 나머지는 노드 단위 + 계약 테스트 조합으로 커버한다.

---

## 6. 검증 난이도 → 빌드 우선순위 연결
"검증 쉬운 것부터" 깔면 thin slice 자신감이 빨리 쌓인다(V2_07 우선순위의 "검증가능성" 축과 직결).

- **결정론(쉬움) — 먼저, 0 허용**: execution_mode · Supervisor 라우팅 · 스키마 · seed 보호 · 배치 ≤3 · capacity 제거 · weatherNotice 룰 구조.
- **분포/메트릭(중) — 기준선 대비 개선 입증**: score_city · soft 게이트 생존율 · 동선 haversine · transport 방향성. **기준선(V1/AND/FIFO)을 같이 돌려 비교**해야 의미 있음.
- **정성(어려움) — judge+스팟체크로 흐름만 감시**: 모순·범위밖 인식 · 무드/soft 추출 · 대화 E2E.

> 비결정 노드(LLM) 통제 원칙: **출력 스키마·구조는 결정론으로, 의미는 judge로** 이원화. LLM 호출은 seed/temperature 고정 또는 응답 캡처로 회귀 안정화.

---

## 7. 한 줄 실행 지침 (드리프트 방지)
**검증 프레임워크를 코드보다 먼저 짓지 말 것.** 1순위는 §0 계측(로깅+사유 enum), 그다음 thin slice 코드와 **나란히** 단위·계약 테스트를 붙인다. 골든셋·E2E·judge는 해당 기능이 돌기 시작한 뒤 채운다. 측정 가능하게 만든 뒤, 기준선과 비교하라 — 그게 "좋아졌다"의 유일한 증거다.
