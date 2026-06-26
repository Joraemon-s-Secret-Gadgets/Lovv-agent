# Candidate Evidence Agent 현재 구현 동작 정리

기준일: 2026-06-25
분석 기준: `src/lovv_agent` 현재 코드. `app/LovvAgentV1/lovv_agent` 배포 사본과 핵심 파일 parity를 확인했다.

## 1. 한 줄 요약

`CandidateEvidenceAgent`는 Intent가 만든 `CandidateEvidenceInput`을 받아 실행 mode와 검색 가능 테마를 확정한 뒤, Bedrock embedding vector로 S3 Vectors 관광지 후보를 검색하고, 도시별 theme gate와 deterministic scoring/selection을 거쳐 Planner가 소비할 내부 `CandidateEvidencePackage`를 만든다.

이 노드는 최종 사용자 응답, 일정 문장 생성, 축제 날짜 검증, 최종 장소 상세 enrichment를 하지 않는다.

## 2. 런타임 진입 경로

실제 실행은 `src/lovv_agent/harness.py`의 `build_harness()`에서 조립된다.

```text
public /recommendations payload
  -> request_state_from_api()
  -> Intent node
  -> Supervisor
  -> candidate_node()
       -> embedding.embed_query(query_text)
       -> optional embedding.embed_query(soft_preference_query)
       -> CandidateEvidenceAgent.run(...)
  -> Supervisor
  -> Festival Verifier or Planner
  -> Response Packager
```

주요 조립 지점:

- `CandidateEvidenceAgent`에는 `DestinationSearchTool`, `DynamoLookupTool`, candidate-evidence 전용 Converse runtime, schema retry limit이 주입된다.
- `candidate_node()`는 `candidate_evidence_input`이 없으면 즉시 `SchemaValidationError`를 낸다.
- primary embedding query는 `cleaned_raw_query`, `soft_preference_query`, active theme 문자열 결합 순서로 첫 non-empty 값을 사용한다.
- `soft_preference_query`가 primary query와 다르면 두 번째 embedding을 만들고, Candidate Evidence의 soft 검색 채널로 넘긴다.

## 3. 입력 계약

입력은 `CandidateEvidenceInput`이다.

핵심 필드:

| 필드 | 사용 방식 |
| --- | --- |
| `country`, `travel_year`, `travel_month`, `trip_type` | 축제 seed, 후보 budget, selected city payload 구성 |
| `destination_id` | 있으면 anchored search로 고정 city 검색 |
| `active_required_themes` | 검색 가능 테마와 외부 링크 테마 분리의 원천 |
| `include_festivals` | true면 attraction retrieval 전에 festival seed lookup을 hard gate로 실행 |
| `cleaned_raw_query` | primary embedding query 우선 후보 |
| `soft_preference_query` | primary query와 다르면 soft vector 검색 추가 |
| `user_location` | city scoring의 거리 penalty 입력 |
| `city_anchor` | package에 그대로 전달되는 anchor metadata |

## 4. 실행 mode 결정

`prepare_candidate_evidence_context()`가 schema를 정규화하고 mode/theme split을 확정한다.

| Mode | 조건 | 실제 의미 |
| --- | --- | --- |
| `anchored_place_search` | `destination_id` 있음 | 해당 city 안에서만 관광지 후보 검색. `include_festivals=true`여도 city는 바꾸지 않는다. |
| `festival_seeded_city_discovery` | `destination_id` 없음, `include_festivals=true` | 먼저 DynamoDB festival seed city를 찾고, seed city 안에서만 attraction retrieval/scoring 실행. |
| `city_discovery` | 그 외 | 검색 가능 테마 기반으로 전체 city 후보를 찾고 scoring으로 city 선택. |

## 5. 테마 분리 규칙

`split_candidate_themes()`는 중복 제거 후 세 그룹으로 나눈다.

| 그룹 | 내용 | 후속 처리 |
| --- | --- | --- |
| `active_required_themes` | 축제 marker를 제외한 사용자 요구 테마 | package audit, quota, reason claim 요약에 사용 |
| `searchable_place_themes` | S3 Vector attraction 검색에 쓸 수 있는 테마 | theme별 `search_candidates()` 호출 |
| `external_link_themes` | 현재는 `미식·노포` | 관광지 vector 검색과 scoring 대상에서 제외, Planner의 foodSearch/CTA 정책으로 전달 |
| `ignored_theme_markers` | `festival`, `festival_event`, `축제`, `축제·이벤트` | 축제 flow marker로만 취급 |

