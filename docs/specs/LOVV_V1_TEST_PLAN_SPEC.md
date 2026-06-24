# LovvAgentV1 테스트 계획 및 결과 보고서 작성 SPEC

---
title: LovvAgentV1 테스트 계획·결과 보고서 — Observability 기반 에이전트 검증
project: Lovv (로브)
status: 설계 (Draft)
date: 2026-06-24
runtime: LovvAgentV1 (단일 AgentCore Runtime · us-east-1)
output:
  - docs/tasks/results/LOVV_V1_TEST_PLAN.md (테스트 계획서)
  - docs/tasks/results/LOVV_V1_TEST_RESULT.md (테스트 결과서 — 양식)
relates:
  - docs/specs/LOVV_AGENTCORE_OBSERVABILITY_SPEC.md
  - docs/specs/LOVV_V1_OBSERVABILITY_CICD_SPEC.md
  - docs/specs/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md
---

## 1. 목적

LovvAgentV1의 **기능적/비기능적 요구사항 충족 여부를 확인**하고, AgentCore Observability
(OTel + X-Ray + CloudWatch)를 통해 **성능과 안정성을 관측·검증**하기 위한 테스트 계획서와
결과 보고서 양식을 산출한다.

### 범위

- 기능 테스트: 각 에이전트 노드가 의도한 응답을 정상 생성하는지 (정상 경로 + fallback 경로)
- 비기능 테스트: 노드별 레이턴시, 토큰 사용량, 에러율, AWS 서비스 호출 지연
- Observability 검증: OTel 스팬/로그가 설계 스키마대로 출력되는지

### 범위 밖

- 추천 품질 평가 (AgentCore Evaluations → Phase 3)
- CI/CD 자동 게이트 (배포 차단 자동화 → 향후)
- 성능 SLO 절대값 확정 (baseline 측정 후 별도 확정)

---

## 2. 테스트 계획서 구조 (산출물 1)

다른 에이전트가 `docs/tasks/results/LOVV_V1_TEST_PLAN.md`를 작성할 때
아래 구조를 따른다.

### 2.1 테스트 목적

- LovvAgentV1의 LangGraph 파이프라인이 정상적으로 실행되는지 확인
- 각 노드(Intent, Candidate Evidence, Planner, Supervisor, Response Packager)가
  설계된 structured output을 반환하는지 확인
- Fallback 경로(retry 소진, no-candidate, clarification)가 의도대로 동작하는지 확인
- OTel 계측이 설계된 스팬/로그 스키마를 준수하는지 확인
- 노드별 레이턴시·토큰 사용량·에러율을 측정하여 baseline 확보

### 2.2 테스트 환경

| 항목 | 값 |
|------|-----|
| 런타임 | LovvAgentV1 (AWS Bedrock AgentCore Runtime) |
| 리전 | us-east-1 |
| Python | 3.12 |
| 프레임워크 | LangGraph ≥0.6 |
| LLM 모델 | openai.gpt-oss-120b-1:0 (전 노드 공통) |
| Embedding 모델 | amazon.titan-embed-text-v2:0 |
| 벡터 저장소 | S3 Vectors (lovv-vector-dev / kr-tour-domain-v1) |
| DB | DynamoDB (TourKoreaDomainData) |
| Observability | OTel SDK → ADOT Collector → AWS X-Ray + CloudWatch Logs |
| 테스트 도구 | pytest, intent_playground, scripts/invoke_live_recommendation.py |

### 2.3 테스트 케이스 분류

#### A. 기능 테스트 — 정상 경로

| TC-ID | 대상 노드 | 시나리오 | 검증 기준 |
|-------|-----------|----------|-----------|
| FN-01 | Intent | 짧은 쿼리 → deterministic 모드 | `execution_mode=deterministic_short_query`, theme 매핑 정상 |
| FN-02 | Intent | 긴 쿼리 → LLM structured output | Bedrock Converse 호출, 파싱 성공, `execution_mode=deterministic_llm_fallback` |
| FN-03 | Candidate Evidence | 도시 발견 모드 | `status=ok`, selected_city 존재, recommended_places ≥ 3 |
| FN-04 | Candidate Evidence | 축제 시드 모드 | festival_candidates 포함, CE 패키지 정상 |
| FN-05 | Planner | 정상 일정 생성 | itinerary 항목 수 = 후보 수, validation passed |
| FN-06 | Planner | LLM copy explanation | body/reason 필드에 LLM 생성 텍스트 존재 |
| FN-07 | Supervisor | 전체 라우팅 | visited_nodes 순서 = 설계 그래프 순서 |
| FN-08 | Response Packager | 공개 응답 마스킹 | 내부 필드(candidate_reason_claims 등) 미노출 |
| FN-09 | 전체 E2E | `/recommendations` 정상 응답 | HTTP 200, 응답 스키마 준수 |

