# 결과서 작성 에이전트 인수인계 (Handoff)

> 목적: 다른 에이전트가 `docs/tasks/results/LOVV_V1_TEST_RESULT.md`를 작성하도록 필요한 입력·규칙을 한곳에 정리.
> 작성일: 2026-06-24

---

## 0. 너의 산출물과 양식

- **출력 파일**: `docs/tasks/results/LOVV_V1_TEST_RESULT.md`
- **따를 양식**: `docs/specs/LOVV_V1_TEST_PLAN_SPEC.md` §3 (결과서 템플릿 — 섹션 1~9 그대로)
- **TC 목록·판정 기준·fixture 매핑**: `docs/tasks/results/LOVV_V1_TEST_PLAN.md` (§3 매핑표, §4 Pass/Fail, §8 갭)

먼저 위 두 문서를 읽고 시작해라. 양식을 새로 만들지 말 것.

---

## 1. 넘기는 데이터 3종

### 1.1 기능·노드 증빙 (Tier 1) — 로컬 state dump

- 파일: `docs/tasks/results/e2e_state_dump_*.json` (fixture별 1개, `capture_e2e_state.py --live --input-dir` 산출)
- 입력 fixture: `docs/tasks/results/agent_input_payloads/` (각 dump의 입력)
- 용도: 결과서 **§2 기능 Pass/Fail** + **§7 노드별 E2E 증빙** 전부 여기서 추출.

state dump → §7 항목 매핑:

| §7 항목 | dump에서 꺼낼 슬라이스 |
|---|---|
| 7.1 요청 Payload | 입력 fixture JSON |
| 7.2 Intent 결과 | `execution_mode`, `active_required_themes`, 의미 신호 |
| 7.3 S3Vectors 검색 | 반환 place 목록 (place_id, title, city_id, distance, theme_tags) |
| 7.4 DynamoDB 조회 | PK/SK, found, overview, content_length |
| 7.5 CE 패키지 | status, mode, selected_city, recommended_places, failure_signals |
| 7.6 Planner 출력 | itinerary(day/slot/placeId/title/body/reason), validation_result |
| 7.7 Supervisor | visited_nodes, fulfilled_matrix |
| 7.8 최종 공개 응답 | 마스킹된 response JSON |

### 1.2 Observability (Tier 2) — 내가 트레이스에서 긁어서 줄 값

> 이건 로컬 dump에 **없다.** 배포 런타임 invoke 후 X-Ray/CloudWatch에서 수집한 값을 별도로 전달한다.
> 콘솔에서 수동으로 긁는 대신 **CLI/API로 자동 수집할 수 있다** — §5 참고. (둘 중 택1)

**(a) per-TC 측정표** — fixture(=traceId)마다 아래를 채워 넘긴다:

| 필드 | 결과서 항목 | 출처 |
|---|---|---|
| traceId | 조인키 / OB-04 | invoke 응답·trace summary |
| 전체 요청 latency | NF-01 | 최상위 invocation 스팬 duration |
| 노드별 latency (intent/candidate_evidence/planner/…) | NF-02 | `node.*` 스팬 duration |
| BedrockConverse 지연 | NF-03 | 서비스 서브스팬 |
| S3Vectors QueryVectors 지연 | NF-04 | 서비스 서브스팬 |
| DynamoDB GetItem 지연 | NF-05 | 서비스 서브스팬 |
| 토큰 (노드별 in/out/total) | NF-06 | `llmMetrics.*` |
| error 발생 수 | NF-07 | `status=error` |
| retry_count | NF-08 | 스팬/로그 |

**(b) OB 증빙 샘플** — TC마다가 아니라 대표 1건씩 캡처해 넘긴다:

| 증빙 | 결과서 항목 |
|---|---|
| AGENT_NODE_METRIC 로그 JSON 1건 (필드 전체) | OB-01 스키마 정합 |
| 스팬 계층 캡처 (최상위→노드→서비스 3계층) | OB-02 |
| 스팬/로그의 requestId 필드 값 | OB-03 (`recommendation_request_id` 정렬) |
| X-Ray ServiceLens trace map 스크린샷 + 대표 traceId | OB-04 |
| CloudWatch Logs Insights 쿼리문 + 결과 샘플 | OB-05 |

### 1.3 조인키

- `deployed_invoke_trace_summary.json` (`invoke_deployed_runtime.py --input-dir` 산출): `{fixture, traceId, statusCode}`.
- 로컬 dump(§1.1)와 트레이스(§1.2)를 **fixture명 / requestId / traceId**로 묶어 TC당 한 행으로 정리해라.

---

## 2. 고정 사실 (결과서 §1 실행 환경에 그대로)

| 항목 | 값 |
|---|---|
| Runtime ARN | `arn:aws:bedrock-agentcore:us-east-1:925273580929:runtime/LovvAgentCore_LovvAgentV1-PumZyEGRsT` |
| 리전 | us-east-1 |
| Python | 3.12 |
| LLM 모델 | openai.gpt-oss-120b-1:0 |
| reasoning_effort | **low** (intent / candidate_reason_claim / planner_copy, 2026-06-24 변경) |
| Embedding | amazon.titan-embed-text-v2:0 |
| S3 Vectors | lovv-vector-dev / kr-tour-domain-v1 |
| DynamoDB | TourKoreaDomainData |
| 배포 해시 / Runtime ID | (내가 deployed-state.json에서 확인해 채움) |