주의: `DestinationSearchTool`도 food/festival 계열 테마를 attraction vector search에서 제외한다. 즉 agent와 tool 양쪽에서 같은 경계를 유지한다.

## 6. Festival seed hard gate

`include_festivals=true`이면 attraction retrieval 전에 `_run_festival_seed_lookup()`이 실행된다.

```text
CandidateEvidenceAgent.run()
  -> _run_festival_seed_lookup()
       -> DynamoLookupTool.search_festival_city_seeds(...)
            -> DynamoDbRepository.query_festival_candidates(...)
```

현재 구현의 세부 동작:

- `DynamoLookupTool.search_festival_city_seeds()`는 `country`, `travel_month`, `city_id`, `max_candidates`를 검증한다.
- `theme_pool` 인자는 caller compatibility를 위해 받지만, 현재 festival document에 travel-theme 필드가 안정적으로 없어서 실제 필터에는 쓰지 않는다.
- fixed city가 있으면 `PK=CITY#{city}`와 `SK begins_with FESTIVAL#` 조건으로 조회하고 month filter를 적용한다.
- city discovery이면 `FestivalMonthIndex`에서 `entity_type=festival`, `gsi_sk begins_with FESTIVAL#{month}`로 조회한다.
- 결과가 있으면 seed city id 목록을 attraction retrieval의 allowed city pool로 사용한다.
- 결과가 없으면 `no_festival_city_seed` 또는 `no_festival_in_anchor_city` failure package를 반환하고 Planner로 넘기지 않는다.

## 7. Attraction retrieval

Festival gate를 통과하거나 festival 요청이 없으면 `_run_attraction_search()`가 검색을 시작한다.

```text
_run_attraction_search()
  -> _retrieve_by_theme()
       -> DestinationSearchTool.search_candidates(query_vector, theme=...)
       -> optional DestinationSearchTool.search_candidates(soft_query_vector, theme=...)
  -> _merge_duplicate_candidates()
  -> DestinationSearchTool.prune_cities(...)
```

현재 특성:

- 테마별 검색은 순차 실행이다. 활성 searchable theme이 N개면 S3 Vectors query도 기본 N회 발생한다.
- `soft_query_vector`가 있으면 같은 theme에 대해 한 번 더 검색한다. 따라서 theme N개일 때 최대 2N회 S3 Vectors query가 발생한다.
- soft 검색 결과는 `place_id -> distance`로 매핑되고, primary 후보에 같은 `place_id`가 있을 때만 `soft_distance`가 주입된다.
- 중복 후보는 stable `place_id` 기준으로 병합하며, 더 작은 vector distance 후보를 유지한다.

## 8. DestinationSearchTool 세부 동작

`DestinationSearchTool`은 S3 Vector query payload 구성과 raw vector record 정규화만 담당한다.

`search_candidates()` 동작:

1. 하나의 active theme만 허용한다.
2. food/festival 계열 테마면 빈 tuple을 반환한다.
3. `build_attraction_search_request()`로 S3 Vectors payload를 만든다.
4. `S3VectorRepository.query_vectors()`를 호출한다.
5. `extract_vector_records()`가 `vectors`, `matches`, `results` 중 존재하는 collection을 추출한다.
6. 각 record를 `AttractionCandidate`로 정규화한다.

S3 Vector request 핵심:

| 필드 | 값 |
| --- | --- |
| `queryVector.float32` | 검증된 embedding vector |
| `topK` | call-level `top_k` 또는 `SearchBudgetSettings.per_theme_attraction_top_k` |
| `returnMetadata` | `true` |
| `returnDistance` | `true` |
| `filter.entity_type` | 항상 `attraction` |
| `filter.city_id` | anchored/festival seed city 제한이 있을 때 |
| `filter.theme_tags` | 현재 theme 하나 |

`normalize_attraction_candidate()`가 요구하는 metadata:

- `entity_type == "attraction"`
- `city_id`
- `title`
- `theme_tags`
- 선택/권장: `city_name_ko`, `latitude`, `longitude`, `ddb_pk`, `ddb_sk`, `place_id`

`place_id`가 metadata에 없으면 vector key의 chunk suffix를 제거해 유도한다.