#### B. 기능 테스트 — Fallback/에러 경로

| TC-ID | 대상 노드 | 시나리오 | 검증 기준 |
|-------|-----------|----------|-----------|
| FB-01 | Intent | LLM structured output 실패 → safe fallback | API themes 그대로 사용, 에러 미전파 |
| FB-02 | Candidate Evidence | no-candidate + clarification | `needs_clarification=true`, planner 미호출 |
| FB-03 | Candidate Evidence | no-candidate (clarification 없음) | 빈 itinerary, fulfilled_matrix evidence=△ |
| FB-04 | Planner | validation retry 소진 (3회) | 빈 itinerary, fulfilled_matrix planning=△, userNotice 존재 |
| FB-05 | Planner | insufficient candidates | 축소 일정, userNotice에 "후보 수가 적어" 포함 |
| FB-06 | Supervisor | unsafe fallback | response_packager로 직행, planner 미호출 |

#### C. 비기능 테스트 — Observability 기반

| TC-ID | 측정 항목 | 검증 기준 |
|-------|-----------|-----------|
| NF-01 | 전체 요청 레이턴시 | `LovvAgentInvocation` 스팬 duration 기록됨 |
| NF-02 | 노드별 레이턴시 | 각 `node.*` 스팬 durationMs 기록됨 |
| NF-03 | BedrockConverse 지연 | `BedrockConverse` 서브스팬 duration 기록됨 |
| NF-04 | S3Vectors QueryVectors 지연 | `s3vectors.QueryVectors` 서브스팬 duration 기록됨 |
| NF-05 | DynamoDB GetItem 지연 | `dynamodb.GetItem` 서브스팬 duration 기록됨 |
| NF-06 | 토큰 사용량 | `llmMetrics.{inputTokens,outputTokens,totalTokens}` 기록됨 |
| NF-07 | 에러율 | `status=error` 비율 = 0 (정상 시나리오) |
| NF-08 | Structured output retry | retry_count 기록됨, 정상 시 0 |
| NF-09 | Denylist 누출 검증 | 로그/스팬에 자격증명·PII·raw vector 미포함 |

#### D. Observability 계측 검증

| TC-ID | 검증 항목 | 기준 |
|-------|-----------|------|
| OB-01 | AGENT_NODE_METRIC JSON 스키마 | §3.3 필드 전체 존재, 타입 정합 |
| OB-02 | 스팬 계층 구조 | 최상위 → 노드 → 서비스 서브스팬 3계층 |
| OB-03 | requestId 정렬 | `state.trace.recommendation_request_id` 사용 |
| OB-04 | X-Ray trace 도달 | ServiceLens에서 trace map 확인 |
| OB-05 | CloudWatch Logs Insights 쿼리 | `logType="AGENT_NODE_METRIC"` 필터 동작 |

### 2.4 테스트 실행 전제

**모든 테스트는 기본적으로 실제 모델 호출 / AWS 서비스 연결 기준으로 진행한다.**

- Bedrock Converse: 실제 `openai.gpt-oss-120b-1:0` 모델 invoke
- S3Vectors: 실제 `lovv-vector-dev` / `kr-tour-domain-v1` 인덱스 조회
- DynamoDB: 실제 `TourKoreaDomainData` 테이블 조회
- AgentCore Runtime: 배포된 `LovvAgentV1` 런타임에 대한 invoke

모킹 기반 pytest는 **로직 회귀 방지용 보조 수단**이며, 테스트 결과서의 증빙에는 포함하지 않는다.

**필요 환경:**
- AWS 자격증명 (Bedrock, S3Vectors, DynamoDB 접근 권한)
- `LOVV_ENABLE_AWS_SMOKE=1` 환경변수
- 배포된 AgentCore Runtime (invoke 테스트 시)

**실행 불가 시:** "미실행 — 사유: ___"로 결과서에 명시하고, 가능해진 시점에 재실행한다.

### 2.5 테스트 실행 명령

