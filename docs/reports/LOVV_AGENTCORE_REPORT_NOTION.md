# Lovv-agent · AgentCore 전환 종합 보고서 (Notion용)

기준일: 2026-06-17 · 분석 대상: `src/lovv_agent` 현재 코드 + `AGENTCORE_MIGRATION_GUIDE.md`
용도: (1) 기술 의사결정 문서, (2) 발표·리뷰용 요약. 본 파일은 Notion 붙여넣기용 단일 통합본이다.

## 목차

- Part 0 — Executive Summary (발표·리뷰용)
- Part 1 — 성능 병목 & AgentCore 전환 이득
- Part 2 — us-east-1 파운데이션 모델 선택 (context window · rate limit 포함)
- Part 3 — 멀티에이전트 아키텍처 & 구조 외 대안 검토
- Part 4 — 현재 Agent 구조의 병렬 실행 가능성
- Part 5 — AgentCore 전환 계획서 (단계 · 체크리스트)

## 신뢰도 표기 규칙 (전 파트 공통)

- **[확인됨]**: `src/lovv_agent` 코드 또는 공식 문서에서 직접 확인된 사실.
- **[추정·중]**: AgentCore/Bedrock 동작에 근거한 합리적 추론.
- **[추정·낮음]**: 워크로드/측정 데이터가 없어 가정에 의존.

절대 수치(ms, %)는 실측 데이터가 없어 제시하지 않았다. 배포 후 CloudWatch/OTel 측정으로 [추정] 항목을 확정한다.

## 한 줄 결론

**구조는 바꾸지 말고(Supervisor/Hierarchical · 커스텀 검색 · LangGraph 유지) AgentCore 단일 Runtime에 얹은 뒤, 코드 최적화(테마 검색 병렬화 → DynamoDB 배치 → 리랭커 → 캐싱)로 성능을 얻는다.** AgentCore는 발판(관측·런타임·Memory)이고, 큰 이득은 그 위 코드 변경에서 나온다.



---

# Part 0 · Executive Summary (발표·리뷰용)

기준일: 2026-06-17 · 상세 근거는 01~04 보고서 참조.

## 핵심 메시지

현재 Lovv-agent는 단순 순차 실행이 아니라 `SupervisorRouter` + `fulfilled_matrix` 기반으로
**필요한 에이전트만 호출하는 통제된 그래프**다. 방향이 이미 좋으므로 **구조를 갈아엎지 않는다.**
AgentCore Runtime으로 얇게 올리면 콜드스타트·자격증명·관측성·턴 간 재사용에서 이득을 얻고,
**실제 큰 성능 향상은 그 위에서 하는 코드 최적화**(테마 검색 병렬화, DynamoDB 배치, 리랭커,
캐싱)에서 나온다.

## 권고 요약

| 영역 | 권고 | 우선순위 |
| --- | --- | --- |
| 그래프 패턴 | Supervisor/Hierarchical **유지** (단일 AgentCore Runtime in-process) | 유지 |
| 검색 계층 | 커스텀 S3 Vectors/DynamoDB **유지** (도메인 로직) | 유지 |
| 프레임워크 | LangGraph **유지** (Strands/관리형 자율 비추천) | 유지 |
| 테마별 벡터 검색 | 순차 → **병렬(ThreadPool)** | ★ 1 |
| DynamoDB 상세 보강 | 단건 루프 → **BatchGetItem/병렬** | ★ 2 |
| 검색→Planner 품질/토큰 | **Cohere Rerank 3.5** 단계 추가 | ★ 3 |
| LLM 모델 | us-east-1 · structured outputs 지원 모델로 구성 (현재 gpt-oss 유지 가능) | 측정 후 |
| 프롬프트 캐싱 | Claude 채택 시에만 (gpt-oss 미지원) | 조건부 |
| 안전·품질 | AgentCore Policy(Cedar) · Evaluations 채택 | 부가 |

## 비추천 (하지 말 것)

- 에이전트별 분리 호스팅 / 완전 자율 Swarm / 관리형 multi-agent 즉시 이전 → 통제력·비용예측성 저하.
- Knowledge Bases로 검색계층 이전 → 도메인 pruning·스코어링 재현 불가.
- Step Functions/Lambda로 오케스트레이션 분산 → supervisor 중복·지연 증가.

## 모델 구성 핵심 (us-east-1)

- 임베딩 `amazon.titan-embed-text-v2:0` **유지** (us-east-1 In-Region).
- 코드가 **native structured outputs**에 의존 → **Nova 계열 불가**(미지원), 후보는 gpt-oss /
  Qwen3 / DeepSeek / Mistral / Claude 4.5-tier.
- us-east-1에서 최신 Claude는 **`us.` 크로스리전 프로필**로만 호출(직접 ID 실패).
- **Context window는 제약 아님**(후보 모두 ≥128K, Lovv 입력은 그보다 훨씬 작음). **Rate
  limit(RPM/TPM)이 실제 제약** → 노드별 **모델 티어링으로 쿼터 버킷 분산** + 리랭커로 Planner
  토큰 축소. Planner는 DeepSeek-V3.2(164K) 또는 Claude Sonnet 4.6(Geo, 200K) 권장. (상세: [02])

