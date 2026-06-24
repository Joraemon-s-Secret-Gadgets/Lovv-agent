# Lovv AgentCore V1 — 구조 유지 · Observability 기반 CI/CD 통합 SPEC

---
title: Lovv AgentCore V1 — 현 구조 동결 + Observability + CI/CD 라인 (통합 SPEC)
project: Lovv (로브)
status: 설계 (Draft · 구현 전)
date: 2026-06-23
runtime: LovvAgentV1 (단일 AgentCore Runtime · us-east-1)
consolidates:
  - docs/specs/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md (배포 준비 게이트·parity·smoke)
  - docs/specs/LOVV_AGENTCORE_OBSERVABILITY_SPEC.md (OTel·X-Ray·CloudWatch 계측)
  - docs/specs/LOVV_AGENTCORE_V1_FM_ROUTING_SPEC.md (단일 런타임·노드별 FM 라우팅 · Gateway는 V2로 이관)
relates:
  - docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md (기반 구현)
  - docs/reports/01_PERFORMANCE_AND_MIGRATION.md / 04_PARALLELIZATION.md (병목 근거)
defers_to_v2:
  - AgentCore Memory / checkpointer / interrupt-resume
  - AgentCore Gateway tool 외부화
  - 대화형 빌더 루프(HITL) · 병렬화 코드 변경
  - Cognito 가명화 · 장기 메모리 수명주기
note: 본 SPEC은 V1 = "구조를 바꾸지 않고 관측 + CI/CD를 완성"하는 범위만 다룬다. 구조 진화는 V2 SPEC.
---

## 0. 한 줄 요약

V1은 **현 deterministic 파이프라인 구조를 그대로 동결**한 채, AgentCore Observability(OTel +
X-Ray + CloudWatch)를 붙이고 **그 관측 신호를 게이트로 쓰는 CI/CD 라인**을 완성한다. 코드 로직·
`/recommendations` 계약·런타임 토폴로지는 바꾸지 않는다.

## 1. 범위와 불변 규칙 (Invariants)

1. **단일 런타임 유지**: `LovvAgentV1` 하나. 노드를 별도 Runtime으로 쪼개지 않는다.
2. **구조 동결**: Intent → Supervisor → Candidate Evidence → Supervisor → Festival(or skip)
   → Supervisor → Planner → Supervisor → Response Packager. 매 노드 사이에 결정론
   Supervisor가 라우팅하는 구조·노드 책임 불변.
3. **계약 불변**: `/recommendations` 요청·응답 스키마 변경 금지.
4. **상태 무변경**: 무상태 기본 유지. **Memory·checkpointer·Gateway·HITL은 V1 범위 밖**(→ V2).
5. **정본/사본 parity**: `src/lovv_agent`(정본) ↔ `app/LovvAgentV1/lovv_agent`(배포 사본) 동기.
6. **비밀·PII 금지**: 자격증명·`aws-targets.json`·raw PII·프롬프트/모델응답 덤프 커밋 금지.
7. **리전 기준**: `us-east-1`.

> V1에서 추가되는 것은 **관측 계측 + 설정 라우팅 + CI/CD 게이트**뿐이며, 추천 로직은 손대지 않는다.

## 2. 통합 출처 매핑 (이 SPEC이 흡수하는 문서)

| 기존 SPEC | 흡수 범위 | V1에서의 위치 |
|---|---|---|
| V1_PRODUCTION_READINESS | 모델 가용성 체크·노드별 structured-output smoke·parity·`agentcore validate/dry-run` 게이트·경계 | §5 CI/CD 게이트 / §1 불변 |
| OBSERVABILITY | OTel 스팬·X-Ray·CloudWatch JSON 로그·토큰/레이턴시/IO 계측·안전 필터 | §3 관측 계층 / §5 관측 게이트 |
| V1_FM_ROUTING | 단일 런타임 결정·노드별 FM 라우팅 설정·provider 정책·rate-limit 측정 | §4 FM 라우팅 (Gateway는 V2로 이관) |

> 원본 문서는 상세 레퍼런스로 유지한다. 본 SPEC은 V1 로드맵의 **단일 진실원(source of truth)**이며,
> 위 3건의 *V1 실행 범위*를 대표한다.

## 3. Observability 계층 (구조 변경 없이 계측만)

투 트랙: **분산추적(OTel→ADOT→X-Ray)** + **구조화 로깅(CloudWatch JSON Lines)**.
(상세 코드는 OBSERVABILITY 원본 §4 참조 — 여기서는 계약만 고정한다.)

### 3.1 스팬 계층

- 최상위: `LovvAgentInvocation` (HTTP 진입~리턴).
- 노드: `node.intent_agent` / `node.candidate_evidence_agent` / `node.festival_verifier_agent` /
  `node.planner_agent` / `node.response_packager`.
