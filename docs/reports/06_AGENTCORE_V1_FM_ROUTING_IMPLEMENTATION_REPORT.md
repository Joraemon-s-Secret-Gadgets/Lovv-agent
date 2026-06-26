# 06 · AgentCore V1 FM Routing 구현 결과 보고서

기준일: 2026-06-22
작업 브랜치: `agentcore-v1-migration`
대상: `LovvAgentV1` 단일 AgentCore Runtime · per-agent Foundation Model routing

## 1. 작업 개요

이번 작업은 기존 AgentCore 전환 계획의 P1 방향을 유지하면서, Runtime을 분리하지 않고
단일 `LovvAgentV1` 안에서 Intent, Candidate Evidence, Planner, Supervisor별 Foundation Model
설정을 분리할 수 있도록 만든 구현 작업이다.

핵심 결정:

- `LovvAgentV1` Runtime은 하나로 유지한다.
- `LOVV_LLM_MODEL_ID`는 전역 fallback으로 유지한다.
- LLM을 쓰는 agent/node별 optional model env var를 추가한다.
- Gateway는 V1 목표가 아니라 이후 additive phase로 유지한다.
- S3 Vectors와 DynamoDB retrieval은 Gateway 뒤로 옮기지 않고 in-process로 유지한다.

## 2. GitHub Issue 등록 결과

`origin` 저장소(`nobrain711/Lovv-agent`)는 GitHub Issues가 비활성화되어 있어, 팀 원격으로 쓰는
`upstream` 저장소(`Joraemon-s-Secret-Gadgets/Lovv-agent`)에 task별 issue를 등록했다.