## 권장 적용 순서 (로드맵)

1. 가이드대로 얇게 이관 + 관측성 확보.
2. 관측으로 병목 측정(테마 검색이 1위인지 확인).
3. **테마 검색 병렬화 → DynamoDB 배치** (가장 큰 단일 요청 지연 단축).
4. 리랭커로 top-k 축소(품질·토큰).
5. 멀티턴 많으면 AgentCore Memory + Planner patch 모드.
6. 병목 확인된 tool만 Gateway 외부화.

## 발표 멘트 (예시)

> 현재 구조는 단순 순차 실행이 아니라 `fulfilled_matrix`와 `RoutingState` 기반으로 Supervisor가
> 필요한 에이전트만 호출하는 통제된 그래프입니다. AgentCore로 올리면 런타임·관측·Memory라는
> 발판을 얻고, 실제 성능은 그 위에서 테마별 벡터 검색을 병렬화하고 DynamoDB를 배치 조회하며
> 리랭커로 후보를 정제해 확보합니다. 완전 자율 에이전트로 풀지 않고 통제된 자율형을 유지하므로
> `/recommendations` 응답 계약을 안정적으로 지키면서 비용·성능을 함께 잡을 수 있습니다.

> 신뢰도: 권고의 근거 다수는 코드/공식 문서로 [확인됨], 성능 효과 크기는 측정 전이라 [추정]이다.
> 절대 수치는 배포 후 측정으로 확정한다.


---

# Part 1 · 성능 병목 & AgentCore 전환 이득

기준일: 2026-06-17 · 신뢰도 규칙은 README 참조.
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
의존). 상세: 04 병렬화 보고서.

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


---

# Part 2 · us-east-1 파운데이션 모델 선택

기준일: 2026-06-17 · 신뢰도 규칙은 README 참조.
기준: AWS Bedrock "Regional availability" 및 "Structured outputs" 문서(2026-06 시점 확인).
현재 설정: `LOVV_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0`,
`LOVV_LLM_MODEL_ID=openai.gpt-oss-120b-1:0`, 기본 리전 `us-east-1`.

## 1. 핵심 리전 제약 — 먼저 이해 [확인됨]

Bedrock는 모델마다 us-east-1에서 호출 방식 지원이 다르다.

- **In-Region(직접 modelId)**: `amazon.nova-pro-v1:0`처럼 접두어 없이 호출.
- **Geo 크로스리전 추론 프로필**: `us.` 접두어 필수 (예: `us.anthropic.claude-...`).
- **Global 크로스리전**: `global.` 접두어.

us-east-1에서 **최신 Claude Sonnet 4 / Sonnet 4.6 / Opus 4는 In-Region 직접 호출 불가**,
`us.` 추론 프로필로만 호출된다. 반면 **Nova 계열, Claude Opus 4.8/4.7, Titan Embeddings V2는
In-Region 직접 호출** 가능.

> 함의: `LOVV_LLM_MODEL_ID`에 접두어 없는 `anthropic.claude-sonnet-4-6-...`을 넣으면 us-east-1에서
> 실패한다. 반드시 `us.anthropic.claude-sonnet-4-6-...` 형태를 쓴다.

## 2. 임베딩 모델 [확인됨]

| 모델 | us-east-1 | modelId | 비고 |
| --- | --- | --- | --- |
| Titan Text Embeddings V2 (현재) | In-Region ✓ | `amazon.titan-embed-text-v2:0` | **유지 권장.** 1024/512/256 차원 |
| Amazon Nova Multimodal Embeddings | In-Region ✓ | (모델카드 참조) | 이미지+텍스트 검색 필요 시에만 |

현재 임베딩 설정은 us-east-1에 적합 → 변경 불필요.

## 3. 하드 제약 — 코드가 native structured outputs에 의존 [확인됨, 중요]

LLM 구간 3곳(Intent / reason claim / Planner)은 모두 `adapters/bedrock_converse.py`가 Converse의
**`outputConfig.textFormat`(native structured outputs, JSON schema)**를 만들어 호출한다. 따라서
**모델 후보는 이 기능 지원 모델로 제한된다.**

- **Amazon Nova 계열(Pro/Lite/Micro/Premier)은 native structured outputs 미지원.** Nova를 그대로
  쓰면 실패하거나 우회(strict tool use/constrained decoding)로 **코드 리팩터링 필요**.
- 지원군(앤트로픽 외 포함): **OpenAI gpt-oss, Qwen3, DeepSeek, Mistral(Large 3 / Ministral 3),
  Google Gemma, NVIDIA Nemotron, MiniMax, Moonshot**, 그리고 Claude 4.5-tier(Haiku 4.5 / Sonnet 4.5 /
  Opus 4.5·4.6).
