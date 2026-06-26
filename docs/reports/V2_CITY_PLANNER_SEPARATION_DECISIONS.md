# V2 도시 선정 ↔ 일정 생성 분리 의사결정 보고서

## 문서 정보

| 항목 | 내용 |
| --- | --- |
| 문서 상태 | Decision Draft |
| 기준일 | 2026-06-25 |
| 분석 기준 | `src/lovv_agent` 현재 코드 (`scoring.py`, `candidate_evidence.py`, `supervisor.py`, `planner.py`, `dynamo_lookup.py`) |
| 관련 문서 | `CANDIDATE_EVIDENCE_AGENT_RUNTIME_FLOW.md`, `docs/reports/kr_attraction_theme_personalization_feasibility_20260625.md`, `02_lovv_data_collect/docs/bedrock_metadata_enrichment_guide.md` |
| 목적 | V1의 도시 선정·일정 생성 결합 문제를 분리하는 V2 설계 결정과 코드 근거, 미결정 사항을 기록한다. |

이 문서는 정본 spec을 대체하지 않는다. 토론으로 합의된 결정과 그 코드 근거를 모아 구현 착수 전에 범위와 미결정 항목을 고정하는 점검 문서다.

## 1. 결론

V1은 도시 점수에 "일정을 채울 수 있는 후보 수"(capacity)가 섞여 있어, 관련성이 높지만 후보가 적은 도시가 순위에서 밀린다. V2는 **도시 선정**(Candidate)과 **관광지 선정·일정 생성**(Planner)을 명확히 분리한다.

핵심은 세 가지다.

첫째, `score_city`에서 capacity 결합을 제거한다. 둘째, Candidate는 curated된 최종 관광지 set 대신 도시 + 점수 매긴 후보 pool + seed를 넘기고, Planner가 고정 도시 안에서 관광지를 다시 선택한다. 셋째, RAG는 새로 만들지 않는다. 같은 S3 Vector 인덱스를 **2개 패스**(Candidate=테마 hard-gate / Planner=도시 고정·테마 무필터)로 사용한다.

추가로 visitor statistics 기반 간접 혼잡도를 도시 점수에 넣고, theme_weights 개인화를 도시 점수에 주입한다.

## 2. V1 문제 정의와 코드 근거

V1에서 도시 선정과 일정 충족이 한 점수·한 선택 단계에 결합되어 있다. capacity 결합은 코드상 세 곳이다.

| 위치 | 코드 | 문제 |
| --- | --- | --- |
| `scoring.py` `score_city` (약 257행) | `semantic_evidence = sum(top_places.score) / budget` | 고정 `budget`(기본 5)으로 나눠, 후보가 적은 도시를 점수에서 희석한다. |
| `scoring.py` `score_city` (약 261–265, 276행) | `candidate_sufficiency` (후보 ≥5면 +0.1) | 후보 5개 미만 도시를 절벽처럼 강등하는 이진 보너스. |
| `candidate_evidence.py` `_select_city_rank_index` (약 947–962행) | `len(selected.primary) >= required_place_count`인 첫 도시 선택 | rank 1위라도 primary가 부족하면 건너뛰고 채울 수 있는 하위 도시를 고른다. |

`_rank_cities`(약 884–911행)도 `(city_score, candidate_count)`로 정렬해 capacity를 보조 tiebreaker로 쓴다.

## 3. V2 책임 경계

| 책임 | Candidate (Pass 1) | Planner (Pass 2) |
| --- | --- | --- |
| retrieval / city scoring | 유지 | — |
| 도시 선정 | 유지 (단, lightweight viability 체크만) | — |
| 출력 | 도시 + scored pool + seed | — |
| 관광지 최종 선택 (quota·dedup·동선) | — | 이전 |
| 일정 배치·enrich | — | 유지 |

원칙: **도시 viability를 결정하는 선택은 Candidate, 일정 맥락이 필요한 선택은 Planner.** 도시 결정권은 Candidate가 primary + ranked reserve 도시를 제안하고 Planner가 실제로 일정을 지어 확정하는 식으로 분산한다.

## 4. score_city 변경 결정

`score_city`(`scoring.py`)는 stateless 순수 함수임을 코드로 확인했다. V2 재호출(Planner 확장 pool)에 안전하다.

