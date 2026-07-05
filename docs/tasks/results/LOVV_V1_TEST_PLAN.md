# LovvAgentV1 테스트 계획서 (Draft)

> 작성일: 2026-06-24
> 근거 SPEC: `docs/specs/LOVV_V1_TEST_PLAN_SPEC.md`
> 런타임: LovvAgentV1 · 리전: us-east-1
> 상태: 초안 — 실행 전 §0 사전조건 충족 필요

---

## 0. 실행 사전조건 (먼저 처리)

| ID | 사전조건 | 상태 | 비고 |
|----|----------|------|------|
| P0-1 | `scripts/capture_e2e_state.py`가 fixture 입력을 받도록 패치 | **미완** | 현재 payload 하드코딩 1건. `--input PATH` / `--input-dir` 추가 필요 (§5.A) |
| P0-2 | AWS 자격증명 + `LOVV_ENABLE_AWS_SMOKE=1` | 확인 필요 | Bedrock / S3Vectors / DynamoDB 접근 |
| P0-3 | 배포된 AgentCore Runtime invoke 가능 | 확인 필요 | `agentcore/.cli/deployed-state.json` 런타임 ID |
| P0-4 | OTel 노드 계측(Phase A) 구현 여부 | **확인 필요** | 미구현 시 NF-*/OB-* 미실행 처리 |
| P0-5 | 데이터 정합성 선행 점검 | 확인 필요 | S3 Vector metadata에 `city_id`·`theme_tags`·`ddb_pk/sk` 존재, theme_tags↔assigned_theme 정합 (`theme_mapping_mismatch_audit.json` 활용). 누락 시 city 비교/DynamoDB enrichment가 구조적으로 실패하므로 §3.A 결과가 오염됨. 근거: `candidate_evidence_agent §9.2`, `evaluation_results §9.2` |

> P0-1이 없으면 §5의 E2E 증빙은 하드코딩 1건만 가능하다. 다중 fixture 증빙(이 계획의 핵심)은 P0-1 선행이 필수다.

---

## 1. 테스트 목적

- LovvAgentV1 LangGraph 파이프라인이 정상 입력에 대해 **각 노드가 설계된 structured output을 반환**하는지 확인 (정상 경로)
- Fallback 경로(no-candidate, insufficient, validation retry 소진, clarification)가 의도대로 동작하는지 확인
- 노드별 실제 실행 결과(검색 후보, CE 패키지, Planner 출력 등)를 **문서로 증빙** (§5)
- (Phase A 계측 구현 시) OTel 스팬/로그 스키마 준수 및 노드별 레이턴시·토큰·에러율 baseline 확보

**범위 밖:** 추천 품질 평가(→ `docs/specs/LOVV_V1_CITY_SELECTION_EVAL_SPEC.md`, Phase 3), SLO 절대값 확정, CI/CD 자동 게이트.

---

## 2. 테스트 환경

| 항목 | 값 |
|------|-----|
| 런타임 | LovvAgentV1 (AWS Bedrock AgentCore Runtime) |
| 리전 | us-east-1 |
| Python | 3.12 |
| 프레임워크 | LangGraph ≥0.6 |
| LLM 모델 | openai.gpt-oss-120b-1:0 (전 노드 공통) |
| **LLM reasoning** | **`reasoning_effort="low"`** (intent / candidate_reason_claim / planner_copy 적용 — 2026-06-24 변경). gpt-oss는 완전 off 불가, low가 바닥 |
| Embedding | amazon.titan-embed-text-v2:0 |
| 벡터 저장소 | S3 Vectors (lovv-vector-dev / kr-tour-domain-v1) |
| DB | DynamoDB (TourKoreaDomainData) |
| Observability | OTel SDK → ADOT Collector → X-Ray + CloudWatch (Phase A 구현 시) |
| 테스트 도구 | capture_e2e_state.py, invoke_live_recommendation.py, intent_playground, pytest |

**city_score live 항목 전제** (결과 해석 시 필요): semantic_evidence + theme_coverage + theme_balance − scale_correction + candidate_sufficiency. `distance_penalty`는 **userLocation 있을 때만**, `congestion_penalty`는 휴면(0), `soft_similarity`는 soft 신호 있을 때만. (planner는 후보를 받은 순서대로 배치 — 재정렬 없음)

---

## 3. 테스트 케이스 분류 및 입력 fixture 매핑

