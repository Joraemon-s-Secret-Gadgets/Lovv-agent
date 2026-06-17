# 00 · Executive Summary (발표·리뷰용)

기준일: 2026-06-17 · 상세 근거는 [01~04 보고서](./README.md) 참조.

## 핵심 메시지

현재 Lovv-agent는 단순 순차 실행이 아니라 `SupervisorRouter` + `fulfilled_matrix` 기반으로
**필요한 에이전트만 호출하는 통제된 그래프**다. 방향이 이미 좋으므로 **구조를 갈아엎지 않는다.**
AgentCore Runtime으로 얇게 올리면 콜드스타트·자격증명·관측성·턴 간 재사용에서 이득을 얻고,
**실제 큰 성능 향상은 그 위에서 하는 코드 최적화**(테마 검색 병렬화, DynamoDB 배치, 리랭커,
캐싱)에서 나온다.

## 권고 요약

| 영역 | 권고 | 우선순위 |
| --- | --- | --- |
| 그래프 패턴 | Supervisor/Hierarchical **유지** (단일 AgentCore Runtime in-process) | 유지 |
| 검색 계층 | 커스텀 S3 Vectors/DynamoDB **유지** (도메인 로직) | 유지 |
| 프레임워크 | LangGraph **유지** (Strands/관리형 자율 비추천) | 유지 |
| 테마별 벡터 검색 | 순차 → **병렬(ThreadPool)** | ★ 1 |
| DynamoDB 상세 보강 | 단건 루프 → **BatchGetItem/병렬** | ★ 2 |
| 검색→Planner 품질/토큰 | **Cohere Rerank 3.5** 단계 추가 | ★ 3 |
| LLM 모델 | us-east-1 · structured outputs 지원 모델로 구성 (현재 gpt-oss 유지 가능) | 측정 후 |
| 프롬프트 캐싱 | Claude 채택 시에만 (gpt-oss 미지원) | 조건부 |
| 안전·품질 | AgentCore Policy(Cedar) · Evaluations 채택 | 부가 |

## 비추천 (하지 말 것)

- 에이전트별 분리 호스팅 / 완전 자율 Swarm / 관리형 multi-agent 즉시 이전 → 통제력·비용예측성 저하.
- Knowledge Bases로 검색계층 이전 → 도메인 pruning·스코어링 재현 불가.
- Step Functions/Lambda로 오케스트레이션 분산 → supervisor 중복·지연 증가.

## 모델 구성 핵심 (us-east-1)

- 임베딩 `amazon.titan-embed-text-v2:0` **유지** (us-east-1 In-Region).
- 코드가 **native structured outputs**에 의존 → **Nova 계열 불가**(미지원), 후보는 gpt-oss /
  Qwen3 / DeepSeek / Mistral / Claude 4.5-tier.
- us-east-1에서 최신 Claude는 **`us.` 크로스리전 프로필**로만 호출(직접 ID 실패).
- **Context window는 제약 아님**(후보 모두 ≥128K, Lovv 입력은 그보다 훨씬 작음). **Rate
  limit(RPM/TPM)이 실제 제약** → 노드별 **모델 티어링으로 쿼터 버킷 분산** + 리랭커로 Planner
  토큰 축소. Planner는 DeepSeek-V3.2(164K) 또는 Claude Sonnet 4.6(Geo, 200K) 권장. (상세: [02])

## 권장 적용 순서 (로드맵)

1. 가이드대로 얇게 이관 + 관측성 확보.
2. 관측으로 병목 측정(테마 검색이 1위인지 확인).
3. **테마 검색 병렬화 → DynamoDB 배치** (가장 큰 단일 요청 지연 단축).
4. 리랭커로 top-k 축소(품질·토큰).
5. 멀티턴 많으면 AgentCore Memory + Planner patch 모드.
6. 병목 확인된 tool만 Gateway 외부화.

## 발표 멘트 (예시)

> 현재 구조는 단순 순차 실행이 아니라 `fulfilled_matrix`와 `RoutingState` 기반으로 Supervisor가
> 필요한 에이전트만 호출하는 통제된 그래프입니다. AgentCore로 올리면 런타임·관측·Memory라는
> 발판을 얻고, 실제 성능은 그 위에서 테마별 벡터 검색을 병렬화하고 DynamoDB를 배치 조회하며
> 리랭커로 후보를 정제해 확보합니다. 완전 자율 에이전트로 풀지 않고 통제된 자율형을 유지하므로
> `/recommendations` 응답 계약을 안정적으로 지키면서 비용·성능을 함께 잡을 수 있습니다.

> 신뢰도: 권고의 근거 다수는 코드/공식 문서로 [확인됨], 성능 효과 크기는 측정 전이라 [추정]이다.
> 절대 수치는 배포 후 측정으로 확정한다.