| 항 | 변경 | 근거 위치 |
| --- | --- | --- |
| `semantic_evidence` | `÷budget` → `÷max(1, min(budget, n))` (평균 품질로) | 약 257행 |
| `candidate_sufficiency` | **제거** (또는 viability flag로 분리, ranking 제외) | 약 261–265, 276행 |
| `theme_balance` | 균등 Shannon 엔트로피 → **profile 가중 목표 분포** divergence | 약 477–500행 |
| `theme_match_score` (score_place) | 이진 0.2 → 매칭 테마의 `theme_weights` 비례 | 약 181–185행 |
| `congestion_effect` | 잠자던 `congestion_penalty` 훅을 부호 있는 항으로 배선 | 약 266–278행 |

`_select_city_rank_index`는 V2에서 `fixed_city_id`가 아니면 항상 rank 0(최상위)을 반환하도록 capacity 강등을 제거한다.

### 4.1 개인화(theme_weights) 적용 범위

theme_weights는 **active 테마 교집합 안에서의 재가중**으로만 도시 점수에 들어간다. active가 아닌 profile 테마는 도시 점수를 바꾸지 않는다(장소 채우기에서만 surface). "개수"가 아니라 "score"에 가중하며, theme_balance의 목표 분포를 재형성하는 방식이다. 단일 active 테마면 도시 점수 불변이다.

### 4.2 간접 혼잡도(congestion)

- 입력: 적재 완료된 **월별 visitor statistics**(도시+월 stat item)를 정규화한 값.
- 부호: 기본(소도시 지향) 약한 minus, "조용/한산" 명시 큰 minus, "활발/시끄러움" plus(음수 w_cong). 명확성을 위해 `± congestion_effect` 형태로 구조 변경 권장.
- 선호 신호: Intent에 혼잡 선호 필드를 신규 추가(예정).

주의 세 가지를 구현 시 반드시 반영한다.

1. **vibe와 혼잡도 분리.** enrichment 가이드는 `calm`/`serene`/`peaceful`을 "혼잡도와 무관"하게 정의했다. 따라서 "조용한 분위기"(vibe)와 "한산함"(congestion)은 다른 축이며, Intent가 둘을 구분해 라우팅해야 한다.
2. **정규화 + cap.** 원시 방문객 수는 도시 간 편차가 커서 그대로 넣으면 점수를 지배한다(과거 테스트에서 도시 순위가 뒤집힐 만큼 강했음). 정규화 후 cap을 걸어 비슷한 도시 재정렬에 한정한다.
3. **이중 감점 방지.** `scale_correction`(후보 수)과 congestion(방문객 수)이 둘 다 큰 도시를 깎으므로 소도시 과편향이 되지 않게 함께 튜닝한다.

## 5. RAG 구조 — 1개 인덱스, 2개 검색 패스

별도 RAG 시스템을 만들지 않는다. `DestinationSearchTool`의 `filter.theme_tags`/`filter.city_id`는 독립적으로 제어 가능하므로, 같은 인덱스·임베딩을 두 설정으로 호출한다.

- **Pass 1 (Candidate):** `filter.theme_tags=on` (도시·seed 후보용 hard gate).
- **Pass 2 (Planner):** `filter.city_id=고정`, `theme=off` (관광지 채우기용).

이는 "vector 발견 → finalist 한정 확장 → 재점수"의 retrieve-then-expand 패턴이며, 확장 대상이 고정 도시 1개라 비용이 bounded다. 점근 복잡도는 Candidate와 같은 클래스를 유지한다.

## 6. Candidate 출력 계약 변경

V2에서 Candidate는 `select_primary_with_theme_quotas`로 만든 curated `recommended_places`/`reserve_places`(현재 `candidate_evidence.py` 약 412–433행)를 최종 산출물로 내지 않는다. 대신 다음을 넘긴다.

- 선택 도시 + ranked reserve 도시
- 점수 매긴 후보 pool (theme_tags, 좌표, `ddb_pk`/`ddb_sk` 포함)
- seed(상위 anchor 후보)
- lightweight capacity audit (강등용 아님, viability 표시용)