입력은 `docs/tasks/results/agent_input_payloads/`의 fixture를 사용한다. 기존 8개(`01`–`07`, `99`) + testset 변환 12개(`tc0NN_*`, 미식 제외) = **20개**.

### 3.A 기능 테스트 — 정상 경로

| TC-ID | 시나리오 | 입력 fixture | 검증 기준 |
|-------|----------|--------------|-----------|
| FN-02 | 긴 쿼리 → Intent LLM structured output | 01, tc009, tc017 | Converse 호출, 파싱 성공, execution_mode 기록 |
| FN-03 | 도시 발견 정상 경로 | 01, tc009, tc010, tc011, tc012 | status=ok, selected_city 존재, recommended_places ≥ 3 |
| FN-04 | 축제 시드 모드 | 02 | festival_candidates 포함, CE 패키지 정상 |
| FN-05 | Planner 정상 일정 생성 | tc009, tc012, tc017 | itinerary 항목 수 = 후보 수, validation passed |
| FN-06 | Planner LLM copy explanation | tc009, tc017 | body/reason에 LLM 생성 텍스트 존재 |
| FN-07 | Supervisor 전체 라우팅 | 전 fixture | visited_nodes 순서 = 설계 그래프 순서 |
| FN-08 | Response Packager 마스킹 | 전 fixture | 내부 필드(candidate_reason_claims 등) 미노출 |
| FN-09 | 전체 E2E `/recommendations` | 01, tc009–tc020 | HTTP 200, 응답 스키마 준수 |
| FN-입력추출 | AgentCore/HTTP wrapper 파싱 | 06, 07 | extract_recommendation_payload 정상 |
| FN-거리 | userLocation 거리 감점 경로 | 04, tc015, tc016, tc017, tc018 | distance_penalty > 0, 출발지(서울/대구) 차이 반영 |

### 3.B 기능 테스트 — Fallback/에러 경로

| TC-ID | 시나리오 | 입력 fixture | 검증 기준 |
|-------|----------|--------------|-----------|
| FB-03 | no-candidate (내륙 도시 앵커 + 해안 테마) | 22 (map_marker 영양 + sea_coast) | status=no_candidate, failure_signal=`no_city_after_theme_gate`, needs_clarification |
| FB-05 | insufficient candidates → 축소 일정 | 04·07·11 | 축소 일정, userNotice "후보 수가 적어…축소 일정을 구성" 포함 |
| FB-검증 | 스키마 validation negative | 18 (map_marker destinationId 누락) | 안전 거부, 에러 미전파 |

**입력만으로 재현 불가 → 별도 fault injection 필요 (이번 라운드 범위 밖, 명시):**
FB-01(Intent LLM 실패 → safe fallback), FB-04(Planner validation retry 3회 소진), FB-06(Supervisor unsafe fallback), FN-01(짧은 쿼리 deterministic 모드 — naturalLanguageQuery 없는 fixture 필요).

### 3.C 비기능 테스트 — Observability 기반 (Phase A 계측 구현 시)

NF-01~NF-09: 전체/노드별 레이턴시, BedrockConverse·S3Vectors·DynamoDB 서브스팬 지연, 토큰 사용량, 에러율, retry_count, denylist 누출. **P0-4 미충족 시 노드별 항목은 "미실행 — 계측 미구현"으로 기록** (단, 전체 latency·서비스 서브스팬·토큰은 배포 트레이스로 측정 가능).

**NF-비용 (신규, 트레이스에서 측정):** 근거 `evaluation_results §4` (Ours 평균 ~90 S3 query + ~711 DynamoDB GetItem 추정).

| TC-ID | 측정 | 검증 기준 |
|-------|------|-----------|
| NF-COST-s3 | 요청당 S3 Vector query 수 | 예산 상한 내 (값 기록 후 상한 확정) |
| NF-COST-ddb | 요청당 DynamoDB GetItem 수 | primary-only rehydration 준수(예비 후보 무분별 lookup 없음) |
| NF-LAT-ceil | 전체 요청 latency 상한 | baseline 측정(실측 ~21.5s 관측됨) 후 상한 정의 — 상한 미정 시 "기록만" |

### 3.D Observability 계측 검증 (Phase A 구현 시)