- 크로스리전 추론 프로필(`us.` 등)에서도 structured outputs가 **추가 설정 없이** 동작(공식 문서 확인).

## 4. 다공급사 LLM 후보 (앤트로픽 비한정) [확인됨(지원군) + 추정(리전 직접성)]

코드 수정 없이(=structured outputs 유지) 쓸 수 있는 후보. modelId는 예시, 배포 전
`list-foundation-models`로 확정.

| 역할 | 후보 (다공급사) | modelId 예시 | 강점 | 신뢰도 |
| --- | --- | --- | --- | --- |
| 저비용·대량 (Intent guard, reason code) | gpt-oss-20b / Qwen3-32B / Ministral 3 | `openai.gpt-oss-20b` · `qwen.qwen3-32b` · `mistral.ministral-3-...` | 저비용, structured outputs O | 확인됨(지원)·중(리전) |
| 균형 (현재값 유지) | gpt-oss-120b | `openai.gpt-oss-120b-1:0` | 오픈웨이트, 비용효율, 검증됨 | 확인됨·중 |
| 고품질 추론 (Planner) | DeepSeek-V3.2 / Qwen3-235B / Mistral Large 3 | `deepseek.v3.2` · `qwen.qwen3-235b-a22b-2507` · `mistral.mistral-large-3-675b-instruct` | 강한 추론·tool/agentic | 확인됨(지원)·중 |
| 최고 품질·한국어 우선 | Claude Sonnet 4.5/4.6 (Geo) | `us.anthropic.claude-sonnet-4-6-...:0` | 한국어·추론 최상급, us-east-1은 Geo | 확인됨·중 |

리전 접근: 오픈웨이트는 us-east-1에서 **US 크로스리전 추론 프로필**로 호출 가능(In-Region 직접
여부는 모델별 상이 → 확정 필요). gpt-oss·Qwen3·DeepSeek는 2025-09~10 이후 US 리전 확대.

한국어 품질: 도메인이 한국 관광 + 프롬프트가 한국어라 출력 품질이 중요. 공급사 한국어 벤치마크
부족 → [추정·낮음], **실제 프롬프트로 A/B eval 필수.** 일반적으로 Claude(Geo)·Qwen이 한국어에
강한 편으로 알려져 있으나 반드시 자체 평가로 확인.

권장 조합:
- **코드 변경 없이 비용 최적**: `Intent=gpt-oss-20b`(또는 Qwen3-32B), `reason claim=gpt-oss-20b`,
  `Planner=gpt-oss-120b` 또는 `DeepSeek-V3.2`. 전부 오픈웨이트, structured outputs 유지.
- **한국어 품질 우선**: Planner만 `us.claude-sonnet-4-6`(Geo) 승격, 나머지 오픈웨이트 유지.

## 5. 구성 변경에 필요한 코드 작업 [확인됨]

현재 `config.py: LlmSettings`는 **단일 `model_id`만** 가진다. 노드별 티어링을 하려면 설정 확장
필요(예: `LOVV_LLM_INTENT_MODEL_ID`, `LOVV_LLM_PLANNER_MODEL_ID`). 단일 모델로 시작한다면 현재값
`openai.gpt-oss-120b-1:0` 유지가 가장 안전(검증됨, structured outputs 지원).

권장 env 블록 (단일 모델, 현재값 유지):

```text
LOVV_AWS_REGION=us-east-1
LOVV_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
LOVV_LLM_MODEL_ID=openai.gpt-oss-120b-1:0
```

> Nova로 가려면 별도 작업: `bedrock_converse.py`를 strict tool use 또는 프롬프트 기반 JSON +
> 기존 `schema_retry_limit` 재시도 경로로 변경 필요. 단순 모델 교체로는 불가.

티어링/Claude(Geo) 사용 시 IAM 정책(가이드 §11)은 현재 `Resource:"*"`라 동작하지만, 운영에서
ARN으로 좁힐 땐 **추론 프로필 ARN + 대상 리전 model ARN을 모두** 허용해야 한다.

> 주의: 모델 가용성·modelId는 자주 바뀐다. 배포 전 `aws bedrock list-foundation-models
> --region us-east-1`와 `aws bedrock list-inference-profiles --region us-east-1`로 확정한다.

## 6. Context window & Rate limit 반영 재추천

이 절은 §4 후보를 **context window(컨텍스트 한도)**와 **rate limit(RPM/TPM 쿼터)** 관점에서
다시 평가한다.

### 6-1. Context window — Lovv의 제약 아님 [확인됨(수치) + 추정·중(페이로드)]

| 모델 | context window | output | 신뢰도 |
| --- | --- | --- | --- |
| gpt-oss-120b (현재) | 128K | — | 확인됨 |
| gpt-oss-20b | ~128K | — | 추정·중 |
| Qwen3 (32B/235B/Coder) | ~128K–131K | — | 추정·중 |
| DeepSeek-V3.2 | **164K** | 최대 82K | 확인됨 |
| Mistral Large 3 | 장문 최적화(≈128K+) | — | 추정·중 |
| Claude Sonnet 4.6 (Geo) | 200K (옵션 1M) | — | 확인됨 |
| Claude Haiku 4.5 (Geo) | 200K | — | 추정·중 |

