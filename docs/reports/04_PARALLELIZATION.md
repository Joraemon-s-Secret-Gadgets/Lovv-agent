# 04 · 현재 Agent 구조의 병렬 실행 가능성

기준일: 2026-06-17 · 신뢰도 규칙은 [README](./README.md) 참조.
목적: 현재 구조에서 병렬화 가능/불가 지점, 권장 방식, 선행 작업을 코드 근거로 정리한다.

## 1. 결론

**그래프(노드) 단위 병렬은 현 설계에서 사실상 불가하지만, 노드 "내부"의 I/O 병렬화는 안전하고
효과가 크다.** 가장 큰 이득은 테마별 벡터 검색의 병렬화다.

## 2. 스레드 안전성 — 병렬화의 전제 [확인됨]

- `S3VectorRepository`, `DynamoDbRepository`는 `@dataclass(frozen=True, slots=True)`의 **상태 없는
  pass-through**다. 주입된 boto3 클라이언트를 호출만 하며 요청 payload는 매 호출 로컬 dict로
  복사(`dict(request)`). 공유 가변 상태가 없다.
- boto3 **저수준 클라이언트는 메서드 호출이 thread-safe**(세션/리소스 생성만 비안전인데, 클라이언트는
  harness 부팅 시 1회 생성 후 재사용). 여러 스레드가 같은 클라이언트로 동시 `query_vectors`/
  `get_item` 호출해도 안전.
- 검색 단계에서 동시 접근되는 공유 객체는 boto3 클라이언트(안전)뿐. Scoring/Selection은 검색 후
  실행되어 동시성 충돌 대상이 아니다.

## 3. 병렬화 가능 — 우선순위 [확인됨(독립성) + 추정·중(효과)]

### 3-1. 1순위: 테마별 벡터 검색 (`agents/candidate_evidence.py: _retrieve_by_theme`)

현재 `for theme in themes` 순차 실행. 각 호출 독립, 결과는 concat 후 `_merge_duplicate_candidates`
(place_id 기준 최소 distance)로 중복 제거 → **완료 순서 무관, 병렬 안전.** 지연 (단일쿼리×N) →
약 (단일쿼리×⌈N/워커⌉).

코드 스케치(공개 계약 불변, 약 10줄):

```python
from concurrent.futures import ThreadPoolExecutor

def _retrieve_by_theme(destination_search, *, query_vector, themes, city_id):
    themes = list(themes)
    if len(themes) <= 1:
        return tuple(
            c for t in themes
            for c in destination_search.search_candidates(query_vector, city_id=city_id, theme=t)
        )
    with ThreadPoolExecutor(max_workers=min(len(themes), 8)) as pool:
        results = pool.map(
            lambda t: destination_search.search_candidates(query_vector, city_id=city_id, theme=t),
            themes,
        )
    return tuple(c for group in results for c in group)
```

### 3-2. 2순위: DynamoDB 상세 보강 (`tools/dynamo_lookup.py: enrich_final_places`)

장소당 `get_detail_item` 순차 호출. 각 GetItem 독립, 결과/경고를 장소별로 모은다 → ThreadPool
병렬화 또는 더 낫게 **`BatchGetItem`(IAM 허용, 가이드 §11)**으로 왕복 N→1. 최종 장소가 보통 한
자릿수라 절대 단축폭은 1순위보다 작다.

## 4. 병렬화 불가/비권장 — 이유 [확인됨]

- **그래프 노드 단위 병렬 불가**: Intent→Evidence→Festival→Planner 데이터 의존. Festival은
  `state.evidence.candidate_evidence_package`를 입력으로 받고(harness `festival_node`), Planner는
  evidence+festival 결과를 모두 쓴다. 동시 실행 불가.
- **노드 내 LLM 호출 fan-out 없음**: reason claim 생성은 후보별 N회가 아니라 **단일 구조화 출력
  호출**로 이미 배치되어 있다(`_attach_candidate_reason_claims`). 추가 병렬 여지 없음.
- **LangGraph 네이티브 fan-out 비권장(현 설계)**: 그래프는 단일 가변 `UnifiedAgentState`를 envelope의
  `state` 키 하나로 전달하며 reducer/channel이 없다. 노드를 병렬 분기시키면 동시 쓰기가 서로를
  덮어쓴다. 그래프 레벨 병렬은 state 채널/리듀서 재설계가 필요한 큰 작업이라 현 단계 비권장
  ([03] "패턴 유지"와 일관).

## 5. 권장 메커니즘과 주의사항 [확인됨 + 추정·중]

- **asyncio가 아니라 `ThreadPoolExecutor`**: boto3는 동기 API. I/O 바운드라 GIL은 네트워크 대기 중
  해제되어 스레드 병렬이 효과적이며 aioboto3 전면 재작성 불필요.
- **boto3 커넥션 풀 상향 필수**: 현재 `boto3_clients.py`는 커스텀 `Config` 없이 클라이언트를 만들어
  기본 `max_pool_connections=10`. 병렬도가 10을 넘으면 커넥션 고갈. `botocore.config.Config(
  max_pool_connections=N)`을 클라이언트 생성에 주입해야 한다. [확인됨]
- **서비스 쿼터/스로틀**: S3 Vectors·Bedrock·DynamoDB TPS 한도. 풀 크기 제한 + `retries.max_attempts`
  (설정 가능)로 백오프. 무제한 fan-out 금지.
- **부분 실패 처리**: 한 테마 호출 실패가 전체를 죽이지 않도록 future 예외를 모아 부분 성공/실패
  정책을 정한다(현재 순차 코드는 첫 오류에서 중단).
- **설정 노출**: `LOVV_SEARCH_MAX_PARALLELISM` 같은 knob 추가 권장(기존 timeouts와 함께).
- **AgentCore와의 관계**: 이 병렬화는 in-process로 동작하며 AgentCore가 추가/제거하는 기능이 아니다.
  AgentCore는 호스팅만, 병렬화는 코드 변경으로 얻는다.

## 6. 요약

| 대상 | 병렬화 | 방식 | 신뢰도 |
| --- | --- | --- | --- |
| 테마별 벡터 검색 | **가능(1순위)** | ThreadPoolExecutor, 풀 크기 제한 | 확인됨/추정·중 |
| DynamoDB 상세 보강 | 가능(2순위) | ThreadPool 또는 BatchGetItem | 확인됨/추정·중 |
| 그래프 노드(Evidence/Festival/Planner) | 불가 | 데이터 의존 | 확인됨 |
| 노드 내 LLM 호출 | 불가(이미 단일 배치) | — | 확인됨 |
| LangGraph 네이티브 fan-out | 비권장 | state 리듀서 재설계 필요 | 확인됨 |

선행 작업 2가지(코드): (1) boto3 `Config(max_pool_connections)` 상향, (2) `_retrieve_by_theme`
ThreadPool 적용. 이 둘만으로 가장 큰 단일 요청 지연 단축을 안전하게 얻는다.