| 테스트 유형 | 실행 명령 | 비고 |
|---|---|---|
| 기능 E2E (전체 그래프) | `$env:LOVV_ENABLE_AWS_SMOKE='1'; uv run python scripts/capture_e2e_state.py --live` | 모든 FN-*, FB-* TC 증빙 |
| 배포 런타임 invoke | `uv run python scripts/invoke_live_recommendation.py` | /recommendations 엔드포인트 확인 |
| Intent 프롬프트 평가 | `uv run python intent_playground/run.py --repeat 3` | Intent structured output 일관성 |
| Observability 검증 | X-Ray 콘솔 + CloudWatch Logs Insights 쿼리 | 트레이스 도달, 로그 스키마 |
| (보조) 회귀 방지 pytest | `$env:UV_CACHE_DIR='.cache\uv'; uv run pytest -q` | 로직 회귀 감지용, 결과서 증빙 아님 |

### 2.6 노드별 실행 결과 상세 (E2E 증빙)

테스트 결과서에는 E2E 실행 시 각 노드/tool의 **실제 실행 결과**를 상세히 기록한다.
이는 Observability 로그(요약 수준)와 별개로, "agent가 실제로 무엇을 가져와서 무엇을 만들었는지"를
문서로 증빙하기 위한 것이다.

기록 항목:

| 단계 | 기록할 내용 |
|------|------------|
| 요청 Payload | 실제 입력 JSON (entryType, themes, tripType, naturalLanguageQuery 등) |
| Intent 결과 | execution_mode, active_required_themes, 추출된 의미 신호 |
| S3Vectors 검색 결과 | 반환된 attraction 목록 (place_id, title, city_id, distance, theme_tags) |
| DynamoDB 조회 결과 | 조회한 PK/SK, overview 텍스트, 반환 여부 |
| Candidate Evidence 패키지 | selected_city, mode, recommended_places 전체 목록, failure_signals (있을 경우) |
| Festival Verifier 결과 | 축제 검증 결과 (date_status, is_applicable, planner_policy) — 해당 시 |
| Planner 출력 | itinerary 항목 전체 (day, slot, placeId, title, body, reason), validation_result |
| Supervisor 라우팅 기록 | visited_nodes 순서, fulfilled_matrix 최종 상태 |
| 최종 공개 응답 | /recommendations 응답 JSON (마스킹 후 공개 형태) |

**캡처 방법:** `harness.invoke_state()` 반환값에서 각 상태 슬라이스를 추출하거나,
`scripts/invoke_live_recommendation.py` 실행 시 `--dump-state` 옵션으로 중간 상태 저장.

### 2.7 판정 기준 (Pass/Fail)

| 기준 | Pass 조건 |
|------|-----------|
| 기능 정상 경로 | 전 TC Pass (expected output 일치) |
| Fallback 경로 | 전 TC Pass (의도한 fallback 동작 확인) |
| Observability 스키마 | AGENT_NODE_METRIC JSON 필드 100% 존재, denylist 누출 0 |
| 에러율 | 정상 시나리오에서 `status=error` = 0 |
| 스팬 계층 | 전 노드 + 서비스 서브스팬 존재 |

---

## 3. 테스트 결과서 양식 (산출물 2)

다른 에이전트가 `docs/tasks/results/LOVV_V1_TEST_RESULT.md`를 작성할 때
아래 양식을 따른다.