OB-01~OB-05: AGENT_NODE_METRIC JSON 스키마, 스팬 3계층, requestId 정렬, X-Ray trace 도달, CloudWatch Logs Insights 쿼리. **P0-4 의존.**

### 3.E 스키마 계약 — 필수 필드 완전성

FN-08(마스킹)·FN-09(200)는 노출/상태코드만 본다. 별도로 **필수 필드 부재 시 다운스트림 크래시**를 검증한다. state dump로 즉시 확인 가능. 근거: `candidate_evidence_agent §5`, Planner 출력 명세, `05_agent_spec §7.4`.

| TC-ID | 대상 | 검증 기준 |
|-------|------|-----------|
| SC-CE | CE 패키지 | `status`, `selected_city`, `recommended_places` 등 필수 필드 존재 (부재 시 Planner 크래시) |
| SC-PLAN | Planner 출력 | `itinerary`, `recommendationReasons` 등 필수 필드 존재 |
| SC-FEST | 축제 검증 | `date_status`, `confidence` 존재 (없으면 Planner가 confirmed 판정 불가) |
| SC-API | `/recommendations` 200 | 응답 계약 필수 필드 완전성 (`selectedDestination`, `itinerary`, `confidence` 등) |

### 3.F 그라운딩·안전 정책

문서가 명시한 금지사항(`05_agent_spec §11`) 검증. 일부는 기존 fixture(02 축제, tc009 등)로 관측 가능.

| TC-ID | 대상 | 검증 기준 |
|-------|------|-----------|
| SF-FEST | 미확정 축제 배치 금지 | `date_status≠confirmed` 축제가 확정 일정으로 배치되지 않음 (Planner gate) |
| SF-GROUND | 설명 그라운딩 | recommendationReasons가 검색된 장소에만 근거 — 출처 없는 장소 사실 생성(환각) 없음 |
| SF-ACCOM | 숙소 직접 추천 금지 | Planner가 호텔명·예약정보 생성 안 함, 검색 링크만 |

---

## 4. 판정 기준 (Pass/Fail)

| 기준 | Pass 조건 |
|------|-----------|
| 기능 정상 경로 | 3.A 전 TC Pass (expected structured output 반환) |
| Fallback·입력검증 | 3.B 전 TC Pass (의도한 fallback 동작·상태 기록, negative 입력 안전 격리) |
| 스키마 계약 | 3.E 전 TC Pass (필수 필드 100% 존재) |
| 그라운딩·안전 | 3.F 전 TC Pass (금지사항 위반 0) |
| Observability 스키마 | (계측 구현 시) AGENT_NODE_METRIC 필드 100% 존재, denylist 누출 0 |
| 에러율 | 정상 시나리오에서 status=error = 0 |

> LLM 노드(FN-02, FN-06)의 Pass는 **구조·존재 검사**다(파싱 성공 / 필드 존재). 내용 품질은 보지 않는다 — 품질은 Phase 3.

---

## 5. 테스트 실행 방법

### 5.0 TC군 → 수집원 매핑 (어느 항목을 무엇으로 수집하나)

| TC군 | 수집원 | 도구 | 비고 |
|------|--------|------|------|
| §3.A 기능 정상 (FN-*) | **로컬 e2e state dump** | `capture_e2e_state.py --live` | 노드 내부 상태 필요. 로컬 프로세스 + 실제 AWS 데이터 서비스 |
| §3.B Fallback·입력검증 (FB-*, FB-VAL-*) | **로컬 e2e state dump** | `capture_e2e_state.py --live` | failure_signals·거부 상태 |
| §3.E 스키마 계약 (SC-CE/PLAN/FEST) | **로컬 e2e state dump** | `capture_e2e_state.py --live` | 내부 패키지 필드 완전성 |
| §3.F 그라운딩·안전 (SF-*) | **로컬 e2e state dump** | `capture_e2e_state.py --live` | 내부(date_status·그라운딩) + 최종 응답 |
| FN-08 마스킹 / FN-09 200 / SC-API | **공개 응답** | `invoke_live_recommendation.py` (로컬 in-process) | 응답 JSON만 필요할 때 |
| §3.C 비기능 NF-* (latency·서브스팬·토큰·비용) | **배포 invoke → CloudWatch/X-Ray 트레이스** | `invoke_deployed_runtime.py` → `fetch_traces.py` | **로컬 latency 사용 금지.** 배포 런타임만 트레이스 생성 |
| §3.D Observability OB-* | **배포 invoke → CloudWatch/X-Ray** | `invoke_deployed_runtime.py` → `fetch_traces.py` / Logs Insights | Transaction Search 전제 |
| P0-5 데이터 정합성 | **오프라인 데이터 점검** | S3 Vector/DynamoDB 직접 조회, `theme_mapping_mismatch_audit.json` | 런타임 무관 선행 |
| 회귀(보조) | 로컬 단위테스트 | `pytest` | 증빙 아님 |

