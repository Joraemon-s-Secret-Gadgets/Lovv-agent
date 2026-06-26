# Lovv 대화형 일정 빌더 — 1차 설계 문서 (Design Draft v1)

---
title: Lovv 대화형 일정 빌더 아키텍처 — 1차 설계 (초안)
project: Lovv (로브)
status: 1차 설계 (Draft · 구현 전 · 일부 확인 필요)
date: 2026-06-22
relates:
  - docs/specs/v2/LOVV_AGENTCORE_MEMORY_CHECKPOINTER_SPEC.md (checkpointer/HITL 계약 — R1~R6)
  - ADR — Lovv 개인화·에이전트 상태 아키텍처 결정 기록 (ephemeral 통합 / persistent 분리)
  - (기획) 94_kick.md, followup-requery.md, plan-detail.md, theme-detail.md
  - (팀) 멀티-에이전트-멀티-턴-구축-가이드.md + 원본 스레드 gemini.google.com/share/363c6a30a285 (패턴만 차용)
note: 본 문서는 1차 설계 캡처용. 코드는 아직 수정하지 않음.
---

## 0. 배경 · 한 줄 요약

기존 구조는 Planner가 도시 근거 관광지 후보를 **임의 배치**해 전체 일정을 자동 생성한다.
문제는 "사용자가 그 임의 동선을 그대로 받아들일지"다. 그래서 **소도시 선정까지는 그대로**
두되, **일정 구성은 사용자가 장소를 하나씩 고르며 쌓는 대화형 HITL 루프**로 바꾼다.

> Planner 역할: "후보를 임의 배치하는 자동 생성기" → "사용자가 고른 순서대로 쌓는 대화형 빌더".
> 동선은 **선택 순서**가 결정한다 (임의 배치 폐기).

## 1. 설계 원칙 (불변 규칙)

1. **동선 = 선택 순서.** 시스템이 방문 순서를 임의로 정하지 않는다.
2. **Ephemeral 통합 / Persistent 분리** (ADR 준수). 빌더 상태(체크포인트)+세션은 AgentCore
   Memory 단기, 영속 가명 개인화 프로필은 커스텀 2티어.
3. **통찰 이유는 근거 의무 · 환각 금지.** 근거 없으면 이유 문장을 생성하지 않는다.
4. **기반은 LangGraph/AgentCore Runtime.** 팀 가이드(Bedrock Agents+Lambda)는 **패턴만 차용**.
5. **Supervisor는 결정론 코드** (현 `supervisor.py` 유지, LLM 라우팅 아님).
6. **actorId = 가명 ID** (모든 계층).

## 2. 전체 흐름

```text
[1회 셋업]
  Profile Agent(가명 영속 프로필, 🔒) ┐
  Intent Agent(매 턴, action 파싱)    ├─▶ Candidate Evidence·도시 선정(1회, city gate)
                                      ┘        └─▶ 루프 시드 {도시, query_vector, anchor, budget}
                                                        │ (체크포인트 초기값)
[대화형 빌더 루프 · HITL]                                ▼
  Supervisor(결정론) ─▶ Anchor ─▶ 반경 Provider(코어 재사용·radius gate+action 필터)
        ▲                                  │
        │                                  ▼  ∥ 병렬 fan-out: DB 큐레이션 ∥ 지도 API ∥ 축제
        │                         후보 제시 ⏸ interrupt (서브 윈도우 = 사이드바)
        │                                  │  soft floor → 폴백 사다리
        └──── next anchor ◀── 사용자 픽·일정 추가 ◀──┘
                                           │ DONE
[출력]                                     ▼
  Planner(축소)+Packager: 구간 동선(교통 API)+타임라인 ─▶ 메인 타임라인(PLAN DETAIL)

[상태] AgentCore Memory 체크포인터(ephemeral, itinerary_builder) ↔ 영속 가명 프로필(커스텀 티어)
```

## 3. Candidate Evidence 3층 분해 (이 설계의 핵심)

기존 단일 패스(임베딩→검색→city gate→scoring→sufficiency→선정→이유)를 3층으로 나눈다.
도구가 이미 DestinationSearch / DynamoLookup / Scoring로 분리돼 있어 자연스럽다(신뢰도 높음).

1. **공유 검색·스코어 코어 (stateless · 재사용)** — 입력 `(query_vector, 게이트, 필터)` → 점수순
   후보. **게이트 추상화: `city | radius`** (후보가 `latitude/longitude` 보유, scoring에 거리
   페널티 존재 → 반경 게이트 가능, 코드 확인). **scoring 가중치는 context별**(도시 선정=테마
   커버리지 중심, 반경 스텝=거리 중심). **query_vector 재사용**(매 턴 재임베딩 금지).
