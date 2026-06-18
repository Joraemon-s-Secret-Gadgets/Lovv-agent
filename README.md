# Lovv Agent

Lovv의 소도시 여행 추천 workflow를 LangGraph로 구현한 Python 3.12 프로젝트입니다.
현재 구현은 API 형태의 입력을 받아 실제 AWS 검색 및 LLM 호출을 수행하고,
`/recommendations` 계약에 맞춘 추천 도시와 일정을 반환합니다.

이 저장소가 graph와 추천 business workflow를 소유하며, AWS AgentCore Runtime은
향후 이 package를 실행하는 serving wrapper와 runtime harness로 연결할 예정입니다.

## Current Scope

- 실제 `langgraph.graph.StateGraph` 기반 Supervisor workflow
- API structured input을 보존하는 Intent Agent
- Amazon Bedrock Converse 기반 structured output 및 한국어 prompt
- Bedrock embedding과 S3 Vector 기반 관광지 검색
- DynamoDB 기반 최종 일정 항목 detail 보강
- Candidate Evidence 구성, 도시 선택, scoring audit
- Planner 일정 배치와 사용자용 추천/일정 근거 생성
- `/recommendations` 응답 형태로 변환하는 deterministic Response Packager
- boto3 credential chain을 사용하는 local live harness

축제 workflow의 계약과 기본 구조는 포함되어 있지만, 실제 데이터와 운영 조건에
따른 추가 검증이 필요합니다. AgentCore 배포 설정과 memory 연동은 아직 포함하지
않습니다.

## Workflow

```text
API request
  -> Intent Agent
  -> Supervisor
  -> Candidate Evidence Agent
       -> Bedrock Embedding
       -> S3 Vector retrieval
       -> city grouping/scoring
       -> candidate reason claims
  -> Supervisor
  -> Festival Verifier (when requested)
  -> Supervisor
  -> Planner Agent
       -> final itinerary placement
       -> DynamoDB detail enrichment
       -> Bedrock copy/explanation generation
  -> Supervisor
  -> Response Packager
  -> API response
```

Supervisor routing은 현재 deterministic state transition을 기본으로 합니다. 이는
LLM이 검색 결과나 일정 상태를 임의로 변경하지 않도록 하기 위한 현재 MVP 선택이며,
추후 LLM Supervisor 비교 E2E 테스트를 추가할 수 있습니다.

## Requirements

