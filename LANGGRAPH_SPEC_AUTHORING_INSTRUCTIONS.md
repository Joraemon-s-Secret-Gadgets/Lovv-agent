# LangGraph SPEC Authoring Instructions

이 문서는 `Lovv-agent`에서 LangGraph 구현 SPEC을 작성하거나 갱신할 때 반드시 먼저 읽어야 하는 지시사항이다.
매번 긴 참고 문서 목록을 다시 입력하지 않기 위해, PRO20x Spec Workflow와 Lovv Agent 정본 문서 참조 규칙을 한곳에 고정한다.

## User Request Original

SPEC 작업을 시작할 때 사용자의 원문 요청을 그대로 보존한다.

```md
User Request Original:
<사용자가 한국어로 작성한 요청을 수정 없이 붙여넣기>
```

원문 요청은 사용자의 의도, 뉘앙스, 성공 기준에서 최종 권위를 가진다.

## Structured Agent Contract

Spec Agent 또는 Main Codex는 실행 안정성을 위해 원문 요청을 다음 영어 contract로 정규화한다.

```md
Structured Agent Contract:
- Display Name:
- Core Role: Spec Agent
- Domain Focus: Lovv LangGraph agent implementation
- Work Focus: Write or update implementation SPEC before detailed implementation
- Execution Mode: Sequential unless the user explicitly selects another mode
- Goal:
- Source of Truth:
- Scope:
- Out of Scope:
- Required Context:
- Output Format:
- Verification:
- Stop Condition:
```

Review Agent가 있다면 `User Request Original`과 `Structured Agent Contract`를 모두 기준으로 결과를 검토한다.

## Primary Operating Rule

`oh_my_agents/PRO20x/AGENTS.md`의 Spec Workflow를 따른다.

Spec 작성 단계에서는 다음을 수행한다.

- 목표와 비목표를 정의한다.
- 사용자 또는 시스템 actor를 식별한다.
- 사용자 흐름과 기대 동작을 작성한다.
- 기능 요구사항과 acceptance criteria를 작성한다.
- 제약, edge case, security, privacy, accessibility 우려를 기록한다.
- 기존 시스템 문맥을 요약한다.
- 선택한 설계 접근을 설명한다.
- 영향받는 파일, 폴더, 모듈, API, 데이터 모델, UI 흐름을 식별한다.
- 오류 처리, 호환성, migration, 테스트 전략을 정의한다.
- feature boundary, dependency, risk, assumption, verification need를 정리한다.
- 사용자 검토가 가능할 정도로 명확하게 작성한다.
- SPEC 단계에서 구현 코드를 작성하지 않는다.

## Required Lovv Agent Reference Documents

LangGraph 구현 SPEC을 작성할 때는 아래 문서를 source of truth로 우선 참조한다.

```text
oh_my_documents/docs/05_agent_spec/05_agent_spec.md
oh_my_documents/docs/05_agent_spec/candidate_evidence_agent.md
oh_my_documents/docs/05_agent_spec/intent_agent.md
oh_my_documents/docs/05_agent_spec/planner_agent.md
oh_my_documents/docs/05_agent_spec/festival_verifier_agent.md
oh_my_documents/docs/05_agent_spec/candidate_evidence_runtime_retrieval.md
oh_my_documents/docs/05_agent_spec/scoring_tool.md
oh_my_documents/docs/05_agent_spec/destination_search_tool.md
```

참조 우선순위는 다음과 같다.

1. `05_agent_spec.md`: 전체 Agent 구조, 책임 경계, canonical 흐름.
2. `intent_agent.md`: API structured input 정본 원칙과 Candidate Evidence 입력 생성 계약.
3. `candidate_evidence_agent.md`: Candidate Evidence Package, 실행 모드, festival seed/fixed-city lookup, failure/status 정책.
4. `candidate_evidence_runtime_retrieval.md`: S3 Vector, DynamoDB, runtime retrieval 계약.
5. `destination_search_tool.md`: 목적지/장소 검색 tool facade, festival seed helper, metadata/rehydration 규칙.
6. `scoring_tool.md`: ranking, scoring factor, audit 기준.
7. `festival_verifier_agent.md`: 최종 선택 도시의 축제 후보 날짜 검증과 Planner handoff 정책.
8. `planner_agent.md`: 일정 생성, slot template, festival overlay, `foodSearch`/placeholder 정책.

보조 참조:

- `oh_my_documents/docs/05_agent_spec/agent_harness_design.md`: AgentCore harness, memory, LangGraph test fixture 경계를 설계할 때 참조한다.

## Context Loading Rule

SPEC 작성 전에 다음 순서로 최소 문맥을 읽는다.

1. `oh_my_agents/PRO20x/AGENTS.md`의 Spec Workflow, User Language Preservation Rule, Agent Invocation Contract.
2. `oh_my_agents/docs/projects/lovv-project-context.md`.
3. 위 `Required Lovv Agent Reference Documents`의 관련 섹션.

모든 문서를 통째로 반복 로드하지 말고, SPEC 작성에 필요한 섹션을 우선 검색해 읽는다.

## SPEC Output Format

