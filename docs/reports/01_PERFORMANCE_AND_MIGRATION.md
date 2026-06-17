# 01 · 성능 병목 & AgentCore 전환 이득

기준일: 2026-06-17 · 신뢰도 규칙은 [README](./README.md) 참조.
목적: 현재 코드의 성능 병목, AgentCore 전환이 주는 이득, 코드 개선 항목, 측정 검증을 정리한다.

## 1. 핵심 요약

**AgentCore Runtime으로 "얇게 올리는 것" 자체는 그래프 연산을 빠르게 만들지 않는다.**
가이드 설계대로 `harness.py`를 HTTP entrypoint 뒤에 붙이는 lift-and-shift이므로 노드 로직·검색
횟수·LLM 호출 횟수는 동일하다. 성능 향상은 두 갈래다.

1. **AgentCore 플랫폼이 직접 주는 향상** — 콜드스타트/연결 재사용, 자격증명 경로 단축, 관측성
   기반 병목 식별, Memory를 통한 턴 간 재계산 제거.
2. **마이그레이션이 가능하게/측정 가능하게 만드는 코드 개선** — 직렬 I/O 루프를 병렬화/배치/캐시로
   전환. 가장 큰 지연 단축이 여기서 나오며, 코드 변경이 필요하다.

요약: **AgentCore = 발판(관측+런타임+Memory), 큰 성능 이득 = 그 위의 코드 최적화.**

## 2. 현재 구조에서 확인된 성능 병목

모두 현재 `src/lovv_agent` 코드에서 직접 확인.

### 2-1. 테마별 직렬 벡터 검색 — 최대 병목 후보 [확인됨]

`agents/candidate_evidence.py`의 `_retrieve_by_theme`:

```python
for theme in themes:
    candidates.extend(
        destination_search.search_candidates(query_vector, city_id=city_id, theme=theme)
    )
```

테마 1개당 S3 Vectors `QueryVectors` 네트워크 왕복 1회를 **순차로** 수행. 활성 테마 N개면
지연 ≈ (단일 쿼리 지연 × N). 테마가 3~5개로 늘면 후보 수집 지연을 선형으로 키운다.

### 2-2. 최종 장소 상세 보강(DynamoDB)도 직렬 [확인됨]

`tools/dynamo_lookup.py`의 `enrich_final_places`는 최종 일정 장소 수만큼 `get_detail_item`을
순차 호출한다. `BatchGetItem` 권한은 IAM 정책 예시에 이미 있으나(가이드 §11) 코드는 단건 루프.

### 2-3. LLM 구조화 출력 호출 (직렬 + 재시도) [확인됨]

Bedrock Converse 구조화 출력 호출이 3곳: Intent 정규화(`harness.py`), Candidate reason claim,
Planner 설명 생성. `adapters/bedrock_converse.py`는 `for attempt in range(1, retry_limit + 2)`로
스키마 실패 시 재호출(`schema_retry_limit` 기본 2). 한 요청 안에서 최대 (1+재시도)×3 구간이
순차 발생. LLM 호출이 보통 전체 지연의 최대 단일 항목이다 [추정·중].

### 2-4. 임베딩 단건 호출, 캐시 없음 [확인됨]

`adapters/embeddings.py`의 `embed_query`는 쿼리 1건 임베딩만 지원(배치 없음). 임베딩/벡터결과
캐시가 없어 동일·유사 요청도 매번 재계산.

### 2-5. 콜드스타트 / 클라이언트 생성 비용 [확인됨 + 추정]

`build_live_harness` → `create_boto3_client_factory`에서 boto3 `Session`과 서비스 클라이언트를
생성. `main.py`(가이드 §8)의 전역 `_harness` 메모이즈로 **웜 호출 시 재사용**되므로 콜드스타트
(첫 호출)에서만 생성+계측 비용 발생 [확인됨]. 절대값은 측정 필요 [추정·낮음].

### 2-6. 프롬프트 파일 I/O [확인됨, 영향 작음]

`pyproject.toml`이 `prompts/*.md`를 `force-include`하고 런타임에 읽는다. 가이드 §6은 문자열
inline 권장. 호출당 영향은 작지만 콜드스타트에 미세하게 더해진다.

## 3. AgentCore 플랫폼이 "직접" 주는 향상 (코드 변경 없음)