2. **도시 선정 오케스트레이터 (1회)** — 코어를 city 게이트+테마 쿼터+축제 시드로 돌려 소도시 확정.
3. **반경 Provider (루프)** — 코어를 radius 게이트+스텝 필터로 anchor 주변에서 돌려 선택지 제시.

**산출물 변화**: CandidateEvidencePackage가 "최종 답"에서 **"루프 시드"**
`{선정 도시, query_vector, anchor(최고점 장소), budget}`로 확장 → 체크포인트 초기값이 된다.

## 4. 대화형 빌더 루프 (HITL)

매 턴 반복: **Anchor → 반경 Provider → 후보 제시(⏸ interrupt) → 사용자 픽 → next anchor**.
"DONE"이면 루프 종료 → 출력.

- **interrupt/resume = checkpointer 필수.** 이 루프 때문에 checkpointer SPEC의 Requirement 6
  (interrupt/resume)이 **후순위 옵션 → 핵심 전제로 승격**된다. 턴 사이 상태 보존도 필수이므로
  Phase 1·2(체크포인터)도 같이 필요해진다.
- **Intent action 어휘** (팀 가이드 병합): 루프 중 자연어 명령을 구조화한다 — `PICK`,
  `REPLACE_PLACE`, `EXCLUDE`, `FILTER`(=followup-requery 간판 5종), `DONE`. 이 액션이 반경
  Provider의 필터를 재파라미터화한다.

## 5. 후보 2티어 + 병렬 fan-out

후보 제시는 세 소스를 **병렬**로 합친다(팀 가이드 병합, 앞선 병렬화 분석과 연결):

| 티어 | 소스 | 통찰 이유 | 비고 |
|------|------|-----------|------|
| 큐레이션 | DB(벡터+scoring) = 반경 Provider 출력 | ○ | 검증 메타데이터·통찰 이유 |
| 보충 | 지도 API | ✕ | 식당·카페·gap-fill (기본 정보만) |
| 축제 | RAG/외부 API | 별도 | 동시 구동 |

- 식당·카페는 **별도 DB 채널을 만들지 않고 지도 API로 반경 표시**(결정).
- **2티어를 사용자에게 명시 구분**("DB 추천 vs 주변에서 찾은 곳"). API 보충 장소엔 통찰 이유를
  억지 생성하지 않는다(plan-detail §4 원칙).

## 6. Sufficiency — soft floor + 폴백 사다리

"최소 개수"를 유지하되 **하드 게이트가 아니라 soft floor**로 둔다(그래야 기존 실패 모드를 안 되살림).

- **큐레이션 최소**: floor 없음 — 극단적으로 **1곳까지 허용**(그 1곳이 anchor가 됨).
- **표시(선택) 최소**: soft floor만 둠(예: 3~5). 폴백 사다리로 채운다 —
  ① 반경 확장(N→2N) ② 지도 API 보충 ③ 그래도 미달이면 **솔직한 안내**("이 주변엔 ○곳뿐") +
  반경 넓히기/다른 도시 제안. **하드 실패로 되돌리지 않는다.**
- 효과: DB 적재량 의존(최소 개수 미충족 시 실패) 문제를 **런타임 온디맨드 보충**으로 근본 해결.
  (신뢰도: 구조 정합 높음 / 수치·동작은 설계 판단 중)

## 7. Profile Agent + Lock (팀 가이드 병합)

- **Profile Agent**가 가명 영속 프로필(DynamoDB 핫 · 커스텀 티어)에서 장기 성향을 읽어 **초기 시드(도시 선정)**
  에만 기여한다. Intent(실시간)와 분리해 프롬프트 복잡도·환각을 낮춘다.
- **루프 중 🔒 Lock** — 매 턴 재실행하지 않는다(토큰 절약). 우리 "query_vector 재사용/재계산
  금지"에 에이전트 레벨 근거를 준다. **재트리거 조건**: 동행자·테마 같은 근본 변경 시에만
  Supervisor가 다시 깨운다.

## 8. 상태 · 메모리 (단기 AgentCore / 장기 커스텀 TTL→S3)