`insufficient_candidates` 판정은 Candidate에서 사라지고, Planner가 재인출·확장 후 판단한다.

## 7. Planner 일정 마무리 flow

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | 입력 수신 (고정 도시·seed·reserve·축제) | 수정 |
| 2 | 일자·슬롯 골격 (`trip_type`→required count) | 유지 |
| 3 | anchor 배치 (seed 1/day) | 신규 ◆1 |
| 4 | Pass-2 재인출 (city 고정·theme off) | 신규 |
| 5 | 축제 날짜 배치 | 수정 ◆2 |
| 6 | 슬롯 채우기 (quota → MMR + geo tiebreak) | 신규 ◆3 |
| 7 | 충족성 판정 → fallback 사다리 | 신규 ◆4 |
| 8 | 최종 enrich (`enrich_final_places`) | 유지 |
| 9 | 출력 + grounded explanation | 유지 |
| 10 | 검증 → Supervisor (실패 시 ≤2회 재시도) | 유지 |

현재 Planner는 설계상 검색을 하지 않는다(`planner.py` docstring 약 4행, `recommended_places`만 배치하는 약 268행). 따라서 **3·4·6·7단계의 신규 구현, 특히 Planner에 검색 능력(DestinationSearchTool + embeddings)을 부여하는 것이 V2 최대 비용**이다. enrich는 기존 `enrich_final_places`(약 203–243행)를 재사용한다.

### 7.1 fallback 사다리

부족 시: 테마 완화 재인출 → 짧은 일정 / 사용자 질문(END_WAIT_USER) → reserve 도시로 재실행. reserve 도시는 Planner 내부에서 소비하며 Supervisor 루프를 새로 만들지 않는다. 축제 모드의 reserve는 festival seed 도시 풀로 한정한다.

## 8. non-seed 슬롯 채우기 신호 정책

목표는 "active 테마로 모든 슬롯을 채우지 않는 것"이다. 사용자가 제안한 신호들(soft_query, vibe, profile)은 모두 Intent/사용자 의존이라 **부재 가능**하다는 공통 약점이 있다(테스트에서 soft_query 미생성 확인).

- **robust 코어 (항상 동작):** query 유사도(primary embedding) + MMR 다양성 penalty. MMR은 어떤 optional 신호도 필요 없이 active 테마 편중을 깬다.
- **optional boost (있을 때만, 하나씩 추가·측정):** soft_query(독립 검색으로 변경 필요 — 현재는 primary 후보 부스터만, `_retrieve_by_theme` 약 827–841행), vibe overlap, profile, popularity(visitor stats), companion_fit.
- soft_query를 억지로 항상 생성하면 primary와 같아져 broadening이 0이 되므로 강제하지 않는다.

### 8.1 vibe tags

`bedrock_metadata_enrichment_guide.md`에 **canonical taxonomy**(vibe 38, experience 10, companion 7)가 정의되어 있고 enum 검증(temp 0)이 있으므로, Intent가 같은 vocabulary로 vibe를 내면 discrete overlap 매칭이 깨끗하게 동작한다(이전 턴의 어휘 정렬 우려 해소). 단 (a) hard filter 아닌 soft re-rank로 쓰고(미생성 관광지 recall hole 방지), (b) 실제 데이터 vibe 커버리지 확인, (c) Intent vibe 출력은 미구현이라 v1 이후 적용.

### 8.2 분류코드 다양성(MMR)

`lcls_systm3` 분류 코드로 일정 내 동일 분류 편중을 막는 다양성 penalty는 **도입 보류(고려만)**. 도입 시 hard cap이 아니라 soft MMR penalty로, slot 수 비례·다양성 없으면 양보·anchor 포함·테마 폭에 따라 λ 조절. `class_tags`는 벡터 metadata에 있어 추가 DynamoDB 왕복 불필요.

## 9. 모드별 영향

| 모드 | capacity 제거(ranking) | Planner 재인출 | 추가 작업 |
| --- | --- | --- | --- |
| 일반(city_discovery) | 적용 | 필요 | — |
| 도시 고정(anchored) | 불필요 (`_select_city_rank_index`가 이미 rank 0 반환) | 필요, 가장 단순 | — |
| 축제 포함(festival_seeded) | **적용** (seed 도시 간 동일 버그) | 필요 | 축제=날짜 anchor화(현재 day1 하드코딩, `planner.py` 약 389–442행), fallback은 seed 풀 한정 |