Lovv의 3개 LLM 노드 입력 크기를 보면:
- **Intent**: API payload + 대화 요약 + messages → 작음.
- **reason claim**: 후보 패키지 요약(상위 ~5 장소 / ~3 축제) → 중간.
- **Planner**: 후보 패키지 + 축제 검증 → 가장 크지만, top-k=50이어도 수천~수만 토큰 수준.

→ **모든 후보(≥128K)가 충분한 여유**를 가진다. context window는 모델 선택의 결정 요인이 아니다.
큰 입력은 컨텍스트 오버플로보다 **TPM(분당 토큰) 소모**로 나타나므로, 해결책은 큰 컨텍스트 모델이
아니라 **top-k 축소/리랭커**([03] §2-1)로 입력 토큰을 줄이는 것이다.
(단, 실제 Planner 입력 토큰 크기는 측정으로 확인 권장 [추정·중].)

### 6-2. Rate limit(RPM/TPM) — 실제 제약, 티어링이 유리 [확인됨 + 추정·중]

Bedrock 온디맨드 쿼터는 **모델별·리전별·계정별**로 RPM(분당 요청)과 TPM(분당 토큰)을 두며,
Converse/InvokeModel 계열 호출을 합산한다. 핵심 사실:

- **요청 1건당 LLM 호출이 최대 3구간 × (1+재시도)** 발생([01] §2-3). 단일 요청 내 LLM 호출은
  순차라 RPM 부담이 작지만, **동시 사용자 수가 늘면 RPM/TPM이 곱으로 증가**한다.
- [04]에서 권장한 테마 검색 병렬화는 **S3 Vectors 쿼터**(Bedrock과 별개)라 LLM RPM을 높이지 않는다.
- **모델 티어링이 rate limit에 유리**: 노드마다 다른 모델을 쓰면 각 모델의 **독립 쿼터 버킷**을
  사용하므로, 한 모델 쿼터를 요청당 3번 태우지 않고 부하가 분산된다. (티어링은 비용뿐 아니라
  스로틀 회피에도 이득.) [확인됨(메커니즘)]
- **일부 모델은 RPM 쿼터가 없고 TPM만** 적용된다(예: Claude Opus 4.7/4.8) → 버스트 트래픽에 유리.
- **크로스리전 추론 프로필(`us.`)**은 단일 In-Region보다 throughput을 집계/상향하는 경향 → 오픈웨이트
  모델을 us-east-1에서 `us.` 프로필로 부르면 한도 여유가 늘 수 있다 [추정·중].

### 6-3. 재추천 (context + rate limit 종합)

노드별 배치 — context 여유는 모두 충분하므로 **비용·품질·쿼터 분산** 기준으로 선택:

| 노드 | 추천 모델 | 이유 (context/rate) |
| --- | --- | --- |
| Intent guard | gpt-oss-20b (또는 Qwen3-32B) | 입력 작음, 저비용, 독립 쿼터 버킷 |
| reason claim | gpt-oss-20b / gpt-oss-120b | 중간 입력, 별도 버킷 |
| Planner | **DeepSeek-V3.2**(164K, 저가) 또는 Claude Sonnet 4.6(Geo, 200K) | 입력 최대 노드에 context 여유 큰 모델, DeepSeek는 TPM 단가 낮음 |

운영 권장:
1. **티어링으로 쿼터 분산** — 세 노드를 서로 다른 모델 버킷에 배치(스로틀 회피 + 비용).
2. **Planner 입력 토큰 축소** — 리랭커로 top-k를 줄여 TPM 소모를 직접 낮춤([03] §2-1).
3. **백오프 유지** — 기존 `retries.max_attempts`로 throttling(429) 재시도, 병렬도는 풀로 제한([04]).
4. **쿼터 증설/프로필** — 선택한 Planner 모델의 RPM/TPM을 Service Quotas에서 상향 요청, 오픈웨이트는
   `us.` 크로스리전 프로필 사용.
5. **버스트가 크면** RPM 쿼터가 없는 TPM-only 모델(Claude Opus 4.x) 고려(프리미엄 비용 감수).

> 정확한 RPM/TPM 기본값은 계정·리전별로 다르다. 배포 전 **Service Quotas 콘솔**에서 선택 모델의
> 실제 값을 확인하고, 예상 동시 요청수 × 요청당 LLM 호출수로 필요한 RPM/TPM을 산정한다.


---

# Part 3 · 멀티에이전트 아키텍처 & 구조 외 대안 검토

기준일: 2026-06-17 · 신뢰도 규칙은 README 참조.
목적: 멀티에이전트 패턴 선택과, 현재 구조 외 대안(검색계층/프레임워크/캐싱/리랭킹 등)의
채택·비채택 판단을 제시한다.