- Supervisor: `node.supervisor_router` (매 워커 사이에 실행됨).
- AWS 서브스팬: `BedrockConverse` / `s3vectors.QueryVectors` / `dynamodb.GetItem`.

> 노드 스팬 이름은 `graph.py`의 LangGraph 등록명과 일치시킨다:
> `intent_agent`, `candidate_evidence_agent`, `festival_verifier_agent`, `planner_agent`,
> `response_packager`, `supervisor_router`.

### 3.2 필수 지표 (CI/CD 게이트의 입력이 됨)

`request_latency`, `node durationMs`, `BedrockConverse` 지연, `s3vectors`/`dynamodb` 지연,
`llm.usage.{input,output,total}_tokens`, `contextUsagePercent`, structured-output `retry_count`,
`throttle_count`, `error_rate`, cold/warm 구분.

### 3.3 로그 스키마 (고정 계약 — 게이트가 파싱)

`logType="AGENT_NODE_METRIC"` 단일 라인 JSON. 필드: `timestamp/requestId/nodeName/durationMs/
status/llmMetrics{modelId,inputTokens,outputTokens,totalTokens,contextWindow,contextUsagePercent}/
inputSummary/outputSummary`. (OBSERVABILITY §3 스키마 동결.)

> `requestId`는 `state.trace.recommendation_request_id`에서 가져온다 (상태 객체 `TraceState` 참조).
> `state.request`에는 request_id 필드가 없으므로, Observability 원본 §4.3의 예시 코드
> (`getattr(state.request, ...)`)는 구현 시 `state.trace.recommendation_request_id`로 정렬해야 한다.

### 3.4 안전 필터 (불변)

Allowlist: 쿼리 길이·테마·status·선정 도시·일정 요약·검증 오류 스펙. Denylist: 자격증명·raw
RAG/Vector 전체·PII. `build_memory_safe_summary` 원칙 준수.

## 4. FM 라우팅 설정 (단일 런타임 내 노드별 모델)

- 전역 fallback `LOVV_LLM_MODEL_ID` + 노드별 override
  (`LOVV_INTENT_/CANDIDATE_EVIDENCE_/PLANNER_/SUPERVISOR_LLM_MODEL_ID`), 선택적 adapter override.
- 해석 규칙: 노드 전용 → 전역 → 미해석 시 명확한 config 에러 → 시작 시 resolved map 로깅(자격증명·
  프롬프트 미포함).
- provider 비제한(Converse 호환 + 동일 structured-output 계약 충족 모델만).
- **노드별 측정 의무**(§3.2 지표): prompt/completion token·latency·retry·throttle.
- 권장 초기 라우팅: Intent=저가·스키마안정, Candidate=저/중, Planner=고품질 한국어, Supervisor=미설정.
- **Gateway는 V1 비목표** — V2 SPEC의 additive phase로 이관.

## 5. CI/CD 라인 (이 SPEC의 핵심)

Observability 신호를 **게이트로 사용**하는 파이프라인. 기존 준비성 게이트 + 관측 기반 회귀 게이트.

```text
[push / PR]
 ├─ 1) lint / format
 ├─ 2) unit test (config 파싱 · entrypoint payload · resolver · parity util)
 ├─ 3) compileall (src · tests · app/LovvAgentV1)
 ├─ 4) parity check  (src/lovv_agent ↔ app/LovvAgentV1/lovv_agent · 불일치 경로 출력)
 ├─ 5) telemetry contract test
 │       - AGENT_NODE_METRIC JSON 스키마 검증(필드·타입·denylist 누출 0)
 │       - 노드 스팬 이름·필수 attribute 존재 검증(모킹 트레이서)
 ├─ 6) (env-gated · LOVV_ENABLE_AWS_SMOKE=1)
 │       - 모델 가용성: bedrock list-foundation-models / list-inference-profiles (us-east-1)
 │       - 노드별 structured-output smoke (Intent · Candidate reason-claim · Planner)
 │       - 결과를 docs/tasks/results/ 리포트에 기록(자격증명·PII 미기록)
 ├─ 7) agentcore validate --json
 ├─ 8) agentcore deploy --target v1 --dry-run --json
 └─ 9) 배포 게이트 (실패 시 차단)

[deploy 후 · 관측 검증]
 ├─ 10) post-deploy smoke 1건 → 트레이스가 X-Ray/ServiceLens에 도달하는지 확인
 ├─ 11) 관측 회귀 게이트 (아래 §6 예산 대비 p50/p95/p99 · token · error_rate)
 └─ 12) 롤백 기준 충족 시 이전 버전으로 롤백
```

### 5.1 관측 기반 게이트 (신규 핵심)

- **Telemetry contract gate (CI, AWS 불필요)**: 계측이 §3.3 스키마를 정확히 내보내는지, denylist
  필드(자격증명·PII·raw vector)가 절대 새지 않는지 단위 테스트로 강제. → 관측을 "신뢰 가능한
  게이트 입력"으로 만드는 선행 조건.