**테스트는 두 경로로 진행한다:**

**경로 1 — 로컬 live harness** (`capture_e2e_state.py --live`, `invoke_live_recommendation.py`): **src/ 코드를 in-process로 실행**한다(실제 AWS 데이터 서비스는 호출하지만 배포 런타임은 아님). 따라서 **재배포 없이 src 변경을 즉시 검증**할 수 있다 — 기능·스키마·안전·LLM 재시도 동작·노드 state 증빙(§3.A/B/E/F)이 여기 대상. `.env.local`을 로드해 RuntimeConfig를 채운다. **한계:** CloudWatch/X-Ray 트레이스가 없고, 로컬 프로세스 latency는 프로덕션 대표값이 아니다.

**경로 2 — 배포 런타임 invoke** (`invoke_deployed_runtime.py` → `fetch_traces.py`): **배포된 app/ 코드**를 호출한다 → src 변경을 반영하려면 **재배포가 선행**되어야 한다. **기본 동작은 fixture마다 새 `runtimeSessionId` = 새 MicroVM(격리·콜드)**이며 session을 유지하지 않는다(워밍 latency를 재려면 `--session-id`로 한 세션을 고정). **NF/OB·CloudWatch/X-Ray 트레이스·프로덕션 latency(§3.C/D)는 이 경로에서만** 측정된다.

> 요약: **기능·출력·재시도·노드증빙 = 경로 1(로컬, 재배포 불필요), latency·관측 = 경로 2(재배포 후, 트레이스).**

**왜 deployed만으로 전부 못 하고 로컬 live가 필요한가:**

- **노드 내부 state를 deployed로는 못 본다.** 배포 런타임은 **마스킹된 공개 응답만** 반환한다. Intent 결과·S3Vectors 후보·DynamoDB 조회·CE 패키지·Planner 내부 출력·candidate_reason_claims 등 **마스킹 전 노드 state(§2.6/§7 증빙)** 는 `capture_e2e_state.py`의 in-process `invoke_state()` 로만 덤프된다. 경로 2의 공개 응답으로는 "agent가 실제로 무엇을 가져와 무엇을 만들었는지"를 증빙할 수 없다.
- **디버깅 / fault isolation.** TC가 실패했을 때 로컬은 예외·스택트레이스·중간값을 직접 본다. deployed는 트레이스/로그로 간접이라 어느 노드·계층에서 깨졌는지 파악이 느리다.
- **비용.** deployed invoke는 MicroVM 콜드스타트 + Transaction Search ingestion 비용이 매 호출 발생. 로컬 반복은 데이터 서비스 호출 비용만 든다.

반대로 **로컬이 못 주는 것**(프로덕션 latency, CloudWatch/X-Ray 관측, `main.py`·엔트리포인트·OTel 초기화·env 주입 같은 배포-런타임 통합)은 deployed에서만 나온다. → **두 경로는 상호 보완이며 어느 하나로 전부를 대체할 수 없다.**

### 5.A E2E 노드별 state 증빙 (§2.6 핵심) — capture_e2e_state.py

노드 내부 state 전체를 dump하므로 §2.6 증빙의 주 도구. **단, P0-1 패치 필요** (현재 payload 하드코딩 1건).

```powershell
# (1) 패치 전 — 형태 검증용 mock 1건
uv run scripts/capture_e2e_state.py --mock

# (2) 패치 후 — fixture 단건 라이브
$env:LOVV_ENABLE_AWS_SMOKE='1'; uv run scripts/capture_e2e_state.py --live --input docs/tasks/results/agent_input_payloads/tc009_chat_nature_coast_quiet.json

# (3) 패치 후 — fixture 폴더 일괄 (권장)
$env:LOVV_ENABLE_AWS_SMOKE='1'; uv run scripts/capture_e2e_state.py --live --input-dir docs/tasks/results/agent_input_payloads
```