> **최종 방향**: 단기는 AgentCore Memory, 장기는 **커스텀 DynamoDB TTL→S3**로 보관기간·삭제권을
> 직접 통제한다(ADR "ephemeral 통합 / persistent 분리" 원안). 매핑·raw PII는 어느 계층에도 노출하지
> 않는다. (AgentCore 장기 메모리는 무한 보존·수동 삭제라 보관기간 통제가 거칠어 장기 컴플라이언스
> 데이터엔 부적합 — TTL 라인이 그 약점을 메운다.)

- **단기 (AgentCore Memory)**: `itinerary_builder = { anchor, items[ ], next_anchor,
  radius_km, active_filters, budget }` + 세션 컨텍스트 + checkpoint(interrupt↔resume).
  `event_expiry`로 자동 정리. → checkpointer SPEC **Requirement 4**(serde) 대상.
- **장기 ① 파생 개인화 프로필 (DynamoDB 핫, TTL 없음)**: 가명 ID PK, 자주 읽는 선호 요약.
  Profile Agent의 읽기 소스. **지우지 않음**(개인화 유지).
- **장기 ② raw 이벤트 로그 (DynamoDB TTL → S3 콜드)**: 아래 §8.1 TTL 라인. 프로필 재계산·분석·학습용.
- **hard line**: 매핑 테이블(가명ID↔실제신원)·raw PII는 어느 저장소에도 넣지 않음(별도 KMS·최소권한
  IAM). 전 계층 **actorId = 가명 ID** 격리.

### 8.1 TTL 라인 (raw 이벤트 → S3 콜드)

1. DynamoDB 이벤트 아이템 `ttl`(epoch 초) = `now + N일`. TTL은 **best-effort**(만료 후 며칠 내,
   SLA 없음) → "N일 후 반드시"가 요건이면 `expires_at` 필드 + **읽기 시 앱레벨 필터**로 보강.
2. **DynamoDB Streams**(NEW_AND_OLD_IMAGES) 활성화.
3. **Lambda**가 TTL 삭제만 필터: `eventName == "REMOVE"` AND
   `userIdentity.principalId == "dynamodb.amazonaws.com"` (사용자/앱 삭제와 구분).
4. OLD_IMAGE(가명 상태)를 **S3 콜드**에 적재(날짜/actor-해시 파티션).
5. 용도: 프로필 재계산·분석·학습, 복귀 사용자 재하이드레이션.
6. **삭제권(right-to-erasure)**: DynamoDB + S3 **양쪽 삭제 플로우** 명시. 고볼륨 시
   `DynamoDB → Kinesis → Firehose → S3`로 확장(부트캠프 규모엔 Streams+Lambda가 단순·저렴).

## 9. Planner 역할 축소

가이드의 Planner(교통 API로 동선 최적화)는 우리 원칙(동선=선택 순서)과 충돌 →
**"순서 결정자"가 아니라 "선택된 순서의 구간 이동시간 계산(교통 API) + 타임라인 렌더"** 로 축소.
사실상 ResponsePackager + 구간 동선. 동선은 **직전 장소→새 장소 구간만** 계산하므로 단순해진다.

> **보강(원본 Gemini 스레드 확인)**: 이 구간 계산은 LLM이 아니라 **pure-code geo**
> (Haversine/Shapely)로 처리한다. 반경 게이트도 동일하게 좌표 기반 hard-filter → LLM
> 환각·지연 제거(신뢰도 높음, 정합). Planner는 데이터/좌표 전용, 텍스트 생성은 하지 않는다.

## 10. 기존 기획 문서와의 정합 / 충돌

- **plan-detail.md**: "자동 생성 결과 화면" 전제가 깨짐 → **빌더 모드 + 리뷰 모드**로 분리.
  Day 탭·지도 마커·점선 동선·통찰 이유·저장 시드는 **완성본에 그대로** 유효.
- **followup-requery.md**: 도시/테마 재추천 → **장소 단위 선택 루프**로 확장. 간판 5종 =
  Intent FILTER action. 세션 취향 벡터에 "고른 장소" 신호 추가.
- **94_kick.md**: 충돌 아님 — 공개 일정 복제는 **빌더 초기 상태를 prefill**하는 진입점. 호환.
- **candidate_evidence_runtime_retrieval.md §9**: restaurant 제외/미식=foodSearch 링크 →
  새 구조는 **지도 API로 식당 후보 직접 표시**. 이 문서는 **갱신 필요**(확인 항목).

## 11. 팀 가이드 병합 요약

