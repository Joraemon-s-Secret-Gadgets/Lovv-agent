# 02 · us-east-1 파운데이션 모델 선택

기준일: 2026-06-17 · 신뢰도 규칙은 [README](./README.md) 참조.
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