산출: `docs/tasks/results/e2e_state_dump_<timestamp>.json` (payload별 1개, requestId로 추적).

### 5.B 공개 응답 확인 — invoke_live_recommendation.py

마스킹된 `/recommendations` 응답만 필요할 때 (FN-08, FN-09).

```powershell
$env:LOVV_ENABLE_AWS_SMOKE='1'; Get-Content docs/tasks/results/agent_input_payloads/tc016_chat_coast_rest_daegu_daytrip.json | uv run python scripts/invoke_live_recommendation.py
```

### 5.C 배포 런타임 invoke (NF/OB 전용) — invoke_deployed_runtime.py

**이것만 CloudWatch/X-Ray 트레이스를 생성한다.** (5.A/5.B는 로컬 in-process라 트레이스 없음.)

```powershell
# 배포 런타임을 실제 invoke (fixture 폴더 일괄) → fixture별 traceId 요약 저장
uv run python scripts/invoke_deployed_runtime.py --input-dir docs/tasks/results/agent_input_payloads

# 생성된 traceId로 트레이스 자동 수집 (NF·OB 입력)
uv run --python 3.12 scripts/fetch_traces.py --summary docs/tasks/results/deployed_invoke_trace_summary.json --out docs/tasks/results/traces_fetched.json --profile skn26_final
```

### 5.D Intent 일관성

```powershell
uv run python intent_playground/run.py --repeat 3
```

### 5.E Observability 수집 (Phase A 구현 시)

자동: `fetch_traces.py`가 X-Ray `batch_get_traces`(노드/서비스 서브스팬·latency)와 CloudWatch Logs Insights(`logType="AGENT_NODE_METRIC"`, `--logs` 옵션)를 끌어온다. 수동: X-Ray ServiceLens trace map. **주의:** `/ping` InternalOperation 스팬은 제외하고 `/invocations` traceId만 집계(fetch_traces가 자동 분리).

### 5.F (보조) 회귀 방지 pytest — 결과서 증빙 아님

```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest -q
```

---

## 6. 노드별 실행 결과 상세 기록 항목 (§2.6)

각 fixture E2E 실행 시 결과서(`LOVV_V1_TEST_RESULT.md`)에 기록: 요청 Payload → Intent 결과(execution_mode, active_required_themes) → S3Vectors 검색 결과(place_id, title, city_id, distance, theme_tags) → DynamoDB 조회(PK/SK, overview, found) → CE 패키지(selected_city, mode, recommended_places, failure_signals) → Festival Verifier(해당 시) → Planner 출력(itinerary day/slot/placeId/title/body/reason, validation_result) → Supervisor(visited_nodes, fulfilled_matrix) → 최종 공개 응답.

캡처원: `capture_e2e_state.py`의 state dump에서 각 슬라이스 추출.

---

## 7. 실행 순서 요약

```text
[준비] P0-1 capture 패치 → P0-2/3 AWS·런타임 확인 → P0-4 계측 여부 확인 → P0-5 데이터 정합성
[로컬 증빙] 5.F pytest(회귀) → 5.A --mock(형태) → 5.A --live --input-dir
            → 기능·Fallback·입력검증·스키마계약·그라운딩/안전(§3.A/B/E/F) state dump에서 추출
[배포 트레이스] 5.C invoke_deployed_runtime → fetch_traces → 비기능·Observability(§3.C/D) 채움
[기록] §6 항목으로 LOVV_V1_TEST_RESULT.md 작성
```

---

## 8. 알려진 갭 / 한계

- FB-01/04/06, FN-01은 입력만으로 재현 불가 → fault injection 또는 전용 fixture 필요(별도 라운드).
- Observability(NF/OB)는 Phase A 계측 선행. 미구현 시 baseline 미확보.
- 입력 fixture는 **기능(출력 정상 여부)** 검증용이며 추천 품질 oracle이 아니다. testset 유래 12건은 미식·축제 외 일반 테마만 포함(폐쇄 풀 편향은 품질평가에서만 문제).
- oh_my_documents 스펙은 V1보다 큰 에이전트(멀티턴·conversation_summary·feedbackHistory 개인화·session 동시성)를 기술하나, **이들은 배포 V1 미구현으로 본 계획 범위 밖**(V2/별도). §3.E/3.F는 V1에서 실측 가능한 것만 반영함.
