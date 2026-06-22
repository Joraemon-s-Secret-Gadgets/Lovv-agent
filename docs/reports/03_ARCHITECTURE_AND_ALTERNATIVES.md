# 03 · 멀티에이전트 아키텍처 & 구조 외 대안 검토

기준일: 2026-06-17 · 신뢰도 규칙은 [README](./README.md) 참조.
목적: 멀티에이전트 패턴 선택과, 현재 구조 외 대안(검색계층/프레임워크/캐싱/리랭킹 등)의
채택·비채택 판단을 제시한다.

## 1. 멀티에이전트 아키텍처 추천

AWS가 제시하는 패턴: A2A(에이전트 간 표준 통신), Supervisor + Sub-agent(LLM 동적 라우팅),
직접 boto3 호출, Hierarchical(계층형), Swarm(완전 자율). AWS-native 구현은 Bedrock multi-agent
collaboration(관리형 supervisor) + AgentCore Runtime(개별 에이전트 호스팅).

### 1-1. 결론: 현재의 Supervisor/Hierarchical 패턴을 단일 Runtime에 유지 [추정·중]

Lovv는 이미 `SupervisorRouter` + `fulfilled_matrix` 기반 **Supervisor(오케스트레이터-워커) 패턴**을
코드로 구현·검증했다. 이 워크로드에 맞는 정답 패턴이며 새 아키텍처로 갈아엎을 이유가 없다.
권장은 **이 그래프를 단일 AgentCore Runtime 안에 in-process 호스팅**하는 것(가이드 §15 "처음엔
in-process, 병목 확인된 tool만 외부화"와 일치).

### 1-2. 하지 말 것 [추정·중]

- **에이전트별 분리 호스팅**(각 agent를 별도 Bedrock Agent/AgentCore Runtime): 네트워크 홉·지연·
  비용 증가. 짧게 끝나는 요청 워크로드엔 손해, 아직 불필요.
- **완전 자율 Swarm**: 라우팅을 LLM에 전적 위임 → 비용 예측성·재현성 저하, `/recommendations`
  응답 계약 위협. 가이드의 계약 우선 원칙과 충돌.
- **관리형 Bedrock multi-agent collaboration으로 즉시 이전**: 검증된 fulfilled_matrix·validation·
  response contract 로직을 관리형 LLM 라우팅에 넘기게 되어 통제력·비용예측성 저하. LangGraph
  supervisor 유지가 유리.

### 1-3. 단계적 확장 경로 [가이드 일치]

1. 단일 AgentCore Runtime + LangGraph supervisor(현 패턴) 이관.
2. 관측성으로 병목 tool 식별.
3. 병목으로 확인된 **그 tool만** AgentCore Gateway 타깃(tool-as-service)으로 외부화(가이드 §15
   후보: Scoring, Matrix Transition, Link Builder, Weather Trends).
4. 멀티턴 비중 크면 AgentCore Memory 추가로 turn 간 재사용.
5. 외부 협업/이종 에이전트 연동이 실제 필요할 때만 A2A/관리형 collaboration 검토.

요약: **패턴은 그대로(Supervisor/Hierarchical), 호스팅만 AgentCore 단일 Runtime, 분리는 관측
데이터가 정당화할 때만 tool 단위로.**

## 2. 현재 구조 외 대안 검토

현재 구조(LangGraph supervisor-router + 커스텀 S3 Vectors/DynamoDB 검색 + 단일 Runtime
lift-and-shift) 기준으로 바꿀 가치가 있는 것과 바꾸지 말 것을 구분한다.

### 2-1. 추천: 리랭커(Cohere Rerank 3.5) 단계 추가 [확인됨(가용) + 추정·중(효과)]

us-east-1에서 `cohere.rerank-v3-5:0` 사용 가능(Amazon Rerank 1.0은 us-east-1 미지원). 적용 위치:
`_retrieve_by_theme` → `prune_cities`/`ScoringTool` 사이. 효과:

- 벡터 검색은 **싸게 많이 가져오고**, 리랭커로 상위만 추려 **Planner 입력 토큰 축소**.
- 거리 기반 단순 정렬보다 의미 적합도가 좋아져 **추천 품질 개선** 가능.
- 비용: 검색당 rerank 1회 추가. top-k 축소의 LLM 토큰 절감과 상쇄 여부는 측정 필요.

판단: 커스텀 스코어링을 **대체가 아니라 보강**. 품질/토큰 둘 다 노리면 1순위 후보.

### 2-2. 추천(조건부): 프롬프트 캐싱 [확인됨(지원모델) + 추정·중(가치)]

Bedrock 프롬프트 캐싱(GA, 1시간 TTL)은 반복 고정 컨텍스트 입력 토큰 최대 90%, 지연 최대 85%
절감. Lovv의 3개 system 프롬프트는 고정·반복이라 적합도 높다.

제약: 지원 모델이 **Claude(Sonnet/Haiku/Opus 4.5)와 Nova로 한정**. 현재 `gpt-oss-120b`는 **미지원**.
Nova는 [02 모델 선택]대로 structured outputs 미지원이라 제외. → "Claude(Geo)+캐싱" 조합의 절감이
gpt-oss 대비 순이득인지 비용 비교 후 결정.

### 2-3. 비추천: 관리형 RAG(Knowledge Bases)로 검색계층 이전 [추정·중~높음]

현재 검색계층은 단순 RAG가 아니라 **도메인 로직**: 테마 AND-gate pruning(`prune_cities`), 축제
시드 선검색(`search_festival_city_seeds`), 커스텀 스코어링, DynamoDB 상세 보강. 관리형 KB는 일반
RAG는 쉽게 주지만 이 도메인 규칙 재현이 어렵다. → **검색계층 커스텀 유지**(리랭커 보강만 §2-1).

### 2-4. 비추천: 프레임워크를 Strands/관리형 자율로 교체 [확인됨(특성) + 추정·중(fit)]

Strands Agents SDK는 model-driven(LLM이 스스로 도구·순서 결정)으로 AWS 통합은 좋지만, Lovv는
**엄격한 `/recommendations` 계약 + `fulfilled_matrix` 검증 + 결정적 라우팅**이 핵심이라 LangGraph의
명시적 그래프 제어가 더 맞는다. → **LangGraph 유지.**

단, 프레임워크 무관하게 **AgentCore GA 구성요소는 채택 가치 있음**:
- **AgentCore Policy(Cedar)**: 국가 혼합 금지·미검증 축제 확정 금지 등을 코드 밖 정책으로(가이드 §15 Policy 후보).
- **AgentCore Evaluations**: 모델/top-k 교체 시 품질 회귀 자동 감시([02] 모델 스왑 위험 완화).

### 2-5. 비추천: Step Functions / 에이전트별 Lambda 분산 [추정·중]

라우팅은 이미 LangGraph supervisor가 결정적으로 처리. Step Functions/Lambda 분리는 동일 기능을
중복 구현하며 네트워크 홉·콜드스타트·지연 증가. 테마 검색 병렬화는 **분산이 아니라 in-process
async/스레드**로 충분([04 병렬화]).

### 2-6. 보류: 기타 추론 비용 레버 [확인됨]

- 배치 추론: 대화형 실시간 워크로드라 부적합.
- Provisioned Throughput: 트래픽 증가 + 지연 SLA가 빡빡할 때만.
- Latency-optimized inference: 지원 모델 한정·효과 제한적 → 측정 후 선택.

### 2-7. 대안 검토 요약

| 대안 | 판단 | 이유 | 신뢰도 |
| --- | --- | --- | --- |
| Cohere Rerank 3.5 추가 | **추천(1순위)** | top-k 축소 + 품질, 커스텀 스코어링 보강 | 확인됨/추정·중 |
| 프롬프트 캐싱 | 조건부 추천 | 고정 프롬프트 절감 크나 Claude/Nova 한정 | 확인됨/추정·중 |
| Knowledge Bases 이전 | 비추천 | 도메인 pruning/스코어링 재현 불가 | 추정·중~높음 |
| Strands/관리형 자율 | 비추천 | 계약·검증·결정적 라우팅엔 LangGraph 적합 | 추정·중 |
| Step Functions 분산 | 비추천 | supervisor 중복·지연 증가 | 추정·중 |
| AgentCore Policy/Evaluations | 추천(부가) | 프레임워크 무관, 안전·품질 회귀 관리 | 확인됨/추정·중 |

종합: **구조 자체는 바꾸지 말 것.** 가치 있는 "구조 외" 추가는 (1) 리랭커로 검색→Planner 최적화,
(2) Claude 채택 시 프롬프트 캐싱, (3) AgentCore Policy/Evaluations 정도. 나머지(KB 이전, 프레임워크
교체, 오케스트레이션 분산)는 현 단계에서 비용·리스크가 이득을 넘는다.