| 가이드 항목 | 처리 | 비고 |
|-------------|------|------|
| 결정론 코드 Supervisor | **이미 보유** | `supervisor.py` 그대로 |
| 서브 윈도우 후보 격리 | **결합** | 우리 interrupt "후보 제시"의 UI 표현 |
| 비동기 병렬 | **결합** | 스텝별 DB∥API∥축제 fan-out |
| Profile Agent + Lock | **흡수(신규)** | §7 |
| Intent action 어휘 | **흡수(신규)** | §4 |
| 단일 DynamoDB State | **우리 2티어로** | ephemeral/persistent 분리 유지 |
| Planner 동선 최적화 | **축소 흡수** | §9 |
| Bedrock Agents+Lambda 기반 | **패턴만 차용** | 기반은 LangGraph/AgentCore |
| 토큰 70%·2.5초 | **추정치(미검증)** | 우리 환경 측정 필요 |

### 11.1 원본 Gemini 스레드 추가 검토 (결정 기록)

가이드의 원본 대화(`gemini.google.com/share/363c6a30a285`)를 추가 검토했다. 가이드엔 없던
3가지 항목의 처리 결정:

| 항목 | 결정 | 근거 |
|------|------|------|
| **Planner = Geo-Filter (Haversine/Shapely, pure code)** | **흡수(확정)** | 우리 "Planner 축소"와 일치 → §9 보강. LLM 미사용으로 환각·지연 제거 |
| **Output(Presenter) Agent 분리** | **보류** | 현 ResponsePackager 유지. 통찰 이유 렌더 분리 이점은 인정하나 후속 재검토 |
| **sLLM 생성 + 대형 LLM 릴레이 검수** (speculative) | **보류** | 지연·복잡도 트레이드오프. 우선 코드 정합성 게이트로 대체, 풀 릴레이는 후속 최적화 |
| **다중 반경 교집합** (거점 2곳 이상) | **옵션 확장** | 코어는 단일 anchor 순차 루프. 다거점(숙소 2곳 등) 여행용 확장으로만 명시 |
| Bedrock Agents + Lambda 기반 | 패턴만 차용(기결정) | 기반은 LangGraph/AgentCore |
| 단일 DynamoDB State | 우리 2티어로(기결정) | ephemeral/persistent 분리 |

> 정합성 게이트(Output 보류의 대체): Planner/검색 결과의 핵심 Key(장소명·날짜·좌표)가
> `itinerary_builder` State와 일치하는지 **코드로 1차 검수**하고, 불일치 시에만 LLM 개입을
> 검토한다. "근거 의무·환각 금지"(§1.3)의 실행 장치.

## 12. 코드 영향 (개략 · 구현 전)

- `candidate_evidence` 3층 분해 + **게이트 추상화(city|radius)** + scoring 가중치 파라미터화.
- 신규: **반경 Provider 노드**, **빌더 루프 오케스트레이터**, **Intent action 파서**,
  **Profile Agent**(가명 프로필 read+Lock), **지도 API 어댑터**(식당·카페·반경).
- 상태: `itinerary_builder` state group 추가 → checkpointer SPEC R4 serde 확장.
- HITL: checkpointer SPEC R1~R6에 직접 연결(특히 R6 interrupt/resume이 핵심으로 승격).

## 13. Observability (CloudWatch + OpenTelemetry)

빌더 루프의 **지연·비용·폴백·정합성**을 추적한다. AgentCore Observability(CloudWatch +
OTel 트레이싱, ADR §5 매핑)를 그대로 활용한다.

> **기반 스펙**: 토큰·컨텍스트 윈도우·노드 레이턴시·I/O 트레이싱의 전체 규격(OTel + AWS X-Ray +
> CloudWatch JSON Logs)은 `LOVV_AGENTCORE_OBSERVABILITY_SPEC.md`에 정의돼 있다. 아래 빌더 전용
> 메트릭은 그 스펙의 `AGENT_NODE_METRIC` JSON 스키마를 **확장**해 기록한다.

- **CloudWatch 커스텀 메트릭** (trace 전용 · 사용자 API 미노출 · `build_memory_safe_summary`
  원칙 준수 — 가명 ID·원시 후보·PII 미포함):

  | 메트릭 | 의미 |
  |--------|------|
  | `builder_loop_turns` | 한 세션의 픽 횟수(루프 길이) |
  | `radius_retrieval_latency_ms` | 반경 Provider 1스텝 지연 |
  | `checkpoint_rw_latency_ms` | interrupt↔resume(체크포인트 쓰기/읽기) 지연 |
  | `fallback_radius_expand_count` / `fallback_api_count` / `honest_notice_count` | soft floor 폴백 사다리 단계별 발생 |
  | `tier_curated_count` / `tier_api_count` | 2티어(DB vs 지도 API) 비율 |
  | `consistency_gate_fail_count` | 정합성 게이트(장소명·날짜·좌표 vs State) 실패 |
  | `profile_lock_hit` / `profile_retrigger_count` | Profile 잠금/재트리거 |
  | `tokens_per_turn` | 턴당 토큰(가이드 70% 주장 실측 근거) |
  | `s3_query_count` / `ddb_get_item_count` | 기존 candidate 메트릭 재사용 |