## 1. 멀티에이전트 아키텍처 추천

AWS가 제시하는 패턴: A2A(에이전트 간 표준 통신), Supervisor + Sub-agent(LLM 동적 라우팅),
직접 boto3 호출, Hierarchical(계층형), Swarm(완전 자율). AWS-native 구현은 Bedrock multi-agent
collaboration(관리형 supervisor) + AgentCore Runtime(개별 에이전트 호스팅).

### 1-1. 결론: 현재의 Supervisor/Hierarchical 패턴을 단일 Runtime에 유지 [추정·중]

Lovv는 이미 `SupervisorRouter` + `fulfilled_matrix` 기반 **Supervisor(오케스트레이터-워커) 패턴**을
코드로 구현·검증했다. 이 워크로드에 맞는 정답 패턴이며 새 아키텍처로 갈아엎을 이유가 없다.
권장은 **이 그래프를 단일 AgentCore Runtime 안에 in-process 호스팅**하는 것(가이드 §15 "처음엔
in-process, 병목 확인된 tool만 외부화"와 일치).

### 1-2. 하지 말 것 [추정·중]

- **에이전트별 분리 호스팅**(각 agent를 별도 Bedrock Agent/AgentCore Runtime): 네트워크 홉·지연·
  비용 증가. 짧게 끝나는 요청 워크로드엔 손해, 아직 불필요.
- **완전 자율 Swarm**: 라우팅을 LLM에 전적 위임 → 비용 예측성·재현성 저하, `/recommendations`
  응답 계약 위협. 가이드의 계약 우선 원칙과 충돌.
- **관리형 Bedrock multi-agent collaboration으로 즉시 이전**: 검증된 fulfilled_matrix·validation·
  response contract 로직을 관리형 LLM 라우팅에 넘기게 되어 통제력·비용예측성 저하. LangGraph
  supervisor 유지가 유리.

### 1-3. 단계적 확장 경로 [가이드 일치]

1. 단일 AgentCore Runtime + LangGraph supervisor(현 패턴) 이관.
2. 관측성으로 병목 tool 식별.
3. 병목으로 확인된 **그 tool만** AgentCore Gateway 타깃(tool-as-service)으로 외부화(가이드 §15
   후보: Scoring, Matrix Transition, Link Builder, Weather Trends).
4. 멀티턴 비중 크면 AgentCore Memory 추가로 turn 간 재사용.
5. 외부 협업/이종 에이전트 연동이 실제 필요할 때만 A2A/관리형 collaboration 검토.

요약: **패턴은 그대로(Supervisor/Hierarchical), 호스팅만 AgentCore 단일 Runtime, 분리는 관측
데이터가 정당화할 때만 tool 단위로.**

## 2. 현재 구조 외 대안 검토

현재 구조(LangGraph supervisor-router + 커스텀 S3 Vectors/DynamoDB 검색 + 단일 Runtime
lift-and-shift) 기준으로 바꿀 가치가 있는 것과 바꾸지 말 것을 구분한다.

### 2-1. 추천: 리랭커(Cohere Rerank 3.5) 단계 추가 [확인됨(가용) + 추정·중(효과)]

us-east-1에서 `cohere.rerank-v3-5:0` 사용 가능(Amazon Rerank 1.0은 us-east-1 미지원). 적용 위치:
`_retrieve_by_theme` → `prune_cities`/`ScoringTool` 사이. 효과:

- 벡터 검색은 **싸게 많이 가져오고**, 리랭커로 상위만 추려 **Planner 입력 토큰 축소**.
- 거리 기반 단순 정렬보다 의미 적합도가 좋아져 **추천 품질 개선** 가능.
- 비용: 검색당 rerank 1회 추가. top-k 축소의 LLM 토큰 절감과 상쇄 여부는 측정 필요.

판단: 커스텀 스코어링을 **대체가 아니라 보강**. 품질/토큰 둘 다 노리면 1순위 후보.

### 2-2. 추천(조건부): 프롬프트 캐싱 [확인됨(지원모델) + 추정·중(가치)]

Bedrock 프롬프트 캐싱(GA, 1시간 TTL)은 반복 고정 컨텍스트 입력 토큰 최대 90%, 지연 최대 85%
절감. Lovv의 3개 system 프롬프트는 고정·반복이라 적합도 높다.

제약: 지원 모델이 **Claude(Sonnet/Haiku/Opus 4.5)와 Nova로 한정**. 현재 `gpt-oss-120b`는 **미지원**.
Nova는 [02 모델 선택]대로 structured outputs 미지원이라 제외. → "Claude(Geo)+캐싱" 조합의 절감이
gpt-oss 대비 순이득인지 비용 비교 후 결정.

### 2-3. 비추천: 관리형 RAG(Knowledge Bases)로 검색계층 이전 [추정·중~높음]

현재 검색계층은 단순 RAG가 아니라 **도메인 로직**: 테마 AND-gate pruning(`prune_cities`), 축제
시드 선검색(`search_festival_city_seeds`), 커스텀 스코어링, DynamoDB 상세 보강. 관리형 KB는 일반
RAG는 쉽게 주지만 이 도메인 규칙 재현이 어렵다. → **검색계층 커스텀 유지**(리랭커 보강만 §2-1).

### 2-4. 비추천: 프레임워크를 Strands/관리형 자율로 교체 [확인됨(특성) + 추정·중(fit)]

Strands Agents SDK는 model-driven(LLM이 스스로 도구·순서 결정)으로 AWS 통합은 좋지만, Lovv는
**엄격한 `/recommendations` 계약 + `fulfilled_matrix` 검증 + 결정적 라우팅**이 핵심이라 LangGraph의
명시적 그래프 제어가 더 맞는다. → **LangGraph 유지.**

단, 프레임워크 무관하게 **AgentCore GA 구성요소는 채택 가치 있음**:
- **AgentCore Policy(Cedar)**: 국가 혼합 금지·미검증 축제 확정 금지 등을 코드 밖 정책으로(가이드 §15 Policy 후보).
- **AgentCore Evaluations**: 모델/top-k 교체 시 품질 회귀 자동 감시([02] 모델 스왑 위험 완화).

### 2-5. 비추천: Step Functions / 에이전트별 Lambda 분산 [추정·중]

라우팅은 이미 LangGraph supervisor가 결정적으로 처리. Step Functions/Lambda 분리는 동일 기능을
중복 구현하며 네트워크 홉·콜드스타트·지연 증가. 테마 검색 병렬화는 **분산이 아니라 in-process
async/스레드**로 충분([04 병렬화]).

### 2-6. 보류: 기타 추론 비용 레버 [확인됨]

- 배치 추론: 대화형 실시간 워크로드라 부적합.
- Provisioned Throughput: 트래픽 증가 + 지연 SLA가 빡빡할 때만.
- Latency-optimized inference: 지원 모델 한정·효과 제한적 → 측정 후 선택.

### 2-7. 대안 검토 요약

| 대안 | 판단 | 이유 | 신뢰도 |
| --- | --- | --- | --- |
| Cohere Rerank 3.5 추가 | **추천(1순위)** | top-k 축소 + 품질, 커스텀 스코어링 보강 | 확인됨/추정·중 |
| 프롬프트 캐싱 | 조건부 추천 | 고정 프롬프트 절감 크나 Claude/Nova 한정 | 확인됨/추정·중 |
| Knowledge Bases 이전 | 비추천 | 도메인 pruning/스코어링 재현 불가 | 추정·중~높음 |
| Strands/관리형 자율 | 비추천 | 계약·검증·결정적 라우팅엔 LangGraph 적합 | 추정·중 |
| Step Functions 분산 | 비추천 | supervisor 중복·지연 증가 | 추정·중 |
| AgentCore Policy/Evaluations | 추천(부가) | 프레임워크 무관, 안전·품질 회귀 관리 | 확인됨/추정·중 |

종합: **구조 자체는 바꾸지 말 것.** 가치 있는 "구조 외" 추가는 (1) 리랭커로 검색→Planner 최적화,
(2) Claude 채택 시 프롬프트 캐싱, (3) AgentCore Policy/Evaluations 정도. 나머지(KB 이전, 프레임워크
교체, 오케스트레이션 분산)는 현 단계에서 비용·리스크가 이득을 넘는다.


---

# Part 4 · 현재 Agent 구조의 병렬 실행 가능성

기준일: 2026-06-17 · 신뢰도 규칙은 README 참조.
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


---

# Part 5 · AgentCore 전환 계획서 (단계 · 체크리스트)

기준일: 2026-06-17 · 신뢰도 규칙은 README 참조.
목적: 현재 단계(로컬 LangGraph 통제형)에서 **(P1) AgentCore Runtime 이관 → (P2) 로그 기반 tool
외부화 → (P3) 자율형 멀티에이전트 전환**으로 단계적으로 넘어가는 작업을 순서·체크리스트·게이트로
정리한다.

## 0. 전환 개요

```text
현재(P0)            P1                    P2 (log-gated)         P3
로컬 LangGraph  →  AgentCore Runtime  →  병목 tool만 Gateway  →  자율형(관리형
supervisor(통제형)  단일 호스팅(통제형)     외부화(부분 분리)        multi-agent)
```

원칙(전 단계 공통):
- **게이트 통과 후 진행** — 각 단계는 직전 단계의 검증 항목을 모두 통과해야 다음으로 넘어간다.
- **`/recommendations` 응답 계약 불변** — 모든 단계에서 공개 계약을 깨지 않는다.
- **신뢰도/관측 우선** — "추정"으로 결정하지 말고 CloudWatch/OTel 로그로 확인 후 결정한다.
- **롤백 가능** — 각 단계는 직전 상태로 되돌릴 수 있는 경로를 유지한다.

대분류 관점([03] 멀티에이전트 2분류): P1~P2는 **통제형(오케스트레이션)** 유지, P3에서 **자율형
(model-driven)**으로 이동한다. P3는 가장 큰 변경이자 위험 구간이므로 guardrail을 강제한다.

---

## Phase 1 — AgentCore Runtime 이관 (통제형 유지)

목적: 코드/검색/LLM 로직을 바꾸지 않고 `harness.py`를 AgentCore Runtime의 HTTP entrypoint 뒤에
올린다(lift-and-shift). 이 단계의 성능 변화는 콜드스타트·자격증명 수준이고, **핵심 산출물은
관측성 확보**다([01] §3).

### 1-1. 사전 준비 체크리스트

- [ ] `agentcore --version` / `--help`로 현재 CLI 하위 명령 확인(가이드 §3)
- [ ] AWS 자격: Bedrock invoke, S3 Vectors query, DynamoDB read, CloudWatch write, runtime role(가이드 §3)
- [ ] `Lovv-agent` 자체 검증: `uv sync` / `uv run pytest` / `compileall`(가이드 §4)
- [ ] (선택) live smoke: `tests/test_aws_smoke.py`로 실제 리소스 연결 확인(가이드 §4)

### 1-2. 패키징/엔트리 체크리스트

- [ ] `lovv_agent` 패키지를 `app/MyAgent/`로 이식(복사 or wheel), `prompts/*.md` 포함 확인(가이드 §6)
- [ ] `app/MyAgent/pyproject.toml` 최소 의존성 정렬, 불필요 의존성 제거(가이드 §7)
- [ ] `main.py`: payload→`/recommendations` 정규화 + `build_live_harness().invoke()`만 호출(가이드 §8)
- [ ] `main.py`에 OTel/`LangchainInstrumentor` 계측 활성화(= 관측성 확보, [01] §3)
- [ ] 로그에 원문 prompt·raw RAG·credential·PII 미출력 확인(가이드 §8/§16)

### 1-3. 설정 체크리스트 (모델/리전)

- [ ] `agentcore.json` envVars: `LOVV_AWS_REGION=us-east-1`, 임베딩 `amazon.titan-embed-text-v2:0`(가이드 §9, [02] §2)
- [ ] `LOVV_LLM_MODEL_ID`는 structured outputs 지원 모델로 — 시작값 `openai.gpt-oss-120b-1:0` 유지([02] §5)
- [ ] `LOVV_AWS_PROFILE`은 배포 env에서 제외(IAM role 사용, 가이드 §9)
- [ ] 배포 전 `list-foundation-models` / `list-inference-profiles`로 modelId 확정([02] §5)

### 1-4. 배포/검증 게이트 (→ P2 진입 조건)

- [ ] `agentcore dev` 로컬 `/invocations` 호출 성공(가이드 §10)
- [ ] `agentcore deploy --diff`로 의도한 변경만 확인 → `deploy` → `status`(가이드 §11)
- [ ] 배포 Runtime ARN으로 실제 호출 성공, 응답이 `/recommendations` 계약과 일치(가이드 §12/§16)
- [ ] **관측성 동작 확인**: node별 latency, S3 Vectors/DynamoDB/Bedrock 구간이 CloudWatch/OTel에
      기록됨([01] §6) — 이게 P2의 판단 근거이므로 필수
- [ ] Runtime role 권한이 Bedrock/S3 Vectors/DynamoDB에 도달, AccessDenied 없음(가이드 §11/§16)

롤백: 직전 로컬 harness 실행 경로 유지(`scripts/invoke_live_recommendation.py`).

---

## Phase 2 — 로그 기반 tool 외부화 (Gateway, 부분 분리)

목적: P1에서 확보한 관측 로그로 **실제 병목 tool을 식별**하고, **그 tool만** AgentCore Gateway
타깃(tool-as-service)으로 외부화한다. 통제형 구조는 유지한다(가이드 §15, [03] §1-3).

> 핵심: "성급한 외부화 금지". 로그가 정당화하지 않으면 in-process로 둔다(네트워크 홉이 오히려
> 지연을 늘릴 수 있음, [01] §4-5).

### 2-1. 측정 게이트 (외부화 결정 기준)

다음 로그를 1~2주 수집 후 판단:

- [ ] node별 latency 분포에서 상위 병목 노드 식별([01] §6)
- [ ] tool별 호출 횟수·합산 지연: S3 Vectors 쿼리(테마 검색), DynamoDB GetItem, Scoring 등
- [ ] 외부화 후보가 (a) 지연 비중이 크고 (b) 독립 확장이 이득인지 확인
- [ ] **먼저 in-process 최적화로 해결되는지 점검**: 테마 검색 병렬화·DynamoDB 배치([04])로
      해소되면 외부화 불필요

### 2-2. 외부화 작업 체크리스트 (병목 확인된 tool만)

가이드 §15 후보: Scoring, Matrix Transition, Link Builder, Weather Trends.

- [ ] 대상 tool의 입출력 계약을 Gateway 타깃 인터페이스로 고정(순수 함수 경계 유지)
- [ ] 인증/권한은 AgentCore Identity로 위임(가이드 §15)
- [ ] 외부화 전/후 동일 입력에 대한 출력 동등성 테스트(회귀 방지)
- [ ] 외부화 후 end-to-end 지연이 **개선됐는지** 로그로 재확인(악화 시 롤백)

### 2-3. 게이트 (→ P3 진입 조건)

- [ ] 외부화한 tool이 계약 동등 + 지연 개선(또는 확장성 확보)으로 검증됨
- [ ] in-process 최적화([04] 병렬화/배치)가 먼저 적용되어 baseline이 안정화됨
- [ ] (멀티턴 비중 크면) AgentCore Memory 도입으로 turn 간 재사용 확인([01] §4, [03] §1-3)

롤백: Gateway 타깃을 in-process 호출로 되돌리는 feature flag 유지.

---

## Phase 3 — 자율형(관리형 multi-agent) 전환

목적: [03] 2분류의 **자율형(model-driven)**으로 이동 — Bedrock 관리형 multi-agent collaboration
등에서 LLM이 라우팅/위임을 결정. 외부·이종 에이전트 협업이 실제로 필요해질 때의 단계다.

> ⚠️ 위험 고지 [확인됨/추정·중]: 자율형은 비용 예측성·재현성·`/recommendations` 계약 안정성을
> 떨어뜨린다([03] §1-2). **따라서 P3는 "필요해질 때만", 그리고 guardrail 강제 하에서만** 진행한다.
> 통제형으로 충분하면 P2에서 멈추는 것이 정답일 수 있다.

### 3-1. 진입 조건 (모두 충족 시에만)

- [ ] 외부/이종 에이전트 연동, 동적 협업 등 **통제형으로 불가능한 요구**가 실재함
- [ ] P1·P2 게이트 통과 + 안정적 baseline 로그 확보
- [ ] guardrail 인프라 준비: **AgentCore Policy(Cedar)** + **Evaluations**([03] §2-4)

### 3-2. 안전한 점진 전환 체크리스트

- [ ] **계약 방어선 유지**: 자율 라우팅을 도입해도 `fulfilled_matrix` 검증·Response Packager·
      Validation은 그대로 남겨 최종 출력 계약을 강제
- [ ] **Policy 강제**: 국가 혼합 금지·미검증 축제 확정 금지·raw trace 저장 금지를 Cedar 정책으로
- [ ] **shadow / A-B 전환**: 자율형을 트래픽 일부에만 적용해 통제형과 품질·비용·지연 비교
- [ ] **Evaluations 회귀 감시**: trajectory·조건 충족·근거성·일정 구조를 자동 평가([03] §2-4)
- [ ] **비용/쿼터 가드**: 자율 루프의 LLM 호출 폭증 대비 max 호출수·예산 한도·RPM/TPM 모니터([02] §6)

### 3-3. 완료 게이트

- [ ] 자율형이 통제형 대비 품질 동등 이상 + 계약 위반 0건(Evaluations 기준)
- [ ] 비용/지연이 허용 범위, 쿼터 스로틀 없음
- [ ] 미달 시 통제형으로 롤백(P2 상태 유지)

롤백: P3는 항상 P2(통제형) 구성으로 되돌릴 수 있는 라우팅 스위치를 유지한다.

---

## 단계 게이트 요약

| 단계 | 핵심 작업 | 진입 조건 | 완료(게이트) | 분류 |
| --- | --- | --- | --- | --- |
| P1 | Runtime 이관 + 관측성 | — | 배포 호출 성공 + 계약 일치 + 관측 동작 | 통제형 |
| P2 | log 기반 tool 외부화 | P1 게이트 | 병목 tool 외부화 검증 + baseline 안정 | 통제형(부분 분리) |
| P3 | 자율형 전환 | 통제형 불가 요구 + guardrail 준비 | 품질 동등↑ + 계약 위반 0 + 비용 허용 | 자율형 |

## 공통 운영 체크리스트 (전 단계)

- [ ] 배포 전: unit/integration 테스트, `compileall`, `deploy --diff` 확인(가이드 §16)
- [ ] 로그 위생: credential·raw RAG·raw web·PII 원문 미기록(가이드 §16)
- [ ] 각 단계 롤백 경로 확보 후 진행
- [ ] [추정] 항목은 로그 측정으로 [확인됨] 승격/기각([01] §6)

## 권장 우선순위 (요약)

1. **P1 이관 + 관측성** — 지금 바로.
2. **in-process 최적화** 병행([04] 테마 검색 병렬화 → DynamoDB 배치, [03] 리랭커) — P2 판단 baseline.
3. **P2 tool 외부화** — 로그가 병목을 가리킬 때만, 그 tool만.
4. **P3 자율형** — 통제형으로 불가능한 요구가 생길 때만, Policy/Evaluations guardrail 하에서.
