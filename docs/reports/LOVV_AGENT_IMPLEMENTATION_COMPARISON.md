# Lovv Agent 설계 대비 구현 현황 및 한계

## 문서 정보

| 항목 | 내용 |
| --- | --- |
| 문서 상태 | Review |
| 기준일 | 2026-06-15 |
| 설계 기준 | `oh_my_documents/docs/05_agent_spec/agent_integrated_explanation.md` |
| 구현 기준 | `Lovv-agent/src/lovv_agent/`, `Lovv-agent/tests/` |
| 목적 | 통합 설명서가 정의한 흐름과 현재 코드의 구현 범위, 차이, 한계를 구분한다. |

이 문서는 설계 정본을 변경하지 않는다. 현재 구현을 발표하거나 AgentCore로
migration할 때, 구현 완료 범위와 후속 작업을 오해하지 않도록 하는 점검 문서다.

## 1. 결론

현재 `Lovv-agent`는 단순 scaffold나 mock workflow가 아니다. 실제 LangGraph,
Bedrock Runtime, S3 Vector, DynamoDB를 연결할 수 있는 실행 경로와
`/recommendations` 응답 포장까지 구현되어 있다.

통합 설명서가 강조하는 다음 원칙에는 대체로 부합한다.

- 단일 LLM 호출이 아니라 여러 단계로 책임을 분리한다.
- API structured input을 정본으로 사용한다.
- 도시와 장소는 검색 결과와 deterministic scoring으로 선택한다.
- Planner는 Candidate Evidence에 포함된 관광지만 사용한다.
- 검증되지 않은 축제를 일정에 넣지 않는다.
- 미식은 식당명을 생성하지 않고 선택 도시의 검색 링크로 제공한다.
- 내부 Candidate Evidence와 audit을 최종 API 응답에 노출하지 않는다.

다만 현재 구현의 Agent는 **LLM이 자율적으로 Tool을 선택하고 반복 호출하는
ReAct형 Agent가 아니다.** Python workflow가 Tool 호출 순서를 결정하고, LLM은
자연어 해석과 근거 문장 생성에 제한적으로 사용된다.

이는 통합 설명서의 데이터 기반 파이프라인 설명과 충돌하지는 않는다. 해당 문서는
Agent를 역할, 입력·출력 계약, Tool 사용, 실패 처리를 포함한 실행 단위로 정의하며,
LLM 자율 tool-calling을 필수 조건으로 명시하지 않는다. 그러나 팀이 의도한
`autonomous tool-using agent` 수준을 목표로 한다면 별도의 설계와 구현이 필요하다.

## 2. 전체 흐름 비교

| 설계 단계 | 현재 구현 | 상태 | 비고 |
| --- | --- | --- | --- |
| 사용자/API 입력 | API payload를 `UnifiedAgentState`로 변환 | 구현 | `request_state_from_api()` 사용 |
| Intent Agent | structured input 검증 및 자연어 보조 신호 추출 | 구현 | 긴 자연어에서 Bedrock structured output 사용 |
| Supervisor Router | fulfilled matrix와 status 기반 routing | 구현 | deterministic router |
| Candidate Evidence Agent | 축제 seed, 관광지 검색, 도시 scoring, primary/reserve 생성 | 구현 | Tool 순서는 Python 코드가 고정 |
| Festival Verifier | 선택 도시 축제의 연도·월 적용 가능성 검증 | 부분 구현 | DynamoDB 날짜 기반이며 외부 공식 페이지 검증은 없음 |
| Planner Agent | 일정 배치, 축제 overlay, 상세 보강, 설명 생성 | 부분 구현 | 단순 slot template 기반 |
| Validation | 장소·축제 grounding과 식당 생성 금지 검사 | 부분 구현 | semantic validation은 제한적 |
| Backend Serving | public API JSON 포장 | 부분 구현 | 저장/SAM/API 서버 책임은 미구현 |
| AWS live harness | Bedrock, S3 Vector, DynamoDB adapter 조립 | 구현 | boto3 credential chain 사용 |
| AgentCore Runtime | 별도 `myagent`에서 migration 중 | 저장소 외부 | 이 저장소에는 배포 manifest가 없음 |