festival seed hard gate와 실패 경로(`no_festival_city_seed` 등), 축제 테마의 searchable theme 제외는 불변이다.

## 10. Supervisor 영향

Supervisor(`supervisor.py`)는 단일 swappable 라우팅 경계(`decide()`)로, fulfilled_matrix(evidence→festival→planning)를 읽어 결정론적으로 다음 노드를 정한다. V2 수정점은 두 곳이다.

1. **Planner 통과 게이트:** `_candidate_package_can_feed_planner`(약 385–395행)가 `recommended_places` 비어있지 않음을 본다 → V2는 curated set이 없으므로 **pool/seed 존재 확인으로 교체**.
2. **fallback 처리:** 채움 실패는 package의 reserve 도시를 Planner가 내부 소비하고 최후에만 END_WAIT_USER로 escalate. 선형 matrix 구조를 유지하고 supervisor 루프를 추가하지 않는다.

## 11. 병렬화 검토

현재 hot path는 전부 동기 boto3 호출이며 병렬이 없다.

- **의존성상 직렬(불가):** evidence→festival→planning, festival seed gate→attraction retrieval, 스코어링 파이프 단계.
- **병렬화 가능(이득 순):** (1) 테마별 retrieval — `_retrieve_by_theme`(약 819행)는 테마 for 루프 순차이고 soft 포함 최대 2N회 독립 I/O. 순차 O(T·L_v)를 ~O(L_v)로 줄이는 지배 latency 레버. (2) `enrich_final_places`(약 212행)는 장소별 개별 GetItem 순차 → BatchGetItem 1회로. (3) V2 Planner boost 쿼리 동시화. (4) (향후) Festival Verifier ∥ Planner Pass-2, 단 그래프 재구성 필요.
- **의미 없음:** 순수 Python 스코어링(GIL·소데이터).

리스크는 스레딩 자체보다 **결정성 보존**이다. 병렬 결과를 완료 순서가 아니라 결정론적 순서로 재정렬 후 스코어링에 넘겨야 한다(`_merge_duplicate_candidates`는 순서 무관이라 병합은 안전). throttle 상한·OTel span context·client thread-safety는 도입 전 확인한다. 병렬화는 기능 동작 후 별도 PR로 붙인다(V2 출하 지연 사유로 삼지 않음).

## 12. 미결정 사항

구현 착수 전 결정이 필요한 항목.

1. **P1 bundling — 가장 먼저.** 정공법(큰 PR: Planner에 검색 능력 신설) vs 인터림(작은 PR: city 강등만 제거 + Candidate가 선택 도시 retrieval 깊이만 확대). P1a(ranking 수정) 단독은 신규 승격된 저후보 도시가 짧은 일정을 낳아 회귀하므로, ranking 수정과 Planner 재인출은 묶어야 한다.

Planner flow의 4개 분기(◆).

2. ◆1 anchor 배치 = score 순 vs 테마 분산
3. ◆2 축제 = 그 날 슬롯 소비 vs overlay
4. ◆3 MMR 다양성 축(theme/`lcls_systm3`) + v1 on/off
5. ◆4 fallback 사다리 임계값·순서

데이터/연동 확인.

6. visitor statistics 후보 도시·월 커버리지 (적재는 완료)
7. Intent의 혼잡 선호 필드, vibe 출력(canonical) — 신규 예정
8. S3VectorRepository/DynamoDbRepository client thread-safety (병렬화 전)

## 13. 다음 단계

1. 미결정 1(bundling)을 확정한다 — 이것이 나머지 우선순위를 결정한다.
2. P1 범위(scoring.py 2곳 + `_select_city_rank_index` + Planner 재인출)를 spec(requirements/design/tasks)으로 분해한다.
3. parity 검증(동작 동일) → 품질 측정(짧은 일정 회귀 제거, 도시 순위 변화, 샘플 profile 3~5개)을 verification 단계로 둔다.
4. 병렬화(테마 retrieval, BatchGet)와 optional boost(soft_query→vibe→profile)는 후속 PR로 하나씩 추가·측정한다.
