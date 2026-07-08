# LOVV V2 Observability Test Guide

작성일: 2026-07-08

이 문서는 V2 live harness 실행 후 observability 로그를 수집하고, 결과 파일을 분석하는 절차를 정리한다. 대상은 `src/lovv_agent_v2` 및 배포 mirror `app/LovvAgentV2`에 적용된 V2 observability이다.

## 1. 관측 대상

V2 runtime은 실행 중 아래 JSON line 로그를 stdout/CloudWatch에 출력한다.

| logType | 의미 | 주요 확인값 |
| --- | --- | --- |
| `AGENT_NODE_METRIC` | LangGraph node/내부 step 실행 시간 | `nodeName`, `durationMs`, `status`, `inputSummary`, `outputSummary` |
| `AGENT_INVOCATION_METRIC` | 요청 1건 전체 실행 시간 | `durationMs`, `status`, `responseStatus`, `toolMetrics`, `traceSummary` |
| `AGENT_LIFECYCLE_METRIC` | 사용자 흐름 상태 | `lifecycleType=modify/weather/clarification`, `event`, `details` |
| `AGENT_MEMORY_GUARD` | memory/checkpointer 비용 위험 guard | `memorySaverType`, `memoryEnabled`, `hasMoreEvents` |

중요: observability 로그는 checkpoint state에 누적하지 않는다. 따라서 metric 출력 자체가 `AgentCoreMemorySaver` event write 수를 늘리지는 않는다. 단, AgentCore Memory가 켜진 경우 memory guard가 invocation당 `ListEvents` 1페이지를 읽을 수 있다.

## 2. 실행 전 확인

로컬 live test에서 AgentCore Memory 과금을 피하려면 `.env.v2.local`에서 memory off 경로를 사용한다.

```powershell
Select-String -Path .env.v2.local -Pattern "LOVV_MEMORY|AGENTCORE|MEMORY"
```

권장:

```text
LOVV_MEMORY_ENABLED=false
```

필수 AWS 의존성:

- Bedrock embedding/runtime
- S3 Vectors
- DynamoDB
- ORS 사용 시 ORS credential 또는 AgentCore credential resolver

## 3. 단일 요청 실행

일반 live smoke runner를 사용한다.

```powershell
.venv\Scripts\python.exe scripts\v2\run_general_live_smoke.py `
  --input docs\tasks\results\v2_intent_mocks\generation\v2_gen_04_history_2d1n.json `
  --session-id obs-guide-create-001 `
  --actor-id local-observer `
  --request-id obs-guide-create-001 `
  --label create-history `
  --out-dir docs\tasks\results\v2_observability_manual
```

결과 JSON은 `--out-dir` 아래에 생성된다. stdout에 출력되는 `AGENT_*` JSON line은 터미널에 표시된다.

## 4. stdout 로그 파일로 저장

PowerShell에서는 `Tee-Object`로 stdout을 파일에도 남긴다.

```powershell
$out = "docs\tasks\results\v2_observability_manual"
New-Item -ItemType Directory -Force $out | Out-Null

.venv\Scripts\python.exe scripts\v2\run_general_live_smoke.py `
  --input docs\tasks\results\v2_intent_mocks\generation\v2_gen_04_history_2d1n.json `
  --session-id obs-guide-create-002 `
  --actor-id local-observer `
  --request-id obs-guide-create-002 `
  --label create-history `
  --out-dir $out |
  Tee-Object -FilePath "$out\create-history.stdout.log"
```

수정 요청은 같은 `session-id`와 `actor-id`를 유지해야 checkpointer state를 이어받는다.

```powershell
.venv\Scripts\python.exe scripts\v2\run_general_live_smoke.py `
  --input docs\tasks\results\v2_intent_mocks\modify\v2_modify_slot_replace_queryless.json `
  --session-id obs-guide-create-002 `
  --actor-id local-observer `
  --request-id obs-guide-modify-002 `
  --label modify-slot `
  --out-dir $out |
  Tee-Object -FilePath "$out\modify-slot.stdout.log"
```

## 5. 로그 파일 빠른 분석

JSON line만 파싱해서 log type 수를 확인한다.

```powershell
$entries = Get-Content "$out\create-history.stdout.log" |
  Where-Object { $_ -like "{*" } |
  ForEach-Object { $_ | ConvertFrom-Json }

$entries | Group-Object logType | Select-Object Name, Count
```

가장 오래 걸린 node/step을 확인한다.

```powershell
$entries |
  Where-Object { $_.logType -eq "AGENT_NODE_METRIC" } |
  Sort-Object durationMs -Descending |
  Select-Object -First 10 nodeName, durationMs, status
```

요청 전체 시간과 AWS/외부 tool latency aggregate를 확인한다.

```powershell
$invocation = $entries | Where-Object { $_.logType -eq "AGENT_INVOCATION_METRIC" } | Select-Object -Last 1
$invocation | Select-Object requestId, durationMs, status, responseStatus
$invocation.toolMetrics
```

