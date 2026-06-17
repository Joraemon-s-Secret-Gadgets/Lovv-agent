# Lovv-agent · AgentCore 전환 보고서 모음

기준일: 2026-06-17
분석 대상: `src/lovv_agent` 현재 코드 + 업로드된 `AGENTCORE_MIGRATION_GUIDE.md`
작성 목적: (1) 엔지니어/리드용 **기술 의사결정 문서**, (2) **발표·리뷰용 요약**.

## 읽는 순서

| # | 문서 | 용도 | 대상 |
| --- | --- | --- | --- |
| 00 | [Executive Summary](./00_EXECUTIVE_SUMMARY.md) | 한 장 요약 · 권고 · 발표 멘트 | 발표/리뷰 |
| 01 | [성능 병목 & 전환 이득](./01_PERFORMANCE_AND_MIGRATION.md) | 현재 병목, AgentCore 이득, 코드 개선, 측정 | 엔지니어 |
| 02 | [us-east-1 모델 선택](./02_MODEL_SELECTION.md) | structured outputs 제약, 다공급사 모델 후보 | 엔지니어 |
| 03 | [아키텍처 & 대안 검토](./03_ARCHITECTURE_AND_ALTERNATIVES.md) | 멀티에이전트 패턴 추천, 구조 외 대안 | 엔지니어/리드 |
| 04 | [병렬 실행 가능성](./04_PARALLELIZATION.md) | 병렬화 가능/불가 지점, 구현 방식 | 엔지니어 |
| 05 | [전환 계획서](./05_TRANSITION_PLAN.md) | P1 이관 → P2 Gateway 외부화 → P3 자율형, 단계·체크리스트·게이트 | 엔지니어/리드 |

발표·리뷰만 필요하면 **00번**, 실행 계획은 **05번**, 구현 결정/근거는 01~04에서 확인한다.

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