실제 LangGraph 경로는 다음과 같다.

```text
Intent Agent
  -> Supervisor
  -> Candidate Evidence Agent
  -> Supervisor
  -> Festival Verifier (includeFestivals=true)
  -> Supervisor
  -> Planner Agent
  -> Supervisor
  -> Response Packager
```

각 worker는 실행 후 Supervisor로 돌아간다. Planner validation 실패 시 최대 제한
횟수 안에서 Planner를 다시 실행할 수 있다.

## 3. Agent별 구현 현황

### 3.1 Intent Agent

구현된 항목:

- `entryType`, `country`, 여행 연월, `tripType`, `destinationId`, themes,
  `includeFestivals`, `userLocation` 검증
- API canonical theme code를 내부 한국어 label로 변환
- `cleaned_raw_query`, `soft_preference_query`, `unsupported_conditions` 생성
- 목적지와 축제 포함 여부에 따른 Candidate Evidence 실행 mode 결정
- 입력 불충분 또는 계약 위반 시 clarification 상태 생성
- Bedrock structured output을 사용한 자연어 보조 신호 추출
- LLM이 core API 값을 변경하면 LLM 결과를 폐기하는 안전 장치
- 짧은 입력 또는 LLM schema 실패 시 deterministic fallback

LLM 사용 범위:

- 자연어의 검색 의도와 soft preference 정리
- unsupported condition 추출 보조
- API의 국가, 월, 여행 유형, 목적지, 축제 여부를 새로 결정하지 않음

한계와 차이:

- 자연어 대화에서 누락된 core field를 채우는 multi-turn clarification loop는 없다.
- conversation summary와 messages를 prompt에 넣을 수 있으나 Memory adapter가 없다.
- `travelYear`가 API payload에 없으면 harness에서 `2026`을 기본값으로 사용한다.
- legacy festival theme가 들어오면 `includeFestivals=true`로 정규화한다.
- LLM이 Tool을 선택하거나 다음 Agent를 결정하지 않는다.

### 3.2 Supervisor Router

구현된 항목:

- `evidence`, `festival`, `planning` fulfilled matrix 관리
- Candidate Evidence status와 clarification 여부에 따른 중단 처리
- 축제 미선택 시 festival 단계를 `N/A`로 처리
- Planner validation retry count 제한
- worker 실행 후 Supervisor 복귀
- 완료, 사용자 대기, 응답 포장 route 결정

한계와 차이:

- Supervisor는 LLM Agent가 아니라 deterministic state machine이다.
- raw search 결과를 해석하거나 Tool을 동적으로 선택하지 않는다.
- 현재 구조는 정본의 “교통정리 담당” 책임에는 부합하지만, LLM Supervisor 실험은
  구현되지 않았다.

### 3.3 Candidate Evidence Agent

구현된 항목:

- `city_discovery`, `anchored_place_search`,
  `festival_seeded_city_discovery` mode
- 축제 포함 시 DynamoDB에서 월과 사용자 테마 OR 조건으로 festival city seed 조회
- 축제 seed가 없을 때 일반 도시 검색으로 몰래 완화하지 않고 clarification 반환
- S3 Vector attraction 검색
- 관광 테마별 검색과 metadata filter
- place id 기준 중복 제거
- 도시별 grouping과 필수 테마 coverage gate
- deterministic place scoring 및 city scoring
- 여행 유형별 일정 슬롯 수를 충족하는 primary 후보가 있는 최고 순위 도시 선택
- 1위 도시의 primary가 부족하면 충분한 다음 순위 도시로 fallback
- 모든 도시가 부족하면 1위 도시를 유지하고 축소 일정 상태 반환
- 선택 도시, city rankings, primary, reserve 후보 생성
- theme quota와 coverage audit
- retrieval, fallback, festival seed audit
- LLM 기반 `candidate_reason_claims` 생성과 schema fallback

LLM 사용 범위:

- 이미 선택된 도시와 장소 근거를 짧은 한국어 claim으로 압축
- 도시 ranking, scoring, 후보 선택은 변경하지 않음

한계와 차이:

- Agent가 검색 전략을 자율적으로 선택하거나 결과를 보고 재검색하지 않는다.
- Tool 호출 순서는 festival seed → attraction retrieval → scoring → selection으로 고정된다.
- 현재 harness는 `cleaned_raw_query`를 우선해 embedding 하나를 만들고, 같은 vector를
  각 테마 검색에 사용한다. 통합 설명서가 표현한 독립적인 raw/soft query channel
  검색은 완전하게 구현되지 않았다.
- 검색 결과가 부족할 때 query rewrite, top K 조정, filter 완화 같은 반복 탐색이 없다.
- Weather Trends 입력은 scoring에 연결되지 않았다.
- restaurant table과 restaurant vector 후보는 의도적으로 검색하지 않는다.
- Candidate Evidence의 LLM claim은 downstream 설명 재료이며 사용자 최종 문구 자체는
  아니다.

### 3.4 Festival Verifier Agent

구현된 항목:

- Candidate Evidence가 선택한 도시의 festival candidate만 입력으로 사용
- 시작일·종료일 정규화
- 시작 연도가 `travelYear`와 일치하는지 확인
- 축제 기간과 `travelMonth`의 적용 가능성 확인
- `confirmed`이면서 월 조건을 만족한 축제만 `placeable` 처리
- cache adapter를 주입할 수 있는 경계와 cache key 정책
- Planner가 사용할 구조화 검증 결과 생성

한계와 차이:

- 현재 live harness는 cache adapter를 주입하지 않는다.
- DynamoDB candidate에 포함된 날짜를 검증할 뿐, 공식 축제 페이지나 Web Search를
  호출해 날짜를 재확인하지 않는다.
- 운영 상태, 취소 여부, 장소 변경 같은 외부 최신 정보 검증은 없다.
- confidence는 검증 정책에 따라 `0.8` 또는 `0.4`로 고정된다.

따라서 현재 구현의 “검증”은 외부 사실 확인 Agent라기보다 **저장된 날짜 필드에
대한 연도·월 정책 검증기**에 가깝다.

### 3.5 Planner Agent

구현된 항목:

- Candidate Evidence status gate
- `daytrip`, `2d1n`, `3d2n`, `4d3n`, `5d4n` slot template
- 선택 도시의 recommended place만 일정에 배치
- reserve place는 현재 일정 배치에 사용하지 않음
- confirmed/placeable festival overlay
- 최종 배치 attraction만 DynamoDB detail enrichment
- 미식 테마의 meal placeholder와 `foodSearch` 링크
- 지도, 숙소, 음식점 검색 링크 생성
- 후보 부족 시 축소 일정과 사용자 notice
- deterministic 기본 설명 생성
- Bedrock 기반 일정 item `title`, `body`, `reason`, 추천 이유, 흐름 설명 생성
- LLM 출력 schema 검증과 deterministic fallback
- 빈 alternative itinerary 반환

LLM 사용 범위:

- 최종 배치 item과 보강된 overview를 바탕으로 사용자용 문구 작성
- 새로운 장소, 축제, 식당을 추가할 수 없음
- 내부 score나 AWS 저장 구조를 사용자 문구에 노출할 수 없음

한계와 차이:

- 일정 배치는 거리, 영업시간, 체류시간, 이동시간 최적화가 아니라 고정 slot 순서다.
- primary 후보가 슬롯보다 부족해도 reserve 후보로 남은 slot을 채우지 않는다.
- 도시 탐색에서는 primary 슬롯 충족 여부로 다음 순위 도시를 선택하지만,
  anchored mode에서는 사용자 고정 도시를 유지하고 축소 일정을 만든다.
- 통합 설명서에 있는 일반 자유시간·산책 placeholder는 구현되지 않았다. 미식용 meal
  placeholder만 존재한다.
- 축제는 첫 attraction 뒤에 단순 삽입하며 날짜별 정교한 배치가 아니다.
- 일정 재구성은 Planner LLM이 수행하지 않는다. LLM은 배치 완료 후 문구만 작성한다.
- confidence는 정상 `0.72`, 후보 부족 `0.5`로 고정되어 있으며 audit에서 계산하지
  않는다.