- **OTel 트레이스**: 노드별 span(Intent→Supervisor→반경Provider→후보제시→픽), interrupt
  지점·resume 경계 표시 → 턴 간 흐름 가시화.
- **CloudWatch 알람**: `radius_retrieval_latency_ms` p95, `consistency_gate_fail_count` 비율,
  `checkpoint_rw_latency_ms`, `tokens_per_turn` 급증.
- **대시보드**: 루프 지연·폴백 비율·2티어 비율·정합성 실패율 1화면.

## 14. CI/CD 파이프라인

기존 Production Readiness 게이트(pytest · compileall · parity `src/lovv_agent` ↔
`app/LovvAgentV1/lovv_agent` · `agentcore validate`/`deploy --dry-run`)를 재사용하고,
**빌더 전용 게이트**를 추가한다.

```text
[push/PR]
 ├─ lint/format
 ├─ unit test
 │    ├─ 무상태 회귀 (checkpointer=None 동작 불변)
 │    ├─ serde round-trip (itinerary_builder state 무손실 — checkpointer SPEC R4)
 │    ├─ geo-filter 단위 (Haversine 반경 정확도)
 │    ├─ soft floor 폴백 사다리 (큐레이션 1곳→API 보충→솔직 안내)
 │    └─ 정합성 게이트 (장소명·날짜·좌표 vs State)
 ├─ parity check (정본 ↔ 배포 사본)
 ├─ (env-gated) 통합 스모크 — interrupt/resume 동일 thread 재개 (AgentCore Memory 테스트 리소스)
 ├─ agentcore validate --json  /  deploy --target v1 --dry-run --json
 └─ 배포 게이트 (실패 시 차단)
```

- **배포**: AgentCore CDK(alpha) **버전 pin**, Memory 설정은 **env-gated**(기본 off).
- **비밀/PII**: 자격증명·PII 페이로드 **커밋 금지**(§7 경계 준수).
- **관측 연동**: 배포 후 §13 메트릭·알람이 자동 등록되도록 IaC(CDK)에 포함.

## 15. 미해결 / 확인 필요

- [ ] 반경 N km 기본값, soft floor 수치(표시 최소 개수) 산정.
- [ ] 교통 API 선택(Kakao/Google/현지) — 구간 동선·이동시간 소스.
- [ ] Profile Lock 재트리거 트리거 정의(어떤 변경이 "근본 변경"인가).
- [ ] 식당·카페: 지도 API only로 충분한지 vs 일부 DB 큐레이션 병행.
- [ ] scoring 반경 모드 가중치 튜닝.
- [ ] `candidate_evidence_runtime_retrieval.md §9`(restaurant 제외) 갱신.
- [ ] 토큰·지연 효과 실측(가이드 추정치 검증).
- [ ] PLAN DETAIL "빌더 모드 + 리뷰 모드" UX 분기 상세.
- [ ] (보류) Output(Presenter) Agent 분리 / sLLM→대형LLM 릴레이 검수 재검토 트리거.
- [ ] (옵션) 다중 반경 교집합(다거점) 확장 설계 — 단일 anchor 코어와의 관계.
- [ ] 코드 정합성 게이트(장소명·날짜·좌표 vs State) 규칙셋 정의.
- [ ] CloudWatch 알람 임계값(p95 지연·정합성 실패율·토큰) 산정.
- [ ] CI 러너에서 AgentCore CLI 가용성 / 통합 스모크용 Memory 테스트 리소스 확보.

## 16. 참고

- checkpointer/HITL 계약: `LOVV_AGENTCORE_MEMORY_CHECKPOINTER_SPEC.md`
- 상태/메모리 결정: ADR — 개인화·에이전트 상태 아키텍처 결정 기록
- 기획: `94_kick.md`, `followup-requery.md`, `plan-detail.md`, `theme-detail.md`
- 팀 가이드(패턴): `멀티-에이전트-멀티-턴-구축-가이드.md`

> 본 문서는 1차 설계(초안)다. 수치·트리거·UX 분기 등 "확인 필요" 항목은 구현 착수 전 확정한다.