- **Latency/token 회귀 게이트 (post-deploy 또는 staging 부하)**: §6 예산을 초과하면 배포 실패/경보.
- **Error-rate 게이트**: 노드별 `status=error` 비율 임계 초과 시 차단.

### 5.2 준비성 게이트 (기존 흡수)

parity·모델 가용성·노드 smoke·`agentcore validate`/`dry-run`은 V1_PRODUCTION_READINESS의 R1~R4를
그대로 게이트화. AgentCore CLI 부재 시 시도 명령·환경 blocker를 리포트에 기록.

### 5.3 리포트 산출물

실행 증빙은 `docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md`에 기록(브랜치·타임스탬프·
리전·모델 가용성·노드 smoke·parity·pytest/compile·validate/dry-run·관측 게이트 결과·blocker·릴리스 권고).

## 6. 성능 예산 / SLO (관측 게이트 기준값)

| 지표 | 측정 위치 | 초기 예산(잠정·측정 후 확정) |
|---|---|---|
| 전체 request latency p95 | `LovvAgentInvocation` | TBD (배포 후 baseline의 N% 이내) |
| node 지연 p95 | 각 `node.*` | candidate_evidence·planner 별도 추적 |
| s3vectors 합산 지연 | `s3vectors.QueryVectors` | 테마 수 비례(병목 후보 — V2 병렬화 전 baseline) |
| dynamodb 합산 지연 | `dynamodb.GetItem` | 장소 수 비례 |
| 노드별 token | `llmMetrics` | Planner 입력 증가 감시 |
| structured-output retry | adapter | 0 목표, 급증 시 프롬프트 점검 |
| throttle count | adapter | 0 목표 |
| error_rate | 노드 status | 임계 초과 시 게이트 차단 |

> 예산 절대값은 **배포 후 baseline 측정으로 확정**한다(§10). V1은 *측정·게이트화*가 목적이며,
> 실제 단축(병렬화 등)은 V2.

## 7. 비용 영향

| 항목 | 분류 | 비고 |
|---|---|---|
| OTel/ADOT·X-Ray 트레이스 | 증가(소) | 샘플링으로 통제 가능 |
| CloudWatch Logs/Insights | 증가(소~중) | JSON 라인 ingest·보존기간 설정 |
| structured-output smoke·모델 가용성 | 증가(미미·env-gated) | CI에서만, 기본 off |
| (선택) provisioned concurrency | 증가 | V1 필수 아님 — 콜드스타트 측정 후 결정 |
| CI/CD 게이트 자체 | 무료~소 | 러너 시간 |

→ V1은 **비용 증가가 작은 관측·게이트 위주**. 큰 비용/구조 변화는 없음.

## 8. 경계 (V1에서 하지 않는 것 → 전부 V2)

- AgentCore Memory·checkpointer·interrupt/resume 활성화 금지.
- AgentCore Gateway로 tool 외부화 금지.
- 대화형 빌더 루프·노드 내부 병렬화 코드 변경 금지.
- Cognito 가명화·장기 메모리 수명주기 금지.
- `/recommendations` 스키마·런타임 토폴로지 변경 금지.

## 9. 성공 기준

1. 모든 노드·LLM·AWS 호출이 §3 스팬/로그 계약대로 트레이스되고, denylist 누출 0이 테스트로 보장.
2. CI/CD 9단계가 동작하고, 관측 기반 게이트(§5.1)가 회귀를 차단.
3. parity·모델 가용성·노드 smoke·`agentcore validate`/`dry-run`이 게이트로 통과 또는 blocker 기록.
4. 배포 후 ServiceLens에서 노드별 latency·token 대시보드가 보이고, §6 baseline이 확정됨.
5. 무상태 기본 동작·`/recommendations` 계약 불변.

## 10. 미해결 / 확인 필요

- [ ] §6 예산 절대값(p50/p95/p99·error_rate 임계) — 배포 후 baseline로 확정.
- [ ] OTel/ADOT 버전 pin·AgentCore(Lambda) 호환·OTLP 엔드포인트(사이드카/데몬) 방식.
- [x] `state` 식별자 속성명 정렬 → `state.trace.recommendation_request_id` 사용 확정
  (`TraceState` 클래스, `state.py`). `agent_run_id`는 별도 런타임 생성 가능.
- [ ] 컨텍스트 윈도우 정적 매핑에 하이브리드(OpenAI) 모델 값 추가.
- [ ] 관측 게이트를 PR 차단형으로 둘지, post-deploy 경보형으로 둘지(러너에 AWS 자격 유무).
- [ ] 콜드스타트 측정 후 provisioned concurrency 도입 여부.

> 본 문서는 V1 통합 SPEC(초안)이다. "확인 필요" 항목은 구현 착수 전 확정한다. 구조 진화는
> `LOVV_V2_UPGRADE_SPEC.md`를 따른다.
