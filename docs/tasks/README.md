# Lovv Agent Task 인덱스

Task 문서는 SPEC을 실제 구현 순서로 나눈 실행 계획이다. 구현이나 검증을 수행한 뒤의
증거는 `results/`에 별도로 남긴다.

## 구현 Task

| 문서 | 연결 SPEC 또는 목적 |
| --- | --- |
| [Lovv LangGraph Agent Implementation Tasks](./LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md) | [LangGraph V1 SPEC](../specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md) 실행 계획 |
| [Lovv AgentCore V1 FM Routing Tasks](./LOVV_AGENTCORE_V1_FM_ROUTING_TASKS.md) | [AgentCore V1 FM Routing SPEC](../specs/v1/LOVV_AGENTCORE_V1_FM_ROUTING_SPEC.md) 실행 계획 |
| [LovvAgentV1 Observability 구현 Task](./LOVV_V1_OBSERVABILITY_IMPLEMENTATION_TASKS.md) | V1 observability 계측과 CI/CD gate 준비 |
| [Lovv AgentCore V1 Production Readiness Tasks](./LOVV_AGENTCORE_V1_PRODUCTION_READINESS_TASKS.md) | [Production Readiness SPEC](../specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md) 문서 이관 및 배포 준비 점검 |
| [Lovv AgentV2 Intent Local Test Tasks](./LOVV_AGENTV2_INTENT_LOCAL_TEST_TASKS.md) | [AgentV2 Intent Local Test SPEC](../specs/v2/LOVV_AGENTV2_INTENT_LOCAL_TEST_SPEC.md) 실행 계획 |

## 결과와 Fixture

- [Task 결과 디렉터리](./results/)에는 실제 구현 또는 검증을 수행한 결과만 둔다.
- 테스트 실행 결과는 `results/tests/<topic>/<timestamp>/` 아래에 `summary.md`, `test_output.md`, `input_output.md`, 원문 log로 적재한다.
- [Agent input payload fixtures](./results/agent_input_payloads/README.md)는 E2E와 AgentCore wrapper 입력 예시를 보관한다.
- 문서 이관만 수행한 경우에는 `results/*_RESULT.md`를 새로 만들지 않는다.