modify/weather/clarification lifecycle을 확인한다.

```powershell
$entries |
  Where-Object { $_.logType -eq "AGENT_LIFECYCLE_METRIC" } |
  Select-Object lifecycleType, event, details
```

memory guard를 확인한다.

```powershell
$entries |
  Where-Object { $_.logType -eq "AGENT_MEMORY_GUARD" } |
  Select-Object level, memorySaverType, memoryEnabled, eventPageCount, hasMoreEvents
```

## 6. 결과 JSON 확인

runner가 만든 결과 JSON에서 public response 상태를 확인한다.

```powershell
$result = Get-ChildItem $out -Filter "*create-history*.json" |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

$payload = Get-Content $result.FullName -Raw | ConvertFrom-Json
$payload.responseStatus
$payload.response.destination
$payload.response.clarification
```

일정 생성/수정 성공 판정:

- `responseStatus = "modification_pending"` 또는 생성 완료 응답이면 정상 완료.
- `responseStatus = "END_WAIT_USER"`이면 clarification interrupt가 정상 발생한 것이다.
- `response.clarification.options[].helperText`가 있으면 front 표시 문구까지 포함된 상태이다.

## 7. 기존 live E2E 예시

기준 결과:

```text
docs/tasks/results/v2_observability_live_e2e/20260708T160734Z/
```

포함 파일:

- `weather-create-v2.stdout.log`
- `modify-slot-v2.stdout.log`
- `weather-resume-chain-v3.stdout.log`
- `observability_summary.json`

확인된 관측값:

- `AGENT_NODE_METRIC`: intent, planner 내부 step, explain, response packager.
- `AGENT_INVOCATION_METRIC`: create, modify, clarification resume 전체 duration.
- `AGENT_LIFECYCLE_METRIC`: weather evaluated, clarification waiting, modify applied.
- `toolMetrics`: `bedrock.Converse`, `bedrock.InvokeModel`, `dynamodb.BatchGetItem`, `s3vectors.QueryVectors`, `ors.SnapPlaces`, `ors.GetMatrix`.
- `AGENT_MEMORY_GUARD`: local memory saver 또는 AgentCore memory event page 상태.

## 8. 분석 기준

우선 확인할 항목:

1. `AGENT_INVOCATION_METRIC.durationMs`
   - 사용자가 체감하는 총 응답 시간.
2. `toolMetrics`
   - Bedrock, S3Vectors, DynamoDB, ORS 중 병목이 어디인지 확인.
3. `AGENT_NODE_METRIC` 상위 `durationMs`
   - graph 내부에서 오래 걸리는 node/step 식별.
4. `AGENT_LIFECYCLE_METRIC`
   - modify/weather/clarification이 의도한 branch를 탔는지 확인.
5. `AGENT_MEMORY_GUARD`
   - AgentCore Memory event page가 비정상적으로 커지는지 확인.

위험 신호:

- `AGENT_INVOCATION_METRIC.status != "success"`
- 동일 요청에서 `AGENT_NODE_METRIC`의 같은 node pair가 반복됨.
- `AGENT_MEMORY_GUARD.hasMoreEvents = true`
- `toolMetrics.bedrock.Converse.maxMs` 또는 `ors.GetMatrix.maxMs`가 전체 지연 대부분을 차지함.
- clarification이 필요한 케이스인데 `END_WAIT_USER`가 아닌 완료 응답으로 내려감.

## 9. CloudWatch에서 확인할 때

배포 runtime에서는 같은 JSON line이 CloudWatch Logs에 남는다. Logs Insights에서는 `logType` 기준으로 필터링한다.

```sql
fields @timestamp, requestId, logType, nodeName, durationMs, status, responseStatus
| filter logType in ["AGENT_INVOCATION_METRIC", "AGENT_NODE_METRIC", "AGENT_LIFECYCLE_METRIC", "AGENT_MEMORY_GUARD"]
| sort @timestamp desc
| limit 100
```

특정 request 기준:

```sql
fields @timestamp, logType, nodeName, lifecycleType, event, durationMs, status
| filter requestId = "obs-guide-create-002"
| sort @timestamp asc
```

외부 tool 병목은 `AGENT_INVOCATION_METRIC.toolMetrics`를 펼쳐서 확인한다. CloudWatch Logs Insights에서 nested JSON 집계가 불편하면, stdout log를 내려받아 §5의 PowerShell 분석 절차를 사용한다.

## 10. 운영 메모

- live test를 많이 반복할 때는 memory off local harness로 라우팅/성능 문제를 먼저 해결한다.
- AgentCore Memory를 켠 검증은 session 수와 반복 횟수를 제한한다.
- observability field는 public response contract가 아니다. front/backend API 구현은 response payload를 기준으로 하고, `AGENT_*` 로그는 운영 진단용으로만 사용한다.
- `app/LovvAgentV2`는 deploy mirror이다. `src/lovv_agent_v2` 변경 검증 후 deploy 전에 mirror 반영 여부를 확인한다.
