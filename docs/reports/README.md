# Lovv-agent · 보고서 인덱스

기준일: 2026-06-25

이 폴더는 분석 보고서, 의사결정 기록, 구현 결과 요약, 외부 전달용 문서를 보관한다.
구현 계약은 [`docs/specs`](../specs/README.md), 실행 계획은
[`docs/tasks`](../tasks/README.md)에 둔다.

## 읽는 순서

발표·리뷰만 필요하면 **00번**, 실행 계획은 **05번**, 구현 결과는 **06번**, 구현 결정/근거는
01~04에서 확인한다. V2 논의는 `V2_*` 보고서를 먼저 읽고 관련 SPEC으로 이동한다.

## AgentCore V1 전환 보고서

| # | 문서 | 용도 | 대상 |
| --- | --- | --- | --- |
| 00 | [Executive Summary](./00_EXECUTIVE_SUMMARY.md) | 한 장 요약 · 권고 · 발표 멘트 | 발표/리뷰 |
| 01 | [성능 병목 & 전환 이득](./01_PERFORMANCE_AND_MIGRATION.md) | 현재 병목, AgentCore 이득, 코드 개선, 측정 | 엔지니어 |
| 02 | [us-east-1 모델 선택](./02_MODEL_SELECTION.md) | structured outputs 제약, 다공급사 모델 후보 | 엔지니어 |
| 03 | [아키텍처 & 대안 검토](./03_ARCHITECTURE_AND_ALTERNATIVES.md) | 멀티에이전트 패턴 추천, 구조 외 대안 | 엔지니어/리드 |
| 04 | [병렬 실행 가능성](./04_PARALLELIZATION.md) | 병렬화 가능/불가 지점, 구현 방식 | 엔지니어 |
| 05 | [전환 계획서](./05_TRANSITION_PLAN.md) | P1 이관 → P2 Gateway 외부화 → P3 자율형, 단계·체크리스트·게이트 | 엔지니어/리드 |
| 06 | [AgentCore V1 FM Routing 구현 결과](./06_AGENTCORE_V1_FM_ROUTING_IMPLEMENTATION_REPORT.md) | issue 등록, per-agent FM routing 구현, 검증 결과 | 엔지니어/리드 |

## 보조 분석과 지시 문서

| 문서 | 용도 | 대상 |
| --- | --- | --- |
| [Candidate Evidence Agent 현재 구현 동작 정리](./CANDIDATE_EVIDENCE_AGENT_RUNTIME_FLOW.md) | Candidate Evidence와 하위 tool의 실제 코드 기준 실행 흐름 | 엔지니어 |
| [data_collect ELT Vector 적재 작업 지시서](./DATA_COLLECT_VECTOR_ELT_INSTRUCTIONS.md) | data_collect 쪽 vector 적재 작업 지시와 검증 관점 | 엔지니어 |
| [LangGraph SPEC Authoring Instructions](./LANGGRAPH_SPEC_AUTHORING_INSTRUCTIONS.md) | LangGraph 구현 SPEC 작성 규칙 | 엔지니어/에이전트 |
| [멀티 에이전트 아키텍처 조사](./MULTI_AGENT_ARCHITECTURE_SURVEY.md) | 대표 멀티 에이전트 패턴과 Lovv Agent 적용 매핑 | 엔지니어/리드 |
| [설계 대비 구현 현황 및 한계](./LOVV_AGENT_IMPLEMENTATION_COMPARISON.md) | 통합 설계 대비 현재 구현 범위, 차이, 후속 보완점 | 엔지니어/리드 |
| [AgentCore 전환 종합 보고서 (Notion용)](./LOVV_AGENTCORE_REPORT_NOTION.md) | Notion 게시용 통합 보고서 | 발표/공유 |

## V2 설계 결정

| 문서 | 용도 | 대상 |
| --- | --- | --- |
| [V2 아키텍처 결정 보고서](./V2_ARCHITECTURE_DECISIONS.md) | V2 방향 전환, 유지/폐기 항목, 미결정 사항 | 엔지니어/리드 |
| [V2 도시 선정 ↔ 일정 생성 분리 의사결정 보고서](./V2_CITY_PLANNER_SEPARATION_DECISIONS.md) | Candidate와 Planner 책임 분리 결정과 코드 근거 | 엔지니어 |
| [V2 Architecture Structure draw.io](./V2_ARCHITECTURE_STRUCTURE.drawio) | V2 구조 다이어그램 원본 | 설계 편집 |
| [V2 Architecture Structure PNG](./V2_ARCHITECTURE_STRUCTURE.png) | V2 구조 다이어그램 이미지 | 발표/공유 |
| [V2 Architecture Structure SVG](./V2_ARCHITECTURE_STRUCTURE.svg) | V2 구조 다이어그램 벡터 이미지 | 문서 삽입 |

## 신뢰도 표기 규칙 (전 문서 공통)

- **[확인됨]**: `src/lovv_agent` 코드 또는 공식 문서에서 직접 확인된 사실.
- **[추정·중]**: AgentCore/Bedrock 동작에 근거한 합리적 추론.
- **[추정·낮음]**: 워크로드/측정 데이터가 없어 가정에 의존.

절대 수치(ms, %)는 워크로드 실측 데이터가 없어 제시하지 않았다. 배포 후 CloudWatch/OTel
측정으로 [추정] 항목을 [확인됨]으로 승격하거나 기각한다(검증 체크리스트: 01번 문서).

## 한 줄 결론

**구조는 바꾸지 말고(Supervisor/Hierarchical · 커스텀 검색 · LangGraph 유지) AgentCore 단일
Runtime에 얹은 뒤, 코드 최적화(테마 검색 병렬화 → DynamoDB 배치 → 리랭커 → 캐싱)로 성능을
얻는다.** AgentCore 자체는 발판(관측·런타임·Memory)이고, 큰 이득은 그 위 코드 변경에서 나온다.