- 대안 일정과 기상 대체 일정은 구현되지 않았다.
- 일정 수정, 사용자 피드백 반영, multi-turn plan editing은 구현되지 않았다.

### 3.6 Validation

구현된 deterministic validation:

- attraction이 Candidate Evidence의 recommended/reserve place인지 확인
- festival이 confirmed verifier 결과인지 확인
- named restaurant 생성 금지
- meal placeholder의 `placeId` 금지
- validation 실패 시 Supervisor가 제한된 Planner 재실행 수행

한계와 차이:

- 한 도시 원칙을 별도 validation rule로 다시 검사하지 않는다.
- 설명과 일정의 의미적 일치 여부를 판단하는 semantic validator가 없다.
- route overclaim, 이동 가능성, 일정 밀도, 중복 장소 검증이 없다.
- 현재 Planner가 deterministic하게 같은 일정을 다시 만들기 때문에 validation retry가
  실제 수정 효과를 내지 못할 수 있다.
- LLM 문구는 schema, item reference, 금지 내부 용어를 검사하지만 모든 factual claim을
  원문과 문장 단위로 대조하지 않는다.

### 3.7 Response Packager / Backend Serving

구현된 항목:

- Planner 결과를 public recommendation response로 변환
- destination, itinerary days/items, explainability, festival verification, links,
  notice, confidence 포장
- `candidate_evidence_package`, raw retrieval, score audit, DynamoDB key 비노출
- 응답 TTL timestamp 생성
- clarification 또는 실패 상태의 안전한 응답 포장

한계와 차이:

- 구현은 Response Packager이며 실제 Backend API/SAM 서버가 아니다.
- 추천 결과 저장, 사용자 저장 API, MySQL 영속화가 없다.
- 인증, HTTP status mapping, idempotency, request tracing export는 harness 밖의 책임이다.
- AgentCore Runtime entrypoint와 observability 설정은 `myagent` migration에서 별도로
  다룬다.

## 4. LLM 및 Tool 사용 현황

| 단계 | LLM 사용 | Tool/AWS 사용 | 현재 제어 주체 |
| --- | --- | --- | --- |
| Intent | 사용 | Bedrock Converse | Python이 호출 조건 결정 |
| Supervisor | 미사용 | Matrix transition | deterministic router |
| Candidate Evidence 검색 | 미사용 | Bedrock embedding, S3 Vector, DynamoDB | Python 고정 workflow |
| Candidate reason claim | 사용 | Bedrock Converse | Python이 선택 완료 후 호출 |
| Festival Verifier | 미사용 | DynamoDB에서 받은 candidate, 선택적 cache | deterministic policy |
| Planner 일정 배치 | 미사용 | DynamoDB detail lookup, link builder | Python slot template |
| Planner 문구 생성 | 사용 | Bedrock Converse | Python이 최종 배치 후 호출 |
| Validation | 미사용 | Validation helper | deterministic rules |
| Response Packager | 미사용 | 없음 | deterministic mapping |

현재 구현에서 LLM은 Tool을 직접 호출하지 않는다. Tool은 Agent class 또는 harness가
정해진 순서로 호출한다. 따라서 다음과 같은 loop는 아직 없다.

```text
LLM 판단
  -> Tool 선택
  -> Tool 결과 관찰
  -> 추가 Tool 호출 또는 종료 판단
```

현재 구조는 다음에 가깝다.

```text
Python workflow
  -> Tool 호출
  -> deterministic 선택/검증
  -> 필요한 지점에서 LLM structured output 호출
```

## 5. 설계와 구현이 잘 맞는 부분

1. API core field를 자연어보다 우선한다.
2. Candidate Evidence가 도시와 장소 선택을 책임진다.
3. scoring은 LLM이 아니라 deterministic Tool이 담당한다.
4. 축제 포함 city discovery에서 월·테마 seed를 hard gate로 사용한다.
5. Festival Verifier는 선택 도시 후보만 검증한다.
6. Planner는 Candidate Evidence에 없는 관광지를 만들지 않는다.
7. restaurant 후보나 식당명을 생성하지 않는다.
8. 최종 배치 장소만 DynamoDB에서 상세 보강한다.
9. 사용자용 문구 생성과 내부 audit을 분리한다.
10. 내부 Candidate Evidence Package를 public API에 노출하지 않는다.