SPEC은 다음 섹션을 기본 골격으로 작성한다.

```md
# [Feature or Component] SPEC

## Summary
## Goals
## Non-Goals
## User/System Flow
## Requirements
## Design
## Component Responsibilities
## State and Data Contracts
## Runtime Retrieval and Tool Boundaries
## Error Handling and Fallback
## Acceptance Criteria
## Constraints and Risks
## Task Breakdown
## Verification
```

필요한 경우 `Task Breakdown`은 feature-level Task와 atomic Subtask로 나눈다. 각 Subtask는 목적, 범위, 의존성, target files, acceptance criteria, verification command를 가져야 한다.

## Lovv LangGraph SPEC Boundaries

LangGraph 구현 SPEC에서는 다음 경계를 지킨다.

- Candidate Evidence Package는 Planner 내부 입력이며 외부 API 응답이 아니다.
- Intent Agent는 Candidate Evidence 입력을 만드는 구조화 단계로 정의한다.
- Intent Agent는 API structured input의 `country`, `travelMonth`, `tripType`, canonical `themes`, `destinationId`, `includeFestivals`, `userLocation`을 자연어에서 재추론하지 않는다. 자연어는 soft preference, 제외 조건, unsupported condition, 명시적 변경 요청 신호에만 사용한다.
- Candidate Evidence Agent는 검색, 후보 예산, hard-theme gate, festival seed/fixed-city lookup, fallback status, audit를 소유한다.
- Runtime retrieval은 S3 Vector 검색과 DynamoDB primary-only rehydration 계약을 따른다.
- DestinationSearchTool은 retrieval facade이며, ScoringTool은 순수 scoring/audit 로직을 담당한다.
- `includeFestivals=true`와 `destinationId == null`이면 Candidate Evidence는 장소 검색 전에 `festival.month == travelMonth` AND 사용자 travel theme OR 조건으로 festival city seed를 만든다. seed가 없으면 일반 추천으로 몰래 완화하지 않고 `needs_clarification=true`로 사용자 응답을 기다린다.
- `includeFestivals=true`와 `destinationId != null`이면 Candidate Evidence는 `anchored_place_search`를 유지하고 고정 도시 내부에서만 월·테마 조건 축제를 조회한다. 축제 후보가 없다고 도시를 자동 변경하지 않는다.
- Festival Verifier는 Candidate Evidence가 넘긴 최종 선택 도시의 `selected_festival_candidates`만 검증한다. 별도 축제 선택 mode나 도시 ranking/anchor 확정 책임을 만들지 않는다.
- Planner Agent는 itinerary slot 배정, festival overlay, `foodSearch` link/meal CTA, placeholder와 user notice를 담당한다. 현재 단계에서 restaurant table, restaurant S3 Vector 후보, restaurant scoring을 전제하지 않는다.
- Candidate Evidence의 `needs_clarification=true`는 Planner 입력으로 소비하지 않는다. Supervisor는 질문을 사용자에게 전달하고 `END_WAIT_USER`로 종료한다.
- 모델 ID, provider tier, runtime config는 SPEC에서 고정하지 않는다. 필요한 경우 교체 가능한 adapter 경계로 둔다.
- LLM 출력은 가능한 런타임에서 structured output/tool schema/JSON Schema를 강제한다. 단순히 "JSON으로 반환"만 지시하지 말고, schema validation과 bounded retry/fallback 정책을 SPEC에 포함한다.
- 기존 `langgraph_app/SPEC.md`는 과거 구현 초안으로 취급하고, 사용자가 명시하지 않는 한 정본 source of truth로 삼지 않는다.

## Out Of Scope During SPEC Authoring

- 구현 코드 작성.
- 임의 API endpoint, DB table, persistence 정책 추가.
- 사용자 승인 전 Task/Subtask implementation 착수.
- `oh_my_documents` 정본과 충돌하는 agent 책임 재정의.
- JSON/local fixture 기반 검색을 runtime source로 되살리는 설계.

## Review Checklist

SPEC 초안 완료 후 다음을 확인한다.

- 사용자의 한국어 원문 요청이 보존되었다.
- Structured Agent Contract가 작성되었다.
- Required Lovv Agent Reference Documents가 source of truth로 명시되었다.
- Candidate Evidence, Intent, Planner, Festival Verifier, DestinationSearchTool, ScoringTool의 책임이 섞이지 않는다.
- S3 Vector/DynamoDB runtime retrieval 경계가 유지된다.
- Candidate Evidence Package가 외부 API 응답으로 노출되지 않는다.
- `includeFestivals`는 theme이 아니라 별도 boolean 계약으로 유지된다.
- 축제 포함 city discovery는 월·테마 festival seed가 hard gate이며, seed 실패 시 `END_WAIT_USER` fallback이 유지된다.
- 미식 처리는 restaurant 후보 조회가 아니라 선택 도시 기반 `foodSearch`/CTA/placeholder 정책으로 유지된다.
- Planner가 후보 부족을 환각으로 채우지 않고 placeholder/user notice로 처리한다.
- 구현 Task가 있다면 Spec 승인 이후로 미뤄져 있다.
