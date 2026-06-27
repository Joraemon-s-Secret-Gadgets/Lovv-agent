# scripts/ — LovvAgentV1 테스트·운영 스크립트

확정된 V1을 **기능/비기능**으로 검증하는 두 경로의 도구 모음이다.

- **경로 1 — 로컬 live** (`capture_e2e_state.py`, `invoke_live_recommendation.py`): **src/ 코드를 in-process로** 실행(실제 AWS 데이터 서비스는 호출하되 배포 런타임 아님). 재배포 없이 기능·출력·노드 증빙 확인. CloudWatch/X-Ray 트레이스·프로덕션 latency는 없음.
- **경로 2 — 배포 런타임** (`invoke_deployed_runtime.py` → `fetch_traces.py`): **배포된 app/ 코드**를 호출(트레이스 생성). 비기능(latency)·관측(NF/OB)·배포 통합 확인. src 변경을 반영하려면 재배포 선행.

## 스크립트 비교

| 스크립트 | 실행 위치 | 실행 코드 | 산출물 | 트레이스 | 주 용도 |
|---|---|---|---|---|---|
| `capture_e2e_state.py` | 로컬 in-process | `src/` | **노드 내부 state 전체** dump(JSON) | 없음 | §2.6/§7 노드 증빙, 기능·스키마·안전 |
| `invoke_live_recommendation.py` | 로컬 in-process | `src/` | **마스킹된 공개 응답**만 | 없음 | 공개 출력만 빠르게(FN-08/09), stdin 파이프 |
| `invoke_deployed_runtime.py` | **배포 런타임** | `app/`(배포본) | 공개 응답 + `traceId` | **CloudWatch/X-Ray 생성** | 비기능·관측·배포 통합, latency |
| `fetch_traces.py` | AWS API(X-Ray/CW) | — | 트레이스·서브스팬·로그 JSON | (수집) | invoke_deployed가 만든 트레이스 수집 |

## 두 invoke의 역할 차이 (겹치지 않음)

- `invoke_live_recommendation.py` = **로컬 src 그래프** → 마스킹된 `/recommendations` 응답만. 트레이스·프로덕션 latency 없음. **src 변경을 재배포 없이 공개 출력으로 확인**할 때.
- `invoke_deployed_runtime.py` = **배포 런타임** 호출 → 공개 응답 + `traceId` + 트레이스 생성. **프로덕션/관측/배포통합** 확인. src 반영하려면 재배포 필요.
- 둘 다 "invoke 후 응답"이라 비슷해 보이지만 **실행 위치(로컬 src vs 배포 app)와 트레이스 생성 여부**가 다르다.
- **노드 내부 state**가 필요하면 invoke_live가 아니라 `capture_e2e_state.py`를 써라 — 공개 응답에는 내부 state(Intent 결과·후보·CE 패키지 등)가 없다.

## AWS 프로필 (`--profile`)

- 모든 스크립트가 `--profile`을 지원한다. **미지정 시 boto3 기본 자격증명 체인**(default 프로필 / `AWS_*` env / IAM role)을 사용한다.
- 로컬 harness(`capture`, `invoke_live`): `--profile` → `LOVV_AWS_PROFILE` env로 주입 → `RuntimeConfig.aws.profile_name` → boto3 `Session(profile_name=...)`.
- 직접 boto3(`invoke_deployed`, `fetch_traces`): `--profile` → `boto3.Session(profile_name=...)`.

## 사용 예

```powershell
# 경로 1 — 노드 증빙(전체 fixture 일괄)
$env:LOVV_ENABLE_AWS_SMOKE='1'
uv run scripts/capture_e2e_state.py --live --input-dir docs/tasks/results/agent_input_payloads --profile skn26_final

# 경로 1 — 공개 응답만 단건
uv run python scripts/invoke_live_recommendation.py --input docs/tasks/results/agent_input_payloads/tc009_chat_nature_coast_quiet.json --profile skn26_final

# 경로 2 — 배포 호출(fixture마다 새 세션=격리) → 트레이스 수집
uv run python scripts/invoke_deployed_runtime.py --input-dir docs/tasks/results/agent_input_payloads --profile skn26_final
uv run scripts/fetch_traces.py --summary docs/tasks/results/deployed_invoke_trace_summary.json --out docs/tasks/results/traces_fetched.json --profile skn26_final

# 경로 2 — 워밍 latency 측정용(세션 고정)
uv run python scripts/invoke_deployed_runtime.py --input-dir docs/tasks/results/agent_input_payloads --session-id lovv-warm-0000000000000000000000 --profile skn26_final
```

## 사전조건

- **로컬 live**: `LOVV_ENABLE_AWS_SMOKE=1`, AWS 자격증명, `.env.local`(capture는 자동 로드; invoke_live는 RuntimeConfig를 env에서 읽음). `--mock`은 가짜 AWS라 실제 추천/congestion 검증 불가.
- **배포 invoke**: `bedrock-agentcore:InvokeAgentRuntime` 권한 + 배포 완료. 기본은 fixture마다 새 `runtimeSessionId`(=새 MicroVM, 격리·콜드); 워밍은 `--session-id` 고정.
- **fetch_traces**: `xray:BatchGetTraces`/`GetTraceSummaries`, (`--logs` 시) `logs:StartQuery`/`GetQueryResults`, CloudWatch Transaction Search 활성화. X-Ray ID 변환·`/ping` 스팬 제외 내장.

## 비고

- `capture_e2e_state.py`·`invoke_live_recommendation.py`는 `src/`를 실행하므로 src 변경이 **즉시** 반영된다(재배포 불필요). `invoke_deployed_runtime.py`는 배포본을 부르므로 src 변경 반영에 **재배포**가 필요하다.
- latency는 **반드시 경로 2(배포 트레이스)**에서. 로컬 프로세스 시간은 프로덕션 대표값이 아니다.