| 향상 지점 | 무엇이 좋아지나 | 근거/메커니즘 | 신뢰도 |
| --- | --- | --- | --- |
| 웜 컨테이너 재사용 | 콜드스타트 빈도↓, 세션/클라이언트/계측 비용 절감 | microVM 유지 + `_harness` 전역 메모이즈 | 추정·중 |
| 자격증명 경로 단축 | 로컬 profile STS 해석 제거, IAM role 직접 | 가이드 §9, `LOVV_AWS_PROFILE`은 배포 env 제외 | 추정·중 |
| 관측성(OTel/CloudWatch) | 병목 정량화 → 최적화 우선순위 확정 | 가이드 §8 `LangchainInstrumentor`, §15 | 확인됨(설정)·중(효과) |
| 네트워크 근접성 | 같은 리전(us-east-1) 실행 → 왕복 지연↓ | 가이드 §9 리전 고정 | 추정·중 |
| Memory(턴 간 재사용) | 후속 턴 재계산 제거 | 가이드 §13 요약 재사용 | 추정·중 |

**한계**: 위 어느 것도 §2-1(직렬 검색)·§2-2(직렬 GetItem)를 자동 병렬화하지 않는다. 플랫폼
이득은 *호출당 고정비용*과 *턴 간 재사용*에서 나오며 *단일 요청 내부 연산 지연*은 그대로다 [추정·중].

## 4. 마이그레이션이 "가능하게" 하는 코드 개선 (실질적 큰 이득)

### 4-1. 테마별 벡터 검색 병렬화 — 우선순위 1 [추정·중]

§2-1 루프를 `ThreadPoolExecutor`로 동시 실행. 후보 수집 지연을 약 1/N로 단축(N·동시성 한도에
의존). 상세: [04 병렬화 보고서](./04_PARALLELIZATION.md).

### 4-2. DynamoDB 상세 보강 배치화 — 우선순위 2 [추정·중]

§2-2 단건 루프를 `BatchGetItem`(IAM 허용)으로. 왕복 N→1(최대 100/배치).

### 4-3. 임베딩/벡터결과 캐시 [추정·중]

같은 정규화 쿼리 임베딩을 **프로세스 내부** 캐시(LRU). 가이드 §13은 raw embedding/vector의
Memory 저장 금지 → Memory에는 요약만.

### 4-4. LLM 호출 최소화 [추정·낮음]

(a) 짧은 쿼리 deterministic 경로 확대(이미 `intent` 노드에 `min_natural_language_query_chars`
존재), (b) `schema_retry_limit` 재시도 잦은 프롬프트 교정. 효과는 워크로드 의존 → 측정 후.

### 4-5. Gateway 외부화는 "나중에" [가이드 일치]

가이드 §15: 초기엔 in-process, 관측으로 병목 확인된 tool부터 외부화. 성급한 외부화는 네트워크
홉을 늘려 지연 증가.

## 5. 권장 적용 순서

1. 가이드대로 얇게 이관(§4~§12) — 기능 동등성 + 관측성. 이 단계 성능 변화는 콜드스타트/자격증명 수준.
2. 관측성으로 병목 측정 — 여기서 §2-1이 실제 1위인지 확인.
3. 테마 검색 병렬화(§4-1) → DynamoDB 배치(§4-2) — 가장 큰 단일 요청 지연 단축.
4. Memory 도입 — 턴 간 재계산 제거(멀티턴 체감).
5. 캐시·LLM 튜닝(§4-3, §4-4) — 측정 기반 미세 조정.
6. Gateway 외부화(§4-5) — 병목 확인된 tool만.

## 6. 측정 검증 체크리스트 (배포 후)

가이드 §16 운영 체크리스트에 더해 CloudWatch/OTel로 확인:

- node별 latency 분포: `intent` / `candidate_evidence` / `festival` / `planner` / `response_packager`
- `candidate_evidence` 내 S3 Vectors 쿼리 횟수·합산 지연 (= §2-1 검증)
- `enrich_final_places`의 GetItem 횟수·합산 지연 (= §2-2 검증)
- Bedrock Converse 호출 수·token·retry 횟수 (= §2-3 검증)
- 콜드스타트 vs 웜 호출 지연 차 (= §2-5/§3 검증)
- Memory on/off 시 후속 턴 지연 차 (= §4-3 검증)