```markdown
# LovvAgentV1 테스트 결과 보고서

> 실행일: YYYY-MM-DD
> 브랜치: (branch name)
> 실행자: (agent or human)
> 런타임: LovvAgentV1
> 리전: us-east-1

## 1. 실행 환경

| 항목 | 값 |
|------|-----|
| Python | 3.12 |
| LLM 모델 | (실제 사용된 모델 ID) |
| AgentCore Runtime ID | (runtime ID) |
| 배포 해시 | (deploy hash) |

## 2. 기능 테스트 결과 — 정상 경로

| TC-ID | 시나리오 | 결과 | 비고 |
|-------|----------|------|------|
| FN-01 | Intent 짧은 쿼리 | Pass/Fail | |
| FN-02 | Intent 긴 쿼리 LLM | Pass/Fail | |
| ... | ... | ... | ... |

## 3. 기능 테스트 결과 — Fallback 경로

| TC-ID | 시나리오 | 결과 | 비고 |
|-------|----------|------|------|
| FB-01 | Intent safe fallback | Pass/Fail | |
| FB-02 | CE clarification | Pass/Fail | |
| ... | ... | ... | ... |

## 4. 비기능 테스트 결과 — Observability 측정값

| TC-ID | 측정 항목 | 측정값 | 결과 | 비고 |
|-------|-----------|--------|------|------|
| NF-01 | 전체 요청 레이턴시 | ___ms | Pass/Fail | |
| NF-02 | Intent 노드 레이턴시 | ___ms | Pass/Fail | |
| NF-02 | Candidate Evidence 노드 레이턴시 | ___ms | Pass/Fail | |
| NF-02 | Planner 노드 레이턴시 | ___ms | Pass/Fail | |
| NF-03 | BedrockConverse 지연 | ___ms | Pass/Fail | |
| NF-04 | S3Vectors 지연 | ___ms | Pass/Fail | |
| NF-05 | DynamoDB 지연 | ___ms | Pass/Fail | |
| NF-06 | 토큰 사용량 (Intent) | in:___ out:___ | 기록 | |
| NF-06 | 토큰 사용량 (CE) | in:___ out:___ | 기록 | |
| NF-06 | 토큰 사용량 (Planner) | in:___ out:___ | 기록 | |
| NF-07 | 에러율 | ___% | Pass/Fail | |
| NF-08 | Retry count | ___ | 기록 | |
| NF-09 | Denylist 누출 | 0건 / N건 | Pass/Fail | |

## 5. Observability 계측 검증 결과

| TC-ID | 검증 항목 | 결과 | 증빙 |
|-------|-----------|------|------|
| OB-01 | JSON 스키마 정합 | Pass/Fail | (로그 샘플 첨부) |
| OB-02 | 스팬 계층 구조 | Pass/Fail | (X-Ray 트레이스 ID) |
| OB-03 | requestId 정렬 | Pass/Fail | |
| OB-04 | X-Ray trace 도달 | Pass/Fail | (스크린샷 또는 trace ID) |
| OB-05 | CloudWatch Insights 쿼리 | Pass/Fail | (쿼리 결과 샘플) |

## 6. 종합 판정

| 영역 | 결과 | 비고 |
|------|------|------|
| 기능 정상 경로 | Pass/Fail | _/_건 통과 |
| Fallback 경로 | Pass/Fail | _/_건 통과 |
| Observability 계측 | Pass/Fail | |
| 비기능 측정 | 기록 완료 / 미완료 | baseline 확보 여부 |

## 7. 노드별 실행 결과 상세 (E2E 증빙)

### 7.1 요청 Payload

```json
(실제 입력 JSON)
```

### 7.2 Intent 결과

| 항목 | 값 |
|------|-----|
| execution_mode | |
| active_required_themes | |
| 추출 의미 신호 요약 | |

### 7.3 S3Vectors 검색 결과

| # | place_id | title | city_id | distance | theme_tags |
|---|----------|-------|---------|----------|------------|
| 1 | | | | | |
| 2 | | | | | |
| ... | | | | | |

### 7.4 DynamoDB 조회 결과

| PK | SK | found | overview (요약) | content_length |
|----|----|-------|-----------------|----------------|
| | | | | |

### 7.5 Candidate Evidence 패키지

| 항목 | 값 |
|------|-----|
| status | |
| mode | |
| selected_city | |
| recommended_places 수 | |
| failure_signals | |

**recommended_places 목록:**

| # | place_id | title | city_id | theme_tags |
|---|----------|-------|---------|------------|
| 1 | | | | |
| ... | | | | |

### 7.6 Planner 출력

| day | slot | placeId | title | body (앞 50자) | reason (앞 50자) |
|-----|------|---------|-------|----------------|-----------------|
| | | | | | |

**validation_result:** pass / fail (사유: ___)

### 7.7 Supervisor 라우팅

| 항목 | 값 |
|------|-----|
| visited_nodes | [순서 나열] |
| fulfilled_matrix | {evidence: _, planning: _, festival: _} |

### 7.8 최종 공개 응답

```json
(마스킹된 /recommendations 응답 JSON)
```

## 8. Blocker / 미해결 사항

- (있을 경우 기록)

## 9. 첨부

- X-Ray Trace Map 스크린샷
- CloudWatch Logs Insights 쿼리 결과 샘플
- pytest 실행 로그 요약
```

---

## 4. 다른 에이전트가 읽어야 할 필수 참조 문서