- Python `3.12.x`
- [uv](https://docs.astral.sh/uv/)
- live 실행 시 접근 가능한 AWS credential과 다음 서비스 권한
  - Amazon Bedrock Runtime
  - Amazon S3 Vectors
  - Amazon DynamoDB

Python 버전은 `.python-version`과 `pyproject.toml`에서 3.12로 고정합니다.

## Setup

```powershell
uv sync
```

AWS credential은 코드나 환경 파일에 직접 넣지 않습니다. boto3의 기본 credential
chain을 사용하므로 AWS CLI profile, environment credential 또는 IAM role을 사용할
수 있습니다.

## Runtime Configuration

live graph 실행에 필요한 최소 설정 예시입니다. 실제 resource와 model ID로
변경하세요.

```powershell
$env:LOVV_AWS_REGION = "us-east-1"
$env:LOVV_AWS_PROFILE = "lovv-dev" # IAM role 또는 기본 profile 사용 시 생략 가능
$env:LOVV_S3_VECTOR_BUCKET = "your-vector-bucket"
$env:LOVV_S3_VECTOR_INDEX = "your-vector-index"
$env:LOVV_DYNAMODB_TABLE = "your-domain-table"
$env:LOVV_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
$env:LOVV_LLM_MODEL_ID = "your-bedrock-model-or-inference-profile-id"
```

검색 budget, timeout, retry 정책도 환경 변수로 조정할 수 있습니다.

| Variable | Default | Purpose |
| --- | ---: | --- |
| `LOVV_INTENT_MIN_NATURAL_LANGUAGE_QUERY_CHARS` | `5` | 짧은 자연어 입력의 LLM Intent 호출 생략 기준 |
| `LOVV_SEARCH_PER_THEME_TOP_K` | `24` | 테마별 관광지 검색 budget |
| `LOVV_SEARCH_RAW_SOFT_TOP_K` | `12` | raw/soft query channel 검색 budget |
| `LOVV_MAX_FESTIVAL_SEED_CANDIDATES` | `30` | 축제 seed 후보 상한 |
| `LOVV_VERIFIER_CANDIDATE_K` | `5` | 축제 verifier 후보 상한 |
| `LOVV_CONNECT_TIMEOUT_SECONDS` | `3.0` | 연결 timeout |
| `LOVV_READ_TIMEOUT_SECONDS` | `15.0` | read timeout |
| `LOVV_MAX_RETRY_ATTEMPTS` | `2` | runtime 호출 재시도 상한 |
| `LOVV_SCHEMA_RETRY_LIMIT` | `2` | LLM structured output 재시도 상한 |

## Live Invocation

다음과 같은 `/recommendations` 형태의 JSON 파일을 준비합니다.

```json
{
  "entryType": "chat",
  "destinationId": null,
  "country": "KR",
  "travelYear": 2026,
  "travelMonth": 10,
  "tripType": "2d1n",
  "themes": ["sea_coast", "nature_trekking"],
  "includeFestivals": false,
  "naturalLanguageQuery": "조용한 바다와 산책로가 있는 소도시를 추천해 주세요.",
  "userLocation": null
}
```

파일을 사용해 전체 graph를 호출합니다.

```powershell
uv run python scripts/invoke_live_recommendation.py --input request.json
```

표준 입력도 지원합니다.

```powershell
Get-Content request.json | uv run python scripts/invoke_live_recommendation.py
```

실행 결과는 추천 목적지, 일차별 일정, 추천 근거, 일정 흐름 설명 및 외부 링크를
포함한 public JSON입니다. 내부 score, AWS key, raw retrieval payload는 응답에서
제외됩니다.

## Theme Codes

API 입력의 canonical theme code는 다음과 같습니다.

| Code | Internal label |
| --- | --- |
| `sea_coast` | 바다·해안 |
| `nature_trekking` | 자연·트레킹 |
| `food_local` | 미식·노포 |
| `history_tradition` | 역사·전통 |
| `art_sense` | 예술·감성 |
| `healing_rest` | 온천·휴양 |

`includeFestivals`는 theme이 아닌 별도 boolean입니다.

## Test

전체 unit/integration test를 실행합니다.

```powershell
uv run pytest
```

Python source compile 검증:

```powershell
uv run python -m compileall src tests
```

선택적 live AWS smoke test는 명시적으로 활성화해야 합니다.

```powershell
$env:LOVV_ENABLE_AWS_SMOKE = "1"
uv run pytest tests/test_aws_smoke.py
```

일반 test suite는 실제 AWS credential 없이 mocked adapter로 실행됩니다.

## Project Layout

```text
src/lovv_agent/
  adapters/       AWS, Bedrock 및 runtime adapter
  agents/         Intent, Candidate Evidence, Festival Verifier, Planner
  models/         agent 간 schema와 contract
  prompts/        versioned Korean prompt assets
  repositories/   S3 Vector와 DynamoDB repository boundary
  tools/          retrieval, scoring, validation, explanation, packaging
  graph.py        LangGraph node 및 Supervisor routing
  harness.py      API 입력부터 live graph 실행까지의 composition root
scripts/          local live invocation CLI
tests/            unit, integration 및 optional AWS smoke test
docs/specs/       구현 SPEC
docs/tasks/       구현 task와 subtask 결과
```

## Design Documents

- [LangGraph SPEC Authoring Instructions](./LANGGRAPH_SPEC_AUTHORING_INSTRUCTIONS.md)
- [Lovv LangGraph Agent Implementation SPEC](./docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md)
- [Lovv LangGraph Agent Implementation Tasks](./docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md)
- [설계 대비 구현 현황 및 한계](./docs/LOVV_AGENT_IMPLEMENTATION_COMPARISON.md)

Task별 구현 결과는 [`docs/tasks/results`](./docs/tasks/results/)에서 확인할 수
있습니다.

## AgentCore Migration

현재 `src/lovv_agent/harness.py`가 local/live composition root 역할을 합니다.
AgentCore migration에서는 추천 로직을 다시 작성하기보다 이 package의 graph invoke
경계를 AgentCore entrypoint에 연결하는 방향을 사용합니다. 배포 manifest, runtime
entrypoint, observability, memory 정책은 기존 workflow 검증 이후 별도 SPEC과 task로
추가합니다.

현재 AgentCore v1 adapter는 기존 구조를 유지하면서 다음 경계만 추가합니다.

- `app/LovvAgentV1/main.py`: AgentCore CodeZip runtime entrypoint
- `src/lovv_agent/agentcore_entrypoint.py`: AgentCore/HTTP wrapper payload를
  `/recommendations` request로 정규화하고 `build_live_harness().invoke(...)` 호출
- `agentcore/agentcore.json`: schema `version`을 `1`로 고정하고 runtime 이름을
  `LovvAgentV1`로 명시
- `agentcore/aws-targets.example.json`: `default` target 대신 `v1` target을 쓰기 위한
  예시. 실제 계정 값으로 `agentcore/aws-targets.json`을 만들되 이 파일은 git에
  커밋하지 않습니다.

AgentCore CLI가 설치된 환경에서는 실제 계정 정보를 채운 뒤 다음 흐름으로 검증합니다.

```powershell
Copy-Item agentcore/aws-targets.example.json agentcore/aws-targets.json
# agentcore/aws-targets.json의 account를 실제 12자리 AWS account id로 변경
agentcore validate
agentcore dev --runtime LovvAgentV1
agentcore deploy --target v1 --diff
agentcore deploy --target v1
```