## 6. 우선 보완이 필요한 항목

### P0: 실행 계약과 correctness

1. `travelYear` 누락 시 2026을 사용하지 말고 API 계약에 따라 필수 검증할지 결정한다.
2. 통합 설명서의 `entryType` 예시는 실제 API code와 실행 mode를 혼용하고 있으므로
   정본 문서에서 분리한다.
3. raw query와 soft query를 독립 검색 channel로 사용할지, 현재 단일 embedding
   전략을 정식 정책으로 둘지 결정한다.
4. validation retry 시 동일 결과가 반복되지 않도록 수정 전략 또는 종료 정책을
   명시한다.

### P1: 설계상 명시됐지만 부분 구현인 항목

1. semantic validation과 설명 grounding 검증
2. 축제 공식 출처/Web Search 기반 재검증
3. 계산 가능한 confidence 정책
4. 후보 부족 시 안전한 일반 placeholder
5. 일정 날짜·거리·이동시간을 고려한 배치
6. Backend 저장/API/SAM 책임

### P2: 후속 고도화 항목

1. Weather Trends scoring과 alternative itinerary
2. AgentCore Memory를 통한 multi-turn context
3. 사용자 일정 수정 workflow
4. LLM Supervisor 비교 실험
5. Candidate Evidence와 Planner의 자율 tool-calling 실험

## 7. 문서 해석 시 주의사항

통합 설명서에는 현재 API/구현과 맞지 않거나 구현 완료로 오해할 수 있는 표현이
일부 있다.

- 입력 표의 `entryType` 예시는 `city_discovery`, `anchored_place_search`로 되어
  있지만, 현재 코드에서 `entryType` 허용값은 `map_marker`, `chat`,
  `home_recommendation`이다. 전자는 Candidate Evidence의 내부 execution mode다.
- raw/soft query 기반 검색을 별도 channel처럼 설명하지만 현재 구현은 embedding
  하나를 선택해 테마별 검색에 재사용한다.
- Festival Search/Web Search가 Tool 지도에 있으나 현재 Festival Verifier는 저장된
  날짜만 검증한다.
- semantic validation과 재작성은 설계 설명보다 현재 구현 범위가 작다.
- Backend Serving은 응답 포장까지 구현됐고, 저장과 SAM 제공은 구현되지 않았다.

따라서 발표에서는 “현재 구현”과 “설계 확장 방향”을 분리해야 한다.

## 8. 현재 구현을 설명하는 권장 문구

> 현재 Lovv Agent는 LangGraph 기반의 데이터 중심 추천 workflow입니다. Intent에서
> API 입력과 자연어 선호를 정리하고, Candidate Evidence에서 Bedrock embedding과
> S3 Vector 검색, deterministic scoring으로 도시와 관광지를 선택합니다. 축제 포함
> 요청은 DynamoDB의 월·테마 seed를 먼저 적용하고 선택 도시의 날짜를 별도
> 검증합니다. Planner는 선택된 근거 안에서 일정을 배치하고, 최종 장소 상세와
> 사용자용 설명을 생성합니다. LLM은 자연어 해석과 설명 생성에 사용되며, Tool
> 선택과 검색·scoring·일정 배치 순서는 현재 Python workflow가 제어합니다.

## 9. 검증 기준

현재 repository의 기본 검증 명령은 다음과 같다.

```powershell
uv run pytest
uv run python -m compileall src tests
```

live AWS 경로는 별도 환경 설정과 credential을 사용해 다음 구성으로 검증한다.

```text
API request
  -> CompiledStateGraph
  -> Bedrock Converse / Embedding
  -> S3 Vector
  -> DynamoDB
  -> Response Packager
```

AgentCore Runtime의 DEV/deploy 검증은 `myagent` repository의 진입점과 설정을 별도로
검토해야 하며, 이 문서의 “구현 완료” 판정에 포함하지 않는다.
