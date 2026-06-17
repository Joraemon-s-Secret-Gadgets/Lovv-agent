# 05 · AgentCore 전환 계획서 (단계 · 체크리스트)

기준일: 2026-06-17 · 신뢰도 규칙은 [README](./README.md) 참조.
목적: 현재 단계(로컬 LangGraph 통제형)에서 **(P1) AgentCore Runtime 이관 → (P2) 로그 기반 tool
외부화 → (P3) 자율형 멀티에이전트 전환**으로 단계적으로 넘어가는 작업을 순서·체크리스트·게이트로
정리한다.

## 0. 전환 개요

```text
현재(P0)            P1                    P2 (log-gated)         P3
로컬 LangGraph  →  AgentCore Runtime  →  병목 tool만 Gateway  →  자율형(관리형
supervisor(통제형)  단일 호스팅(통제형)     외부화(부분 분리)        multi-agent)
```

원칙(전 단계 공통):
- **게이트 통과 후 진행** — 각 단계는 직전 단계의 검증 항목을 모두 통과해야 다음으로 넘어간다.
- **`/recommendations` 응답 계약 불변** — 모든 단계에서 공개 계약을 깨지 않는다.
- **신뢰도/관측 우선** — "추정"으로 결정하지 말고 CloudWatch/OTel 로그로 확인 후 결정한다.
- **롤백 가능** — 각 단계는 직전 상태로 되돌릴 수 있는 경로를 유지한다.

대분류 관점([03] 멀티에이전트 2분류): P1~P2는 **통제형(오케스트레이션)** 유지, P3에서 **자율형
(model-driven)**으로 이동한다. P3는 가장 큰 변경이자 위험 구간이므로 guardrail을 강제한다.

---

## Phase 1 — AgentCore Runtime 이관 (통제형 유지)

목적: 코드/검색/LLM 로직을 바꾸지 않고 `harness.py`를 AgentCore Runtime의 HTTP entrypoint 뒤에
올린다(lift-and-shift). 이 단계의 성능 변화는 콜드스타트·자격증명 수준이고, **핵심 산출물은
관측성 확보**다([01] §3).

### 1-1. 사전 준비 체크리스트

- [ ] `agentcore --version` / `--help`로 현재 CLI 하위 명령 확인(가이드 §3)
- [ ] AWS 자격: Bedrock invoke, S3 Vectors query, DynamoDB read, CloudWatch write, runtime role(가이드 §3)
- [ ] `Lovv-agent` 자체 검증: `uv sync` / `uv run pytest` / `compileall`(가이드 §4)
- [ ] (선택) live smoke: `tests/test_aws_smoke.py`로 실제 리소스 연결 확인(가이드 §4)

### 1-2. 패키징/엔트리 체크리스트

- [ ] `lovv_agent` 패키지를 `app/MyAgent/`로 이식(복사 or wheel), `prompts/*.md` 포함 확인(가이드 §6)
- [ ] `app/MyAgent/pyproject.toml` 최소 의존성 정렬, 불필요 의존성 제거(가이드 §7)
- [ ] `main.py`: payload→`/recommendations` 정규화 + `build_live_harness().invoke()`만 호출(가이드 §8)
- [ ] `main.py`에 OTel/`LangchainInstrumentor` 계측 활성화(= 관측성 확보, [01] §3)
- [ ] 로그에 원문 prompt·raw RAG·credential·PII 미출력 확인(가이드 §8/§16)

### 1-3. 설정 체크리스트 (모델/리전)

- [ ] `agentcore.json` envVars: `LOVV_AWS_REGION=us-east-1`, 임베딩 `amazon.titan-embed-text-v2:0`(가이드 §9, [02] §2)
- [ ] `LOVV_LLM_MODEL_ID`는 structured outputs 지원 모델로 — 시작값 `openai.gpt-oss-120b-1:0` 유지([02] §5)
- [ ] `LOVV_AWS_PROFILE`은 배포 env에서 제외(IAM role 사용, 가이드 §9)
- [ ] 배포 전 `list-foundation-models` / `list-inference-profiles`로 modelId 확정([02] §5)

### 1-4. 배포/검증 게이트 (→ P2 진입 조건)

- [ ] `agentcore dev` 로컬 `/invocations` 호출 성공(가이드 §10)
- [ ] `agentcore deploy --diff`로 의도한 변경만 확인 → `deploy` → `status`(가이드 §11)
- [ ] 배포 Runtime ARN으로 실제 호출 성공, 응답이 `/recommendations` 계약과 일치(가이드 §12/§16)
- [ ] **관측성 동작 확인**: node별 latency, S3 Vectors/DynamoDB/Bedrock 구간이 CloudWatch/OTel에
      기록됨([01] §6) — 이게 P2의 판단 근거이므로 필수
- [ ] Runtime role 권한이 Bedrock/S3 Vectors/DynamoDB에 도달, AccessDenied 없음(가이드 §11/§16)

롤백: 직전 로컬 harness 실행 경로 유지(`scripts/invoke_live_recommendation.py`).

---

## Phase 2 — 로그 기반 tool 외부화 (Gateway, 부분 분리)

목적: P1에서 확보한 관측 로그로 **실제 병목 tool을 식별**하고, **그 tool만** AgentCore Gateway
타깃(tool-as-service)으로 외부화한다. 통제형 구조는 유지한다(가이드 §15, [03] §1-3).

> 핵심: "성급한 외부화 금지". 로그가 정당화하지 않으면 in-process로 둔다(네트워크 홉이 오히려
> 지연을 늘릴 수 있음, [01] §4-5).

### 2-1. 측정 게이트 (외부화 결정 기준)

다음 로그를 1~2주 수집 후 판단:

- [ ] node별 latency 분포에서 상위 병목 노드 식별([01] §6)
- [ ] tool별 호출 횟수·합산 지연: S3 Vectors 쿼리(테마 검색), DynamoDB GetItem, Scoring 등
- [ ] 외부화 후보가 (a) 지연 비중이 크고 (b) 독립 확장이 이득인지 확인
- [ ] **먼저 in-process 최적화로 해결되는지 점검**: 테마 검색 병렬화·DynamoDB 배치([04])로
      해소되면 외부화 불필요

### 2-2. 외부화 작업 체크리스트 (병목 확인된 tool만)

가이드 §15 후보: Scoring, Matrix Transition, Link Builder, Weather Trends.

- [ ] 대상 tool의 입출력 계약을 Gateway 타깃 인터페이스로 고정(순수 함수 경계 유지)
- [ ] 인증/권한은 AgentCore Identity로 위임(가이드 §15)
- [ ] 외부화 전/후 동일 입력에 대한 출력 동등성 테스트(회귀 방지)
- [ ] 외부화 후 end-to-end 지연이 **개선됐는지** 로그로 재확인(악화 시 롤백)

### 2-3. 게이트 (→ P3 진입 조건)

- [ ] 외부화한 tool이 계약 동등 + 지연 개선(또는 확장성 확보)으로 검증됨
- [ ] in-process 최적화([04] 병렬화/배치)가 먼저 적용되어 baseline이 안정화됨
- [ ] (멀티턴 비중 크면) AgentCore Memory 도입으로 turn 간 재사용 확인([01] §4, [03] §1-3)

롤백: Gateway 타깃을 in-process 호출로 되돌리는 feature flag 유지.

---

## Phase 3 — 자율형(관리형 multi-agent) 전환

목적: [03] 2분류의 **자율형(model-driven)**으로 이동 — Bedrock 관리형 multi-agent collaboration
등에서 LLM이 라우팅/위임을 결정. 외부·이종 에이전트 협업이 실제로 필요해질 때의 단계다.

> ⚠️ 위험 고지 [확인됨/추정·중]: 자율형은 비용 예측성·재현성·`/recommendations` 계약 안정성을
> 떨어뜨린다([03] §1-2). **따라서 P3는 "필요해질 때만", 그리고 guardrail 강제 하에서만** 진행한다.
> 통제형으로 충분하면 P2에서 멈추는 것이 정답일 수 있다.

### 3-1. 진입 조건 (모두 충족 시에만)

- [ ] 외부/이종 에이전트 연동, 동적 협업 등 **통제형으로 불가능한 요구**가 실재함
- [ ] P1·P2 게이트 통과 + 안정적 baseline 로그 확보
- [ ] guardrail 인프라 준비: **AgentCore Policy(Cedar)** + **Evaluations**([03] §2-4)

### 3-2. 안전한 점진 전환 체크리스트

- [ ] **계약 방어선 유지**: 자율 라우팅을 도입해도 `fulfilled_matrix` 검증·Response Packager·
      Validation은 그대로 남겨 최종 출력 계약을 강제
- [ ] **Policy 강제**: 국가 혼합 금지·미검증 축제 확정 금지·raw trace 저장 금지를 Cedar 정책으로
- [ ] **shadow / A-B 전환**: 자율형을 트래픽 일부에만 적용해 통제형과 품질·비용·지연 비교
- [ ] **Evaluations 회귀 감시**: trajectory·조건 충족·근거성·일정 구조를 자동 평가([03] §2-4)
- [ ] **비용/쿼터 가드**: 자율 루프의 LLM 호출 폭증 대비 max 호출수·예산 한도·RPM/TPM 모니터([02] §6)

### 3-3. 완료 게이트

- [ ] 자율형이 통제형 대비 품질 동등 이상 + 계약 위반 0건(Evaluations 기준)
- [ ] 비용/지연이 허용 범위, 쿼터 스로틀 없음
- [ ] 미달 시 통제형으로 롤백(P2 상태 유지)

롤백: P3는 항상 P2(통제형) 구성으로 되돌릴 수 있는 라우팅 스위치를 유지한다.

---

## 단계 게이트 요약

| 단계 | 핵심 작업 | 진입 조건 | 완료(게이트) | 분류 |
| --- | --- | --- | --- | --- |
| P1 | Runtime 이관 + 관측성 | — | 배포 호출 성공 + 계약 일치 + 관측 동작 | 통제형 |
| P2 | log 기반 tool 외부화 | P1 게이트 | 병목 tool 외부화 검증 + baseline 안정 | 통제형(부분 분리) |
| P3 | 자율형 전환 | 통제형 불가 요구 + guardrail 준비 | 품질 동등↑ + 계약 위반 0 + 비용 허용 | 자율형 |

## 공통 운영 체크리스트 (전 단계)

- [ ] 배포 전: unit/integration 테스트, `compileall`, `deploy --diff` 확인(가이드 §16)
- [ ] 로그 위생: credential·raw RAG·raw web·PII 원문 미기록(가이드 §16)
- [ ] 각 단계 롤백 경로 확보 후 진행
- [ ] [추정] 항목은 로그 측정으로 [확인됨] 승격/기각([01] §6)

## 권장 우선순위 (요약)

1. **P1 이관 + 관측성** — 지금 바로.
2. **in-process 최적화** 병행([04] 테마 검색 병렬화 → DynamoDB 배치, [03] 리랭커) — P2 판단 baseline.
3. **P2 tool 외부화** — 로그가 병목을 가리킬 때만, 그 tool만.
4. **P3 자율형** — 통제형으로 불가능한 요구가 생길 때만, Policy/Evaluations guardrail 하에서.
