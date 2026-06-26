# Agent 멀티 에이전트 아키텍처 조사

> 멀티 에이전트 아키텍처의 대표 패턴을 정리하고, 각 패턴이 Lovv Agent 구현에 어떻게 대응되는지 매핑한 문서입니다.
> 작성일: 2026-06-17 · 패턴 출처: LangGraph / LangChain 공식 문서 및 업계 가이드 (하단 참고자료)

## 1. 멀티 에이전트 아키텍처 패턴

- **Single Agent (ReAct) — 기준선**
    - 정의: 하나의 LLM이 reasoning과 tool 호출을 반복(ReAct loop)하며 스스로 다음 행동을 결정.
    - 장점: 단순, 빠른 구축, 디버깅 쉬움.
    - 단점: tool이 ~10개를 넘거나 다영역 작업이 섞이면 라우팅·신뢰성 저하.
    - 적합: 단일 도메인의 단순 작업.

- **Network (네트워크 / 메시)**
    - 정의: 모든 에이전트가 다른 모든 에이전트를 직접 호출할 수 있는 many-to-many 구조.
    - 장점: 유연성 최대, 자유로운 협업.
    - 단점: 제어 흐름이 불명확해 "anarchy(무질서)"가 되기 쉬움 — 대규모에서는 비권장.
    - 적합: 소규모·실험적 협업, 책임 경계가 느슨해도 되는 경우.

- **Supervisor (수퍼바이저)**
    - 정의: 중앙 오케스트레이터 1개가 들어온 작업을 분석해 어떤 worker 에이전트를 호출할지 라우팅. "다른 에이전트를 tool로 갖는 에이전트".
    - 장점: 제어 흐름 명확, 책임 분리, 예측 가능한 라우팅. 출력이 불완전하면 재호출 가능.
    - 단점: 수퍼바이저가 병목·단일 장애점이 될 수 있음.
    - 적합: 전문화된 worker 여러 개 + 단일 종료 조건이 필요한 경우(가장 보편적 프로덕션 선택).

- **Hierarchical (계층형)**
    - 정의: 수퍼바이저가 또 다른 수퍼바이저들을 관리하는 다층 구조. 하위 에이전트를 "팀" 단위로 묶음.
    - 장점: 대규모 엔터프라이즈 확장에 유리, 도메인별 클러스터 분리.
    - 단점: 소규모에는 과설계(overengineering), 지연·복잡도 증가.
    - 적합: 도메인이 여러 개(고객지원·세일즈·IT 등)인 대형 시스템.

- **Swarm (스웜)**
    - 정의: 중앙 라우터 없이 에이전트 간 직접 handoff로 제어권을 넘김. 현재 작업에 맞는 에이전트가 주도.
    - 장점: 동적 전환, 중앙 병목 없음.
    - 단점: 흐름 추적·디버깅 난이도, 실무에서 계층형 대비 성능 우위가 드묾.
    - 적합: 작업이 자연스럽게 전문가 간 이양되는 대화형 시나리오.

- **Pipeline / Sequential (파이프라인)**
    - 정의: 에이전트를 고정된 순서로 직렬 실행. 각 단계의 출력이 다음 단계 입력이 됨.
    - 장점: 결정론적(deterministic), 재현·검증 쉬움, LLM이 흐름을 임의 변경 못 함.
    - 단점: 분기·동적 라우팅에 약함.
    - 적합: 단계와 책임이 명확히 정해진 데이터 기반 워크플로우.

- **Reflection / Validation Loop (검증·재시도)**
    - 정의: 산출물을 검증하는 단계를 두고, 실패 시 제한 횟수 내에서 생성 단계를 재실행하는 보조 패턴.
    - 장점: 품질·근거(grounding) 보장, 환각 억제.
    - 단점: 비용·지연 증가, 종료 조건 설계 필요.
    - 적합: 정확성과 근거가 중요한 작업(일정·사실 검증 등).

## 2. Lovv Agent 적용 매핑

- **Lovv Agent의 정체성: Supervisor + Pipeline 하이브리드**
    - LangGraph `StateGraph` 기반으로 중앙 Supervisor Router가 라우팅하되, worker의 tool 호출 순서는 Python 코드가 고정.
    - 즉 **LLM 자율 tool-calling(ReAct형)이 아니라** deterministic 파이프라인 + 결정론적 Supervisor 조합.

- **Supervisor 패턴 → 적용됨 (핵심)**
    - `Supervisor Router`가 `fulfilled_matrix`와 status 기반으로 다음 worker를 결정.
    - 단, 라우팅이 LLM이 아닌 deterministic state transition → "결정론적 Supervisor".

- **Pipeline / Sequential → 적용됨 (핵심)**
    - 실제 경로: Intent → Supervisor → Candidate Evidence → Supervisor → Festival Verifier → Supervisor → Planner → Supervisor → Response Packager.
    - 각 worker는 실행 후 항상 Supervisor로 복귀.

- **Reflection / Validation Loop → 부분 적용됨**
    - Planner validation 실패 시 최대 2회까지 Planner 재실행.
    - 장소·축제 grounding 및 식당명 생성 금지 검사 포함(단, semantic validation은 제한적).

- **Hierarchical → 미적용**
    - 단일 Supervisor만 존재. 수퍼바이저의 수퍼바이저 구조 없음.

- **Swarm → 미적용**
    - 에이전트 간 직접 handoff 없음. 모든 전환은 Supervisor 경유.

- **Network → 미적용(의도적 배제)**
    - 무질서 방지를 위해 worker 간 직접 호출을 허용하지 않음.

## 3. Lovv Agent 실제 구조 요약 (6개 노드)

- **Intent Agent (🧭)** — API structured input 검증 + 긴 자연어에서 Bedrock structured output으로 보조 신호 추출.
- **Supervisor Router (⚙️)** — fulfilled_matrix·status 기반 결정론적 라우팅, 명료화 필요 시 END_WAIT_USER로 분기.
- **Candidate Evidence Agent (🔍)** — 축제 seed, Bedrock embedding + S3 Vector 관광지 검색, 도시 grouping/scoring, primary/reserve 후보 및 근거(claim) 생성.
- **Festival Verifier Agent (🎪)** — includeFestivals=true일 때 선택 도시 축제의 연·월 적용 가능성 검증(현재 DynamoDB 날짜 기반, 외부 공식 페이지 검증은 미구현).
- **Planner Agent (📅)** — 일정 배치, 축제 overlay, DynamoDB 상세 보강, 사용자용 설명/근거 생성(현재 단순 slot template 기반).
- **Response Packager (📦)** — 내부 Candidate Evidence·audit을 숨기고 `/recommendations` 응답 형태로 deterministic 변환.

- **흐름 요약**
    - START → Intent → Supervisor →(evidence) Candidate Evidence → Supervisor →(festival, includeFestivals=true) Festival Verifier 또는 →(N/A) Planner → Supervisor →(planning) Planner →(validation retry ≤2) Planner → Supervisor →(all done) Response Packager → END.
    - needs_clarification 시 END_WAIT_USER → Response Packager.

## 참고자료

- LangChain Blog — LangGraph Multi-Agent Workflows (network / supervisor / hierarchical)
- LangGraph Multi-Agent Supervisor 공식 문서 (reference.langchain.com)
- Augment Code — Swarm vs. Supervisor: Multi-Agent Architecture Guide
- Lovv Agent 저장소 — `README.md`, `docs/reports/LOVV_AGENT_IMPLEMENTATION_COMPARISON.md`, `lovv_agent_graph.mermaid`