---

## 3. 해석 규칙 (반드시 지킬 것 — 오기 방지)

1. **LLM 노드(FN-02 Intent, FN-06 Planner copy)의 Pass는 구조·존재 검사다.** "파싱 성공 / 필드에 텍스트 존재"이지 내용 품질이 아니다. 품질 평가라고 쓰지 마라(→ Phase 3, 범위 밖).
2. **추천 품질(도시·장소·일정이 좋은지)은 이 결과서 범위 밖이다.** `LOVV_V1_CITY_SELECTION_EVAL_SPEC.md` 소관. 결과서에 품질 결론을 넣지 마라.
3. **city_score 해석 시:** live 항목은 semantic_evidence + theme_coverage + theme_balance − scale_correction + candidate_sufficiency. `distance_penalty`는 **userLocation 있는 fixture(04, tc015~018)에서만** 0이 아니다. `congestion_penalty`는 항상 0(휴면). 0이라고 버그로 적지 마라.
4. **Planner는 후보를 받은 순서대로 배치한다(재정렬 없음).** FN-05 검증은 "itinerary 항목 수 = recommended_places 수, validation passed"이지 일정 최적화 품질이 아니다.
5. **latency(NF-01~05)는 반드시 배포 트레이스 값**을 써라. 로컬 capture_e2e_state.py의 시간은 프로덕션 latency가 아니므로 NF에 쓰지 마라.
6. **미커버 TC는 "미실행"으로 명시하고 사유를 적어라**(추정으로 Pass 처리 금지):
   - FB-01(Intent LLM 실패), FB-04(Planner retry 소진), FB-06(Supervisor unsafe), FN-01(짧은 쿼리 deterministic) → 입력만으로 재현 불가, fault injection/전용 fixture 필요.
7. **에러·후보 부족을 성공으로 계산하지 마라.** no_candidate / insufficient_candidates는 의도된 fallback이면 해당 FB-TC의 Pass 근거이지 정상 추천 성공이 아니다.

---

## 4. 작성 순서 권장

```
1. SPEC §3 양식 + TEST_PLAN.md 읽기
2. §1.3 조인키로 TC↔fixture↔traceId 매핑표 먼저 구성
3. 로컬 dump로 §2(기능)·§7(노드증빙) 채움
4. 내가 준 트레이스 값으로 §4(NF)·§5(OB) 채움
5. §6 종합 판정, §8 blocker(미커버 TC), §9 첨부(트레이스 캡처)
6. §3 해석 규칙 위반 없는지 자기검토
```

---

## 5. 참고: 트레이스 자동 수집 옵션 (CLI/API)

§1.2의 Observability 값은 **콘솔 수동 수집 대신 CLI/API로 자동화 가능**하다. AgentCore는 모든
metric·span·log를 CloudWatch에 저장하고 X-Ray로도 트레이스를 전달하므로 프로그램으로 끌어올 수 있다.
다음 에이전트가 수동 캡처가 번거롭다고 판단하면 이 경로를 택해 fetch 스크립트로 만들어도 된다.

**전제:** 계정에 CloudWatch Transaction Search 활성화(1회 설정, span 반영까지 ~10분). 현재 트레이스가
콘솔에 보이는 상태이므로 켜져 있을 가능성이 높다.

**X-Ray — 트레이스·latency·서브스팬:**

- `aws xray get-trace-summaries --start-time <t> --end-time <t> [--filter-expression ...]` → traceId + 전체 latency (NF-01)
- `aws xray batch-get-traces --trace-ids <id...>` → segment 문서. 노드 스팬 + Bedrock/S3Vectors/DynamoDB 서브스팬 duration (NF-02~05, OB-02)
- `aws xray get-service-graph` → service map JSON (OB-04를 스크린샷 대신 데이터로)

**CloudWatch Logs — AGENT_NODE_METRIC·토큰·retry:**

- `aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore` → 로그그룹명 확인 (정확 이름 확인 지점)
- `aws logs start-query` → `aws logs get-query-results` (Logs Insights, `logType="AGENT_NODE_METRIC"` 필터) → 스키마(OB-01), 토큰(NF-06), retry(NF-08), 쿼리+결과(OB-05)

**조인:** `deployed_invoke_trace_summary.json`의 fixture→traceId를 입력으로, traceId별 segment + 해당
requestId의 AGENT_NODE_METRIC 로그를 묶어 fixture별 구조화 JSON으로 떨구면, 결과서는 그 JSON만 읽으면 된다.

**주의:** 스크립트화 시 boto3 인자명/응답 shape는 botocore 모델로 대조 후 작성할 것
(`xray`: get-trace-summaries / batch-get-traces, `logs`: start-query / get-query-results).
이 자동 수집을 쓰면 §9 첨부의 스크린샷 일부는 JSON 산출물로 대체된다.