| Issue | 제목 | 상태 |
| --- | --- | --- |
| [#1](https://github.com/Joraemon-s-Secret-Gadgets/Lovv-agent/issues/1) | `[AgentCore V1] Audit Task 10.5 memory-safe summary gap` | Open |
| [#2](https://github.com/Joraemon-s-Secret-Gadgets/Lovv-agent/issues/2) | `[AgentCore V1] Break FM routing spec into implementation tasks` | Open |
| [#3](https://github.com/Joraemon-s-Secret-Gadgets/Lovv-agent/issues/3) | `[AgentCore V1] Add per-agent LLM routing config and resolver` | Open |
| [#4](https://github.com/Joraemon-s-Secret-Gadgets/Lovv-agent/issues/4) | `[AgentCore V1] Wire per-agent runtime invokers into harness` | Open |
| [#5](https://github.com/Joraemon-s-Secret-Gadgets/Lovv-agent/issues/5) | `[AgentCore V1] Sync deployment config and vendored runtime` | Open |
| [#6](https://github.com/Joraemon-s-Secret-Gadgets/Lovv-agent/issues/6) | `[AgentCore V1] Verify FM routing and AgentCore validation gates` | Open |
| [#7](https://github.com/Joraemon-s-Secret-Gadgets/Lovv-agent/issues/7) | `[AgentCore V1] Preserve Gateway additive-phase boundaries` | Open |

각 issue에는 로컬 구현 결과와 검증 결과를 comment로 남겼다. Issue는 PR/merge 전 추적용으로
open 상태를 유지했다.

## 3. 구현 결과

### 3-1. Task 문서화

추가 문서:

- `docs/tasks/LOVV_AGENTCORE_V1_FM_ROUTING_TASKS.md`
- `docs/tasks/results/TASK10_SUBTASK05_RESULT.md`
- `docs/tasks/results/AGENTCORE_V1_FM_ROUTING_RESULT.md`

`TASK10_SUBTASK05_RESULT.md`는 기존 LangGraph task plan에서 빠져 있던 Task 10.5 결과 문서다.

### 3-2. Memory-safe summary boundary

`src/lovv_agent/state.py`에 `build_memory_safe_summary(state)`를 추가했다.

이 summary는 future AgentCore Memory 연동을 위한 opt-in 경계이며, 기본적으로 persistence를
수행하지 않는다.

포함하는 정보:

- `recommendation_request_id`
- `agent_run_id`
- compact request summary
- compact serving summary
- memory policy marker

제외하는 정보:

- raw evidence
- full Candidate Evidence Package
- raw web/RAG payload
- natural-language query 원문
- user location
- detailed itinerary body
- secrets / credential / PII

### 3-3. Per-agent LLM routing config

`src/lovv_agent/config.py`에 agent별 model/adapter 설정을 추가했다.

추가된 model env vars:

```text
LOVV_INTENT_LLM_MODEL_ID
LOVV_CANDIDATE_EVIDENCE_LLM_MODEL_ID
LOVV_PLANNER_LLM_MODEL_ID
LOVV_SUPERVISOR_LLM_MODEL_ID
```

추가된 optional adapter env vars:

```text
LOVV_INTENT_LLM_ADAPTER_ID
LOVV_CANDIDATE_EVIDENCE_LLM_ADAPTER_ID
LOVV_PLANNER_LLM_ADAPTER_ID
LOVV_SUPERVISOR_LLM_ADAPTER_ID
```

Resolver 규칙:

1. agent-specific model id가 있으면 그것을 사용한다.
2. 없으면 `LOVV_LLM_MODEL_ID`를 fallback으로 사용한다.
3. live LLM 경로에서 model이 해석되지 않으면 명확한 config error로 실패한다.

### 3-4. Runtime invoker 주입

`src/lovv_agent/adapters/aws_runtime.py`에서 node별 Converse runtime map을 구성하도록 변경했다.

`src/lovv_agent/harness.py`에서는 LLM 사용 경로를 분리 주입한다.

| Graph path | Runtime source |
| --- | --- |
| Intent structured output | `intent` runtime |
| Candidate Evidence reason claim | `candidate_evidence` runtime |
| Planner explanation/copy | `planner` runtime |
| Supervisor | optional config만 준비, V1 기본은 deterministic |

### 3-5. AgentCore deployment sync

AgentCore 배포 패키지 경로인 `app/LovvAgentV1/lovv_agent/`에 canonical source 변경을 동기화했다.

동기화 대상:

- `config.py`
- `state.py`
- `adapters/aws_runtime.py`
- `harness.py`

`agentcore/agentcore.json`에는 V1 routing env vars를 추가했다. 현재 값은 기존 global fallback인
`openai.gpt-oss-120b-1:0`와 동일하게 두었다. 최종 production model ID 선택은 별도 live
availability 및 structured-output smoke 확인 후 결정한다.

## 4. 검증 결과

실행한 검증:

```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_harness.py -k "memory_safe" -q
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_config.py tests/test_harness.py -q
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest -q
$env:UV_CACHE_DIR='.cache\uv'; uv run python -m compileall src tests app\LovvAgentV1
agentcore validate --json
$env:UV_CACHE_DIR='D:\bootcamp\workspace\project\03_final\04_Lovv-agent\.cache\uv'; agentcore deploy --target v1 --dry-run --json
```

결과:

```text
memory_safe: 1 passed, 12 deselected
focused config/harness: 25 passed
full pytest: 212 passed, 1 skipped, 2 subtests passed
compileall: passed
agentcore validate: {"success":true}
agentcore deploy dry-run: {"success":true,"targetName":"v1","stackName":"AgentCore-LovvAgentCore-v1"}
```

주의:

- 첫 dry-run은 CDK synth child process가 user-global uv cache에 접근하면서 Windows access denied로
  실패했다.
- 절대경로 workspace-local `UV_CACHE_DIR`를 지정해 재실행하자 dry-run이 성공했다.
- pytest는 `.pytest_cache` write warning을 냈지만 테스트 실행 자체는 통과했다.

## 5. 변경 파일 요약

주요 코드:

- `src/lovv_agent/config.py`
- `src/lovv_agent/state.py`
- `src/lovv_agent/adapters/aws_runtime.py`
- `src/lovv_agent/harness.py`
- `app/LovvAgentV1/lovv_agent/config.py`
- `app/LovvAgentV1/lovv_agent/state.py`
- `app/LovvAgentV1/lovv_agent/adapters/aws_runtime.py`
- `app/LovvAgentV1/lovv_agent/harness.py`

설정:

- `agentcore/agentcore.json`
- `.gitignore`

테스트:

- `tests/test_config.py`
- `tests/test_harness.py`

문서:

- `docs/specs/v1/LOVV_AGENTCORE_V1_FM_ROUTING_SPEC.md`
- `docs/tasks/LOVV_AGENTCORE_V1_FM_ROUTING_TASKS.md`
- `docs/tasks/results/TASK10_SUBTASK05_RESULT.md`
- `docs/tasks/results/AGENTCORE_V1_FM_ROUTING_RESULT.md`
- `docs/reports/06_AGENTCORE_V1_FM_ROUTING_IMPLEMENTATION_REPORT.md`

## 6. 현재 남은 결정 사항

아직 확정하지 않은 항목:

- 첫 배포용 concrete model ID 세트
- `us-east-1`에서 각 model/profile의 structured-output smoke 결과
- Supervisor에 LLM runtime을 실제 production path로 연결할지 여부
- Gateway 첫 tool을 `LinkBuilder`로 할지 `ScoringTool`로 할지

권장 다음 순서:

1. 현재 변경분을 commit/PR로 묶는다.
2. `us-east-1`에서 후보 모델별 structured-output smoke를 실행한다.
3. dry-run이 아니라 실제 `agentcore deploy --target v1 --diff`로 변경 범위를 확인한다.
4. 배포 후 CloudWatch/OTel에서 model routing, latency, AccessDenied, structured-output 실패 여부를 확인한다.
5. Gateway는 병목 로그가 쌓인 뒤 별도 phase로 진행한다.