## 9. City pruning과 scoring

검색 후보는 먼저 `DestinationSearchTool.prune_cities()`를 통과한다.

Pruning 규칙:

- city id가 없는 후보는 제외된다.
- festival seed 또는 anchored city 제한이 있으면 allowed city pool 밖 후보는 제외된다.
- 각 city는 모든 searchable theme을 최소 하나 이상 가져야 survived group이 된다.

그 다음 `_score_groups()`와 `_rank_cities()`가 실행된다.

`ScoringTool.score_place()`:

- `entity_type != attraction`이면 scored false로 제외된다.
- vector `distance`를 similarity로 변환한다.
- `soft_distance`가 있으면 soft similarity를 추가한다.
- 후보 theme이 active searchable theme과 겹치면 theme match bonus를 준다.
- title/city/theme/좌표 등 metadata 품질을 source quality score로 반영한다.
- user location이 있으면 local distance penalty를 반영할 수 있다.

`ScoringTool.score_city()`:

- place score 상위 `primary_budget` 후보만 city score 계산에 사용한다.
- semantic evidence, theme coverage, theme balance, scale correction, candidate sufficiency, distance penalty, congestion penalty를 합성한다.
- city ranking은 `(city_score, candidate_count)` 내림차순으로 정렬된다.

## 10. Candidate selection

`CandidateSelectionHelper.select_primary_with_theme_quotas()`는 city별 scored place에서 primary/reserve 후보를 고른다.

Trip type별 후보 budget:

| `trip_type` | primary | reserve | Planner 필요 장소 수 |
| --- | ---: | ---: | ---: |
| `daytrip` | 6 | 4 | 3 |
| `2d1n` | 10 | 8 | 5 |
| `3d2n` | 14 | 10 | 8 |
| `4d3n` | 18 | 12 | 11 |
| `5d4n` | 18 | 12 | 14 |

선택 규칙:

- place score 내림차순으로 정렬한다.
- title 기준 중복을 제거한다.
- searchable theme별 minimum quota를 먼저 채운다.
- 이후 theme max quota를 지키며 primary를 채운다.
- 그래도 부족하면 max quota를 완화해 primary를 더 채운다.
- primary에 들어가지 않은 후보에서 reserve를 만든다.
- `coverage_audit`에 quota, shortfall, relaxed slot, dedup count, unfilled slot을 남긴다.

City 선택은 ranking 1위가 항상 최종은 아니다. destination이 고정되지 않은 경우 `_select_city_rank_index()`는 Planner 필요 장소 수를 primary 후보로 채울 수 있는 가장 높은 ranking city를 선택한다. 아무 city도 충분하지 않으면 1위를 선택하고 package status는 `insufficient_candidates`가 된다.

## 11. Candidate reason claim 생성

검색/선택이 끝난 뒤 `_attach_candidate_reason_claims()`가 reason claim 후보를 붙인다.

동작 조건:

- package status가 `ok` 또는 `insufficient_candidates`
- `selected_city`가 있음
- `needs_clarification=false`

runtime이 없으면 deterministic template claim을 만든다.

runtime이 있으면:

1. `_reason_claim_safe_summary()`가 raw retrieval payload와 raw score를 제외한 safe summary를 만든다.
2. `build_structured_converse_request()`로 schema-enforced Bedrock Converse 요청을 만든다.
3. `invoke_structured_output()`이 retry limit 안에서 schema validation을 수행한다.
4. schema 성공이면 `CandidateReasonClaim`을 package에 붙인다.
5. schema 실패면 warning을 남기고 public-ineligible template claim으로 fallback한다.

안전 규칙:

- claim text/evidence refs/place ids에 `place_score`, `score_components`, `raw_s3_uri`, `raw retrieval`, `topK`, `top_k`, `vector distance` 같은 내부 token이 포함되면 거부된다.
- LLM claim은 retrieval, scoring, city selection, quota, fallback 결정을 바꾸지 못한다.

## 12. 출력 package

성공 또는 부분 성공이면 `CandidateEvidencePackage`가 반환된다.

주요 필드:

| 필드 | 내용 |
| --- | --- |
| `status` | `ok`, `insufficient_candidates`, `no_candidate`, `error` |
| `mode` | 실행 mode |
| `selected_city` | Planner 입력용 선택 city summary |
| `city_rankings` | city score, score breakdown, capacity audit, selected flag |
| `recommended_places` | Planner가 우선 사용할 primary 후보 |
| `reserve_places` | fallback용 reserve 후보 |
| `festival_candidates` | festival seed 후보 전체 |
| `selected_festival_candidates` | 선택 city에 속한 festival seed 후보 |
| `festival_seed_audit` | seed status, candidate count, seed city ids |
| `coverage_audit` | theme quota와 itinerary capacity audit |
| `retrieval_audit` | mode, searchable/external themes, retrieved/merged/survived counts |
| `candidate_counts` | retrieved, merged, scored, city, recommended/reserve counts |
| `fallback_audit` | Planner consumable 여부, selected rank, capacity fallback 여부 |
| `candidate_reason_claims` | Planner 설명 생성 재료 후보 |

`recommended_places`와 `reserve_places`는 raw S3 Vector payload 전체를 보존하지 않고, Planner에 필요한 경량 필드와 내부 score audit만 담는다. 최종 public API 응답에서는 이 내부 package와 raw audit이 그대로 노출되지 않는 것이 전제다.

## 13. Failure와 clarification 경로

| 조건 | status | clarification | Planner 진행 |
| --- | --- | --- | --- |
| `destination_search` 미주입 | exception | 없음 | 중단 |
| festival lookup tool 필요하지만 없음 | `error` | false | 중단 |
| festival seed 없음 | `no_candidate` | true | 중단, 사용자 질문 |
| searchable place theme 없음 | `no_candidate` | true | 중단, 사용자 질문 |
| theme gate 후 survived city 없음 | `no_candidate` | true | 중단, 사용자 질문 |
| scored city 없음 | `no_candidate` | true | 중단, 사용자 질문 |
| 선택 city primary 후보가 Planner 필요 수보다 적음 | `insufficient_candidates` | false | 진행 가능, Planner가 보수 처리 |
| candidate reason claim schema 실패 | 기존 status 유지 | false | 진행, warning + fallback claim |

Supervisor는 Candidate Evidence 완료 뒤 `package.status`, `needs_clarification`, `clarifying_question`을 보고 `END_WAIT_USER`, Festival Verifier, Planner, Response Packager 중 다음 경로를 결정한다.

## 14. 하위 component 책임 경계

| Component | 실제 책임 | 하지 않는 일 |
| --- | --- | --- |
| `CandidateEvidenceAgent` | mode/theme split, festival hard gate, retrieval/scoring/selection orchestration, internal package 생성 | public response, itinerary 작성, final detail enrichment |
| `DestinationSearchTool` | S3 Vector attraction request 구성, raw vector record 정규화, city theme gate | scoring, DynamoDB read, itinerary |
| `S3VectorRepository` | bucket/index를 붙여 S3 Vectors `query_vectors` 호출, OTel summary span 기록 | filter 생성, 후보 정규화 |
| `DynamoLookupTool` | festival city seed lookup, final detail enrichment helper 제공 | S3 Vector search, scoring, quota selection |
| `DynamoDbRepository` | DynamoDB query/get request 구성, pagination, OTel span 기록 | festival fallback 판단, detail warning 정책 |
| `ScoringTool` | place/city deterministic score 계산 | 후보 검색, quota selection, public 설명 |
| `CandidateSelectionHelper` | title dedup, theme quota, primary/reserve selection | score 계산, AWS 호출 |
| Candidate reason claim runtime | safe summary 기반 claim 후보 생성 | ranking/selection 변경, raw payload 노출 |

## 15. 현재 구현상 주의점

- 테마별 S3 Vector retrieval은 아직 병렬화되어 있지 않다.
- `soft_preference_query`가 별도 query이면 S3 Vector 호출 수가 theme 수만큼 추가된다.
- festival seed lookup은 현재 theme_pool을 실제 필터에 쓰지 않는다. month와 optional city가 실질 필터다.
- Candidate Evidence는 최종 상세 문서를 DynamoDB에서 붙이지 않는다. `ddb_pk`, `ddb_sk`를 package에 넘기고, final detail enrichment는 후속 Planner/detail 단계의 책임이다.
- `app/LovvAgentV1/lovv_agent`의 배포 사본은 이 문서 작성 시점에 조사한 핵심 파일 기준으로 `src/lovv_agent`와 동일했다.