AgentCore Observability를 V1에 실제 적용하고, 테스트 계획/결과서를 작성하려면
아래 문서를 순서대로 읽어야 한다.

### 4.1 아키텍처 이해 (먼저 읽기)

| 순서 | 파일 | 읽는 이유 |
|------|------|-----------|
| 1 | `agentcore/agentcore.json` | 런타임 구조, 환경변수, 모델 ID 확인 |
| 2 | `src/lovv_agent/config.py` | RuntimeConfig 파싱, 노드별 모델 설정 해석 |
| 3 | `src/lovv_agent/harness.py` | 그래프 조립, 노드 주입 구조 (계측 래핑 지점) |
| 4 | `src/lovv_agent/graph.py` | LangGraph 노드 등록명, 라우팅 구조 |
| 5 | `src/lovv_agent/state.py` | 상태 객체 구조, `TraceState`, `recommendation_request_id` |
| 6 | `src/lovv_agent/adapters/aws_runtime.py` | Bedrock/S3Vectors/DynamoDB 어댑터 (서브스팬 래핑 대상) |

### 4.2 Observability 설계 (계측 구현 시)

| 순서 | 파일 | 읽는 이유 |
|------|------|-----------|
| 7 | `docs/specs/LOVV_AGENTCORE_OBSERVABILITY_SPEC.md` | OTel 스팬 계층, JSON 로그 스키마, 안전 필터, 컴포넌트 설계 전체 |
| 8 | `docs/specs/LOVV_V1_OBSERVABILITY_CICD_SPEC.md` §3 | V1 고정 계약 (스팬 이름, 필수 지표, 로그 스키마) |

### 4.3 기존 테스트 패턴 이해 (보고서 작성 시)

| 순서 | 파일 | 읽는 이유 |
|------|------|-----------|
| 9 | `tests/test_harness.py` | 전체 harness E2E 테스트 패턴, 모킹 구조 |
| 10 | `tests/test_graph_integration.py` | 그래프 경로별 검증 패턴, fallback 케이스 |
| 11 | `tests/test_aws_smoke.py` | opt-in 라이브 smoke 테스트 구조 |
| 12 | `intent_playground/README.md` | Intent prompt 평가 도구 사용법 |
| 13 | `docs/tasks/results/AGENTCORE_V1_FM_ROUTING_RESULT.md` | 기존 결과서 작성 관례 |

### 4.4 배포/검증 (라이브 테스트 시)

| 순서 | 파일 | 읽는 이유 |
|------|------|-----------|
| 14 | `agentcore/.cli/deployed-state.json` | 현재 배포된 런타임 ID, ARN |
| 15 | `scripts/invoke_live_recommendation.py` | 라이브 E2E 호출 스크립트 |
| 16 | `app/LovvAgentV1/main.py` | 엔트리포인트 (OTel 초기화 코드 삽입 위치) |

---

## 5. 실행 순서 요약

```text
[Phase A — 계측 구현]
 1. §4.1 문서 읽고 아키텍처 파악
 2. §4.2 Observability SPEC 읽고 설계 이해
 3. harness.py에 노드 스팬 래핑 추가
 4. adapters/aws_runtime.py에 서비스 서브스팬 추가
 5. main.py에 OTel SDK 초기화 추가
 6. 단위 테스트로 스키마 정합/denylist 누출 검증

[Phase B — 테스트 계획서 작성]
 1. §2 구조에 따라 docs/tasks/results/LOVV_V1_TEST_PLAN.md 작성
 2. 현재 프로젝트 상태에 맞게 TC 목록 확정

[Phase C — 테스트 실행 및 결과서 작성]
 1. 로컬 pytest 실행 → 기능 TC 결과 기록
 2. 배포 후 라이브 호출 → 비기능 측정값 기록
 3. X-Ray/CloudWatch 확인 → Observability TC 결과 기록
 4. §3 양식에 따라 docs/tasks/results/LOVV_V1_TEST_RESULT.md 작성
```

---

## 6. 경계

- 추천 품질 평가(정확도, relevance 등)는 본 spec 범위 밖 → Phase 3 AgentCore Evaluations
- CI/CD 자동 게이트는 본 spec 범위 밖 → Observability 검증 완료 후 별도 작업
- 성능 SLO 절대값은 본 테스트에서 baseline으로 **측정만** 하며, 임계값 확정은 별도
- `/recommendations` 스키마·런타임 토폴로지·추천 로직은 변경하지 않음
