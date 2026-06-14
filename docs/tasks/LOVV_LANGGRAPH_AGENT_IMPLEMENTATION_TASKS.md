# Lovv LangGraph Agent Implementation Tasks

> Status: Draft for implementation planning  
> Date: 2026-06-14  
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`  
> Scope: `Lovv-agent` implementation tasks only

## User Request Original

```text
이제 [LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md](Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md) 로부터 subtask들을 뽑아내서 docs/tasks/에 정리하세요.
```

## Structured Agent Contract

- Display Name: Lovv LangGraph Task Agent
- Core Role: Task Agent
- Domain Focus: Lovv LangGraph agent implementation
- Work Focus: Convert the approved implementation SPEC into ordered implementation-ready Tasks and Subtasks
- Execution Mode: Sequential
- Goal: Produce a task packet that implementation agents can execute one Subtask at a time
- Source of Truth: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Scope: Documentation under `Lovv-agent/docs/tasks`
- Out of Scope: Implementation code, public API redesign, DB schema changes, model ID selection
- Output Format: Markdown task document with Task/Subtask context packets
- Verification: Task dependencies, target files, acceptance criteria, and verification commands are present
- Stop Condition: Task document is ready for user review and implementation approval

## Source Of Truth

Full Spec:

- `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

Primary reference documents to read only when the Subtask requires them:

- `oh_my_documents/docs/05_agent_spec/05_agent_spec.md`
- `oh_my_documents/docs/05_agent_spec/candidate_evidence_agent.md`
- `oh_my_documents/docs/05_agent_spec/intent_agent.md`
- `oh_my_documents/docs/05_agent_spec/planner_agent.md`
- `oh_my_documents/docs/05_agent_spec/festival_verifier_agent.md`
- `oh_my_documents/docs/05_agent_spec/candidate_evidence_runtime_retrieval.md`
- `oh_my_documents/docs/05_agent_spec/scoring_tool.md`
- `oh_my_documents/docs/05_agent_spec/destination_search_tool.md`
- `oh_my_documents/docs/05_agent_spec/agent_harness_design.md`
- `oh_my_documents/docs/07_api_spec/mvp_confirmed_api_contract.md`

## Execution Rules

- Implement one Subtask at a time.
- Before implementation, read the current Subtask packet first.
- Read only the Full Spec sections listed in `Must Read Before Implementation`.
- Do not implement a later Task until dependencies are complete and reviewed.
- Do not create public API endpoints, DB tables, persistence policies, or fixed model IDs unless a later approved Spec explicitly adds them.
- If a Subtask conflicts with the Full Spec or canonical reference documents, stop and ask the user before editing code.
- If tests fail three consecutive times for the same root cause, stop and escalate instead of repeatedly retrying.
- Use `uv` as the canonical Python project and verification runner.
- Pin the project to Python 3.12; do not widen runtime support without a separate decision.
- Use `pyproject.toml` as the single source of truth for Python dependencies and package metadata.
- Run Python and tests from the `Lovv-agent` root with `uv run ...`; do not rely on global Python packages as the normal workflow.
- Run `uv sync` after dependency changes and update `uv.lock` with the dependency change.

## Task Order

| Order | Task | Depends On |
| --- | --- | --- |
| 1 | Project Skeleton and Schemas | Spec approval |
| 2 | Intent Agent and Structured Output Adapter | Task 1 |
| 3 | Supervisor Router | Task 1 |
| 4 | DestinationSearchTool, DynamoLookupTool, and AWS Retrieval Adapters | Task 1 |
| 5 | ScoringTool and Candidate Selection | Task 4 |
| 6 | Candidate Evidence Agent | Tasks 2, 4, 5 |
| 7 | Festival Verifier Agent | Task 6 |
| 8 | Planner Agent and Validation | Tasks 6, 7 |
| 9 | Response Packaging and Graph Integration | Tasks 1-8 |
| 10 | AWS/LLM Integration and AgentCore-Ready Harness Boundary | Task 9 |

---

## Task 1. Project Skeleton and Schemas

- Purpose: node 구현 전에 import 가능한 Python package와 공유 contract를 만든다.
- Scope: package skeleton, config schema, state schema, enum/status type, schema test skeleton.
- Dependencies: Full Spec approval.
- Context Budget: SPEC의 `Design`, `State and Data Contracts`, `Acceptance Criteria`만 우선 읽는다.
- Acceptance Criteria: package import, uv project metadata, core schema validation, no AWS/LLM call.
- Verification: `uv run` import smoke test, schema unit tests.

### Subtask 1.1: Python Package Skeleton

- Purpose: 이후 모든 agent/tool 구현이 들어갈 최소 패키지 구조를 만든다.
- Required Context:
  - Full Spec의 proposed package shape.
- Context Budget:
  - Must read: Full Spec `## Design`, `### Proposed Package Shape`, `## Task Breakdown`.
  - Do not read: 전체 `oh_my_documents`, 기존 `langgraph_app` 코드.
  - Optional read: `Lovv-agent/README.md`.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `## Design`
  - `### Proposed Package Shape`
  - `## Non-Goals`
- Must Read Before Implementation:
  - `### Proposed Package Shape`
  - `## Non-Goals`
- Target Files:
  - `.gitignore`
  - `.python-version`
  - `pyproject.toml`
  - `uv.lock`
  - `src/lovv_agent/__init__.py`
  - `src/lovv_agent/graph.py`
  - `src/lovv_agent/state.py`
  - `src/lovv_agent/config.py`
  - `src/lovv_agent/models/schemas.py`
  - `src/lovv_agent/agents/`
  - `src/lovv_agent/tools/`
  - `src/lovv_agent/adapters/`
  - `src/lovv_agent/repositories/`
  - `tests/`
- Out of Scope:
  - Agent logic.
  - AWS client calls.
  - LLM calls.
  - LangGraph compile logic beyond placeholder imports.
- Acceptance Criteria:
  - `lovv_agent` package imports without runtime side effects.
  - Empty module layout matches the Spec responsibility boundaries.
  - No network, AWS, or model client is initialized at import time.
  - Python runtime is pinned to 3.12 in `.python-version` and `pyproject.toml`.
  - `pyproject.toml` defines the package metadata and dev test dependency boundary.
- Verification:
  - `uv run python -c "import lovv_agent; print(lovv_agent.__version__)"`

### Subtask 1.2: Config and Runtime Settings Schema

- Purpose: AWS, model adapter, search budget, retry/timeout 설정을 코드에 하드코딩하지 않도록 config boundary를 만든다.
- Required Context:
  - Full Spec의 runtime config 목록과 non-goals.
- Context Budget:
  - Must read: Full Spec `### AWS Runtime Boundary`, `### Search Budgets`, `## Non-Goals`.
  - Do not read: AWS deployment docs unless implementation needs live smoke tests.
  - Optional read: `oh_my_documents/docs/05_agent_spec/candidate_evidence_runtime_retrieval.md`.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### AWS Runtime Boundary`
  - `### Search Budgets`
  - `## Non-Goals`
- Must Read Before Implementation:
  - `### AWS Runtime Boundary`
  - `### Search Budgets`
- Target Files:
  - `src/lovv_agent/config.py`
  - `tests/test_config.py`
- Out of Scope:
  - Real credential loading.
  - Concrete model ID selection.
  - AgentCore deployment config.
- Acceptance Criteria:
  - Runtime config includes AWS region, vector resource names, DynamoDB table name, embedding adapter identifier, top K budgets, verifier candidate K, retries, and timeouts.
  - Runtime config includes the Intent natural-language minimum character threshold, default `5`.
  - Defaults are safe for local tests and do not require real AWS credentials.
  - Config can be injected into tools/nodes.
- Verification:
  - `uv run pytest tests/test_config.py`

### Subtask 1.3: Core Data Schemas

- Purpose: graph state and node handoff payload을 schema로 고정해 downstream 오염을 막는다.
- Required Context:
  - Full Spec의 `UnifiedAgentState`, Candidate Evidence input/package, Candidate Evidence `candidate_reason_claims`, Festival Verification output, Planner output, Planner `explanation_audit`.
- Context Budget:
  - Must read: Full Spec `## State and Data Contracts`, `## Error Handling and Fallback`.
  - Do not read: full Planner or Candidate Evidence canonical docs unless schema ambiguity appears.
  - Optional read: relevant canonical agent detail docs for field semantics.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### UnifiedAgentState`
  - `### Candidate Evidence Input`
  - `### Candidate Evidence Package`
  - `### Festival Verification Output`
  - `### Planner Output`
- Must Read Before Implementation:
  - `## State and Data Contracts`
  - `## Error Handling and Fallback`
- Target Files:
  - `src/lovv_agent/state.py`
  - `src/lovv_agent/models/schemas.py`
  - `tests/test_schemas.py`
- Out of Scope:
  - Planner generation.
  - Retrieval/scoring algorithms.
- Acceptance Criteria:
  - State schema contains request, conversation, trace, intent, routing, evidence, festival, planning, and serving groups.
  - Candidate Evidence statuses are limited to `ok`, `insufficient_candidates`, `no_candidate`, `error`.
  - `needs_clarification` and `clarifying_question` are valid across worker outputs.
  - Candidate Evidence `candidate_reason_claims` validates evidence-referenced Korean claim candidates without finalizing public explanation text.
  - Planner `explanation_audit` validates internal evidence refs for generated recommendation reasons.
  - Sample payloads validate.
- Verification:
  - `uv run pytest tests/test_schemas.py`

---

## Task 2. Intent Agent and Structured Output Adapter

- Purpose: `/recommendations` structured input을 Candidate Evidence input으로 안정적으로 정규화한다.
- Scope: Intent node, theme mapping, raw/soft query extraction, unsupported condition extraction, schema-enforced LLM adapter.
- Dependencies: Task 1.
- Context Budget: Intent 관련 SPEC 섹션과 `intent_agent.md`만 우선 읽는다.
- Acceptance Criteria: API core field 보존, short natural-language LLM skip, `includeFestivals` 분리, schema validation, bounded retry.
- Verification: Intent unit tests.

### Subtask 2.1: API Input Normalization and Theme Mapping

- Purpose: API structured input을 자연어보다 우선하는 정본 입력으로 변환한다.
- Required Context:
  - API request field contract and Intent Agent field rules.
- Context Budget:
  - Must read: Full Spec `### R1. Intent Agent`, `### Candidate Evidence Input`; `mvp_confirmed_api_contract.md` recommendation request section.
  - Do not read: full API docs outside `/recommendations`.
  - Optional read: `oh_my_documents/docs/05_agent_spec/intent_agent.md` sections on API structured input and theme mapping.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
  - API Contract: `oh_my_documents/docs/07_api_spec/mvp_confirmed_api_contract.md`
- Required Sections:
  - Full Spec `### R1. Intent Agent`
  - Full Spec `### Candidate Evidence Input`
- Must Read Before Implementation:
  - `### R1. Intent Agent`
  - `### Candidate Evidence Input`
- Target Files:
  - `src/lovv_agent/agents/intent.py`
  - `src/lovv_agent/models/schemas.py`
  - `tests/test_intent.py`
- Out of Scope:
  - LLM prompt generation.
  - Retrieval.
  - City recommendation.
- Acceptance Criteria:
  - `country`, `travelMonth`, `tripType`, canonical `themes`, `destinationId`, `includeFestivals`, and `userLocation` are not inferred from natural language.
  - `userLocation` is normalized to internal `user_location`.
  - Canonical theme IDs map to Candidate Evidence labels.
  - Festival inclusion is controlled by `includeFestivals`, not by theme labels.
- Verification:
  - `uv run pytest tests/test_intent.py -k "normalization or theme_mapping"`

### Subtask 2.2: Raw/Soft Query and Unsupported Condition Extraction

- Purpose: 자연어에서 검색 가능한 문장, 분위기 선호, 지원 불가 조건만 추출하되, 짧은 입력은 보수적으로 무시한다.
- Required Context:
  - Intent Agent scope and natural-language boundary.
- Context Budget:
  - Must read: Full Spec `### R1. Intent Agent`, `## Error Handling and Fallback`.
  - Do not read: Candidate Evidence retrieval internals.
  - Optional read: `oh_my_documents/docs/05_agent_spec/intent_agent.md` prompt template.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R1. Intent Agent`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `### R1. Intent Agent`
- Target Files:
  - `src/lovv_agent/agents/intent.py`
  - `tests/test_intent.py`
- Out of Scope:
  - City/place scoring.
  - Planner notices.
- Acceptance Criteria:
  - `cleaned_raw_query` preserves searchable travel intent.
  - `soft_preference_query` captures atmosphere/preference terms.
  - Unsupported live or unavailable conditions are separated into `unsupported_conditions`.
  - Empty or shorter-than-threshold natural language, default fewer than `5` trimmed characters, skips LLM extraction.
  - Short natural language sets `cleaned_raw_query=""`, `soft_preference_query=""`, and `unsupported_conditions=[]`, then proceeds from structured API input.
  - Natural-language conflicts with structured core fields create clarification or handoff notes, not silent overrides.
- Verification:
  - `uv run pytest tests/test_intent.py -k "raw_soft or unsupported or conflict"`

### Subtask 2.3: Structured Output Adapter and Fallback

- Purpose: LLM output이 schema 밖으로 새지 않도록 structured output과 local validation을 강제한다.
- Required Context:
  - Full Spec model adapter boundary and Intent structured output requirement.
- Context Budget:
  - Must read: Full Spec `### Model Adapter Boundary`, `### R1. Intent Agent`, `## Error Handling and Fallback`.
  - Do not read: provider-specific docs unless adapter API is unclear.
  - Optional read: `oh_my_documents/docs/05_agent_spec/intent_agent.md` structured output section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### Model Adapter Boundary`
  - `### R1. Intent Agent`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `### Model Adapter Boundary`
  - `## Error Handling and Fallback`
- Target Files:
  - `src/lovv_agent/adapters/bedrock_converse.py`
  - `src/lovv_agent/agents/intent.py`
  - `tests/test_intent.py`
- Out of Scope:
  - Concrete model ID selection.
  - Production Bedrock credentials.
- Acceptance Criteria:
  - Adapter supports schema/tool-output style structured output.
  - Malformed output is retried within a bounded limit.
  - Final parse failure returns safe clarification/fallback instead of malformed state.
- Verification:
  - `uv run pytest tests/test_intent.py -k "structured_output or schema_failure"`

---

## Task 3. Supervisor Router

- Purpose: graph routing, matrix transition, clarification stop behavior를 결정적으로 구현한다.
- Scope: Supervisor node, matrix helper, retry limit, `END_WAIT_USER` route, future Supervisor implementation swap boundary.
- Dependencies: Task 1.
- Context Budget: Supervisor and fallback sections only.
- Acceptance Criteria: matrix keys/status, routing order, verifier skip, Planner blocking on clarification, deterministic Supervisor as default.
- Verification: Supervisor unit tests.

Default Task 3 routing is deterministic and is the MVP source of truth. The implementation should still expose a clean routing boundary so a later LLM Supervisor can be swapped in for the same E2E fixture suite after the deterministic baseline passes; live LLM routing is not part of Task 3 baseline acceptance.

### Subtask 3.1: Fulfilled Matrix and Transition Helper

- Purpose: `evidence`, `festival`, `planning` 상태 전이를 재사용 가능한 helper로 만든다.
- Required Context:
  - Full Spec Supervisor routing requirements.
- Context Budget:
  - Must read: Full Spec `### R2. Supervisor Router`, `### UnifiedAgentState`.
  - Do not read: individual agent implementation docs.
  - Optional read: `oh_my_documents/docs/05_agent_spec/05_agent_spec.md` fulfilled matrix section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R2. Supervisor Router`
  - `### UnifiedAgentState`
- Must Read Before Implementation:
  - `### R2. Supervisor Router`
- Target Files:
  - `src/lovv_agent/agents/supervisor.py`
  - `src/lovv_agent/state.py`
  - `tests/test_supervisor.py`
- Out of Scope:
  - LangGraph compile.
  - Agent business logic.
- Acceptance Criteria:
  - Matrix keys are fixed to `evidence`, `festival`, `planning`.
  - Values are limited to `X`, `O`, `△`, `N/A`.
  - Invalid matrix values fail validation.
- Verification:
  - `uv run pytest tests/test_supervisor.py -k "matrix"`

### Subtask 3.2: Routing Decisions and Clarification Stop

- Purpose: worker status에 따라 다음 node 또는 사용자 대기를 선택한다.
- Required Context:
  - Graph sequence and clarification fallback.
- Context Budget:
  - Must read: Full Spec `### Graph Shape`, `### Clarification Fallback`, `## Error Handling and Fallback`.
  - Do not read: retrieval/scoring internals.
  - Optional read: `oh_my_documents/docs/05_agent_spec/05_agent_spec.md` transition table.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### Graph Shape`
  - `### Clarification Fallback`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `### Clarification Fallback`
  - `## Error Handling and Fallback`
- Target Files:
  - `src/lovv_agent/agents/supervisor.py`
  - `src/lovv_agent/graph.py`
  - `tests/test_supervisor.py`
- Out of Scope:
  - Backend response formatting.
  - Actual node execution.
  - Live LLM Supervisor routing.
- Acceptance Criteria:
  - Deterministic routing logic is exposed through a clear function/class boundary that graph wiring can replace later.
  - Deterministic routing remains the source of truth for Task 3 and MVP execution.
  - `needs_clarification=true` routes to user wait and blocks Festival Verifier/Planner.
  - `includeFestivals=false` marks festival as `N/A`.
  - `status=insufficient_candidates` can proceed to Planner only when package is safe.
  - Routing order is evidence, festival, planning.
- Verification:
  - `uv run pytest tests/test_supervisor.py -k "routing or clarification"`

### Subtask 3.3: Retry Limit Enforcement

- Purpose: Planner validation retry가 무한 루프가 되지 않게 한다.
- Required Context:
  - Full Spec retry and Planner validation behavior.
- Context Budget:
  - Must read: Full Spec `### R2. Supervisor Router`, `### R9. Planner Agent`, `## Error Handling and Fallback`.
  - Do not read: full Planner prompt implementation.
  - Optional read: none.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R2. Supervisor Router`
  - `### R9. Planner Agent`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `### R2. Supervisor Router`
  - `## Error Handling and Fallback`
- Target Files:
  - `src/lovv_agent/agents/supervisor.py`
  - `tests/test_supervisor.py`
- Out of Scope:
  - Planner rewrite logic.
- Acceptance Criteria:
  - `validation_retry_count <= 2` is enforced.
  - Retry exhaustion routes to safe fallback state.
  - Retry count is visible in trace/debug state but not user-facing response by default.
- Verification:
  - `uv run pytest tests/test_supervisor.py -k "retry"`

---

## Task 4. DestinationSearchTool, DynamoLookupTool, and AWS Retrieval Adapters

- Purpose: `DestinationSearchTool`은 S3 Vector attraction search로 한정하고, `DynamoLookupTool`은 DynamoDB festival seed lookup과 final placed item detail enrichment를 전담하게 만든다.
- Scope: AWS client adapters, repository interfaces, filter construction, warning handling.
- Dependencies: Task 1.
- Context Budget: DestinationSearchTool, DynamoLookupTool, and runtime retrieval specs only.
- Acceptance Criteria: attraction-only place search, festival seed/fixed-city lookup, no restaurant/festival general search, final item detail enrichment, and no DynamoDB reads inside `DestinationSearchTool`.
- Verification: mocked AWS unit tests.

### Subtask 4.1: AWS Client and Repository Interfaces

- Purpose: tool logic과 boto3/runtime client를 분리해 테스트 가능하게 만든다.
- Required Context:
  - Full Spec AWS runtime boundary.
- Context Budget:
  - Must read: Full Spec `### AWS Runtime Boundary`, `### R5. DestinationSearchTool`, `### R5b. DynamoLookupTool`.
  - Do not read: deployment docs or credentials.
  - Optional read: `oh_my_documents/docs/05_agent_spec/candidate_evidence_runtime_retrieval.md`.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### AWS Runtime Boundary`
  - `### R5. DestinationSearchTool`
  - `### R5b. DynamoLookupTool`
- Must Read Before Implementation:
  - `### AWS Runtime Boundary`
- Target Files:
  - `src/lovv_agent/adapters/aws_clients.py`
  - `src/lovv_agent/repositories/s3_vectors.py`
  - `src/lovv_agent/repositories/dynamodb.py`
  - `tests/test_destination_search.py`
- Out of Scope:
  - Live AWS smoke test.
  - IAM or deployment configuration.
- Acceptance Criteria:
  - Repository interfaces can be mocked without AWS credentials.
  - Runtime clients are injected rather than imported as global singletons.
  - No network call occurs during unit tests.
- Verification:
  - `uv run pytest tests/test_destination_search.py -k "repository or client"`

### Subtask 4.2: Attraction Search Filter and Candidate Normalization

- Purpose: S3 Vector 검색 payload와 attraction candidate 정규화를 구현한다.
- Required Context:
  - DestinationSearchTool place search contract.
- Context Budget:
  - Must read: Full Spec `### R5. DestinationSearchTool`, `### S3 Vector Metadata Contract`, `### Search Budgets`.
  - Do not read: Planner docs.
  - Optional read: `oh_my_documents/docs/05_agent_spec/destination_search_tool.md`.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R5. DestinationSearchTool`
  - `### S3 Vector Metadata Contract`
  - `### Search Budgets`
- Must Read Before Implementation:
  - `### R5. DestinationSearchTool`
  - `### S3 Vector Metadata Contract`
- Target Files:
  - `src/lovv_agent/tools/destination_search.py`
  - `src/lovv_agent/repositories/s3_vectors.py`
  - `tests/test_destination_search.py`
- Out of Scope:
  - City scoring.
  - Festival or restaurant entity search in general place retrieval.
- Acceptance Criteria:
  - `search_candidates` builds attraction-only filters.
  - Optional `city_id` and single active `theme` filter are combined correctly.
  - `미식·노포` and festival labels do not trigger S3 Vector place search.
  - `prune_cities` applies allowed city restriction and searchable theme AND gate.
  - Chunk keys normalize to stable `place_id`.
  - `top_k` is read from injected config/call argument, not fixed as a universal constant.
- Verification:
  - `uv run pytest tests/test_destination_search.py -k "search_candidates or filter or normalize"`

### Subtask 4.3: DynamoLookupTool Festival Seed and Fixed-City Lookup Helper

- Purpose: `includeFestivals=true`에서 장소 검색 전에 월·테마 축제 후보를 찾는 helper를 구현한다.
- Required Context:
  - Festival Candidate Channel and DynamoLookupTool festival helper.
- Context Budget:
  - Must read: Full Spec `### R4. Festival Candidate Channel`, `### R5b. DynamoLookupTool`.
  - Do not read: Festival Verifier date verification implementation.
  - Optional read: `oh_my_documents/docs/05_agent_spec/dynamo_lookup_tool.md` festival seed section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R4. Festival Candidate Channel`
  - `### R5b. DynamoLookupTool`
- Must Read Before Implementation:
  - `### R4. Festival Candidate Channel`
- Target Files:
  - `src/lovv_agent/tools/dynamo_lookup.py`
  - `src/lovv_agent/repositories/dynamodb.py`
  - `tests/test_destination_search.py`
- Out of Scope:
  - `year(start_date) == travelYear` verification.
  - City ranking.
- Acceptance Criteria:
  - Helper applies `festival.month == travelMonth`.
  - Helper applies non-festival travel theme OR matching.
  - Empty theme pool reports `no_required_theme_for_festival_seed`.
  - Empty city discovery seed reports `no_festival_city_seed`.
  - Empty anchored city lookup reports `no_festival_in_anchor_city`.
- Verification:
  - `uv run pytest tests/test_destination_search.py -k "festival_seed or fixed_city"`

### Subtask 4.4: Final Item Detail Enrichment and Warning Policy

- Purpose: Planner가 최종 일정에 배치한 attraction item만 DynamoDB detail로 보강하고 실패를 구조화 warning으로 남긴다.
- Required Context:
  - Final item detail enrichment and error policy.
- Context Budget:
  - Must read: Full Spec `### AWS Runtime Boundary`, `## Runtime Retrieval and Tool Boundaries`, `## Error Handling and Fallback`.
  - Do not read: Candidate Evidence package implementation beyond the boundary contract.
  - Optional read: `oh_my_documents/docs/05_agent_spec/dynamo_lookup_tool.md`.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### AWS Runtime Boundary`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `## Error Handling and Fallback`
- Target Files:
  - `src/lovv_agent/tools/dynamo_lookup.py`
  - `src/lovv_agent/repositories/dynamodb.py`
  - `tests/test_destination_search.py`
- Out of Scope:
  - Candidate Evidence primary/reserve package detail lookup.
  - Scoring-stage or broad candidate detail lookup.
- Acceptance Criteria:
  - Only final placed attraction items are enriched by default.
  - Missing `ddb_pk`/`ddb_sk` creates warning and `details=null`.
  - DynamoDB failures create warning and do not crash the whole graph.
- Verification:
  - `uv run pytest tests/test_destination_search.py -k "enrich or warning"`

---

## Task 5. ScoringTool and Candidate Selection

- Purpose: attraction/city scoring과 primary/reserve selection을 결정적으로 구현한다.
- Scope: score breakdown, distance helper, quota selection, audit fields.
- Dependencies: Task 4.
- Context Budget: ScoringTool and Candidate Selection sections only.
- Acceptance Criteria: no AWS/LLM, excluded categories not scored, deterministic audit, score values kept out of user-facing explanation text.
- Verification: scoring and selection unit tests.

### Subtask 5.1: Place and City Scoring

- Purpose: attraction candidate와 city ranking에 필요한 deterministic score를 계산한다.
- Required Context:
  - ScoringTool formula and excluded target policy.
- Context Budget:
  - Must read: Full Spec `### R6. ScoringTool`; `oh_my_documents/docs/05_agent_spec/scoring_tool.md` scoring target sections.
  - Do not read: Planner docs.
  - Optional read: Candidate Evidence scoring audit section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
  - Canonical Tool Spec: `oh_my_documents/docs/05_agent_spec/scoring_tool.md`
- Required Sections:
  - Full Spec `### R6. ScoringTool`
- Must Read Before Implementation:
  - `### R6. ScoringTool`
- Target Files:
  - `src/lovv_agent/tools/scoring.py`
  - `tests/test_scoring.py`
- Out of Scope:
  - AWS calls.
  - Candidate quota selection.
  - Planner slot placement.
- Acceptance Criteria:
  - `score_place` and `score_city` are deterministic.
  - Score breakdown includes all required fields.
  - `restaurant` and festival candidates are not scored in the current phase.
  - Congestion/visitor signals are accepted as inputs, not fetched internally.
- Verification:
  - `uv run pytest tests/test_scoring.py`

### Subtask 5.2: Candidate Selection Quota and Audit

- Purpose: score 결과에서 Planner가 사용할 primary/reserve attraction 후보를 구성한다.
- Required Context:
  - Candidate selection helper requirements.
- Context Budget:
  - Must read: Full Spec `### R7. Candidate Selection Helper`, `### Candidate Evidence Package`.
  - Do not read: AWS retrieval implementation.
  - Optional read: `oh_my_documents/docs/05_agent_spec/candidate_evidence_agent.md` primary/reserve section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R7. Candidate Selection Helper`
  - `### Candidate Evidence Package`
- Must Read Before Implementation:
  - `### R7. Candidate Selection Helper`
- Target Files:
  - `src/lovv_agent/tools/candidate_selection.py`
  - `tests/test_candidate_selection.py`
- Out of Scope:
  - Scoring formula changes.
  - Planner fallback.
- Acceptance Criteria:
  - Title dedup runs before primary selection.
  - Minimum searchable theme quota is filled first.
  - Soft max quota prevents single-theme dominance.
  - Relaxation is audited when needed.
  - Reserve candidates remain internal.
- Verification:
  - `uv run pytest tests/test_candidate_selection.py`

### Subtask 5.3: Exclusion and Edge-Case Tests

- Purpose: 미식/축제 제외 정책과 후보 부족 edge case를 회귀 테스트로 고정한다.
- Required Context:
  - Full Spec excluded category and fallback requirements.
- Context Budget:
  - Must read: Full Spec `### R6. ScoringTool`, `### R7. Candidate Selection Helper`, `## Error Handling and Fallback`.
  - Do not read: frontend/API docs.
  - Optional read: `oh_my_documents/docs/05_agent_spec/candidate_evidence_agent.md` scoring exclusion notes.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R6. ScoringTool`
  - `### R7. Candidate Selection Helper`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `## Error Handling and Fallback`
- Target Files:
  - `tests/test_scoring.py`
  - `tests/test_candidate_selection.py`
- Out of Scope:
  - New production code beyond test-driven fixes for current helpers.
- Acceptance Criteria:
  - Tests cover festival candidates excluded from scoring.
  - Tests cover gourmet external-link theme excluded from scoring.
  - Tests cover insufficient candidate count and quota shortfall audit.
- Verification:
  - `uv run pytest tests/test_scoring.py tests/test_candidate_selection.py`

---

## Task 6. Candidate Evidence Agent

- Purpose: mode selection, retrieval, scoring, fallback, package output을 orchestration한다.
- Scope: Candidate Evidence node, theme splitting, festival seed gate, selected city/package builder.
- Dependencies: Tasks 2, 4, 5.
- Context Budget: Candidate Evidence and runtime retrieval sections only.
- Acceptance Criteria: all three modes, festival seed hard gate, anchored city isolation, package schema, compact `candidate_reason_claims`.
- Verification: Candidate Evidence orchestration tests.

### Subtask 6.1: Mode Resolution and Theme Splitting

- Purpose: `destinationId`와 `includeFestivals`로 mode를 결정하고 searchable/external theme set을 분리한다.
- Required Context:
  - Candidate Evidence modes and theme handling.
- Context Budget:
  - Must read: Full Spec `### R3. Candidate Evidence Agent`, `### R4. Festival Candidate Channel`.
  - Do not read: Planner generation logic.
  - Optional read: `oh_my_documents/docs/05_agent_spec/candidate_evidence_agent.md` input policy and search modes.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R3. Candidate Evidence Agent`
  - `### R4. Festival Candidate Channel`
- Must Read Before Implementation:
  - `### R3. Candidate Evidence Agent`
- Target Files:
  - `src/lovv_agent/agents/candidate_evidence.py`
  - `tests/test_candidate_evidence.py`
- Out of Scope:
  - Actual AWS calls.
  - Planner food link generation.
- Acceptance Criteria:
  - `city_discovery`, `anchored_place_search`, and `festival_seeded_city_discovery` are selected correctly.
  - `미식·노포` is placed in `external_link_themes`, not `searchable_place_themes`.
  - `includeFestivals` is independent of `destinationId`.
- Verification:
  - `uv run pytest tests/test_candidate_evidence.py -k "mode or theme_split"`

### Subtask 6.2: City Discovery and Anchored Search Orchestration

- Purpose: non-festival city discovery와 anchored search를 retrieval/scoring/selection helper로 연결한다.
- Required Context:
  - Candidate Evidence orchestration, DestinationSearchTool, DynamoLookupTool, ScoringTool contracts.
- Context Budget:
  - Must read: Full Spec `### R3. Candidate Evidence Agent`, `### AWS Runtime Boundary`, `### Candidate Evidence Package`.
  - Do not read: Festival Verifier implementation.
  - Optional read: `candidate_evidence_runtime_retrieval.md`.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R3. Candidate Evidence Agent`
  - `### AWS Runtime Boundary`
  - `### Candidate Evidence Package`
- Must Read Before Implementation:
  - `### R3. Candidate Evidence Agent`
  - `### Candidate Evidence Package`
- Target Files:
  - `src/lovv_agent/agents/candidate_evidence.py`
  - `tests/test_candidate_evidence.py`
- Out of Scope:
  - Festival seed flow.
  - Planner output.
- Acceptance Criteria:
  - City discovery uses retrieval, scoring, and candidate selection helpers.
  - Anchored search applies fixed city filter and never mixes another city.
  - Candidate Evidence passes lightweight candidates and does not call final detail enrichment.
  - Package validates for `ok` and `insufficient_candidates`.
- Verification:
  - `uv run pytest tests/test_candidate_evidence.py -k "city_discovery or anchored"`

### Subtask 6.3: Festival-Seeded City Discovery and Fixed-City Festival Lookup

- Purpose: `includeFestivals=true`에서 월·테마 축제 seed/fixed-city lookup을 Candidate Evidence 앞단에 적용한다.
- Required Context:
  - Festival Candidate Channel hard gate and fallback signals.
- Context Budget:
  - Must read: Full Spec `### R4. Festival Candidate Channel`, `## Error Handling and Fallback`.
  - Do not read: Planner festival overlay internals.
  - Optional read: `oh_my_documents/docs/05_agent_spec/candidate_evidence_agent.md` festival channel section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R4. Festival Candidate Channel`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `### R4. Festival Candidate Channel`
- Target Files:
  - `src/lovv_agent/agents/candidate_evidence.py`
  - `tests/test_candidate_evidence.py`
- Out of Scope:
  - `year(start_date) == travelYear` verification.
  - City auto-relaxation when seed fails.
- Acceptance Criteria:
  - Festival-included city discovery excludes non-seeded cities before attraction scoring.
  - Selected festival candidates are limited to final selected city.
  - Empty theme pool, empty seed, and empty anchored lookup return the specified failure signals with `needs_clarification=true`.
  - Seed failure prevents Planner consumption.
- Verification:
  - `uv run pytest tests/test_candidate_evidence.py -k "festival_seed or fixed_city_festival"`

### Subtask 6.4: Package Builder, Status, Audit, and Reason Claim Candidates

- Purpose: Candidate Evidence Package의 status, counts, warnings, audits와 Planner가 검증할 `candidate_reason_claims`를 일관되게 구성한다.
- Required Context:
  - Candidate Evidence Package schema, candidate reason claim schema, and fallback policy.
- Context Budget:
  - Must read: Full Spec `### Candidate Evidence Package`, `### R3. Candidate Evidence Agent`, `## Error Handling and Fallback`, `## Review Checklist`.
  - Do not read: Response Packager response mapping.
  - Optional read: `oh_my_documents/docs/05_agent_spec/candidate_evidence_agent.md` package/audit sections.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### Candidate Evidence Package`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `### Candidate Evidence Package`
  - `## Error Handling and Fallback`
- Target Files:
  - `src/lovv_agent/agents/candidate_evidence.py`
  - `tests/test_candidate_evidence.py`
- Out of Scope:
  - User-facing recommendation copy.
- Acceptance Criteria:
  - Package validates for `ok`, `insufficient_candidates`, `no_candidate`, and `error`.
  - `needs_clarification` is set only when user input is required.
  - Retrieval and fallback audit fields are populated enough for review/debug.
  - `candidate_reason_claims` contains compact Korean claim candidates with `claim_id`, `scope`, `text_ko`, `evidence_refs`, `required_place_ids`, and `public_eligible`.
  - Candidate Evidence LLM does not change retrieval, scoring, selected city, quota, or fallback decisions.
  - Claim generation schema failure is retried within the configured bound and then recorded as a warning without corrupting the package.
  - Raw score values, top K details, and raw retrieval payloads are not copied into `candidate_reason_claims`.
  - Package is clearly internal and not formatted as public API response.
- Verification:
  - `uv run pytest tests/test_candidate_evidence.py -k "package or status or audit"`

---

## Task 7. Festival Verifier Agent

- Purpose: 최종 선택 도시의 축제 후보가 목표 연도/여행 월에 배치 가능한지 검증한다.
- Scope: verifier node, date normalization, cache boundary, status/policy calculation.
- Dependencies: Task 6.
- Context Budget: Festival Verifier sections only.
- Acceptance Criteria: selected-city candidates only, no city reranking, `year(start_date) == travelYear`, trip applicability.
- Verification: Festival Verifier unit tests.

### Subtask 7.1: Verifier Input and Candidate Scope

- Purpose: Candidate Evidence가 넘긴 `selected_festival_candidates`만 검증하도록 입력 범위를 제한한다.
- Required Context:
  - Festival Verifier ownership boundary.
- Context Budget:
  - Must read: Full Spec `### R8. Festival Verifier Agent`, `### Festival Verification Output`.
  - Do not read: DynamoLookupTool seed implementation.
  - Optional read: `oh_my_documents/docs/05_agent_spec/festival_verifier_agent.md` responsibility section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R8. Festival Verifier Agent`
  - `### Festival Verification Output`
- Must Read Before Implementation:
  - `### R8. Festival Verifier Agent`
- Target Files:
  - `src/lovv_agent/agents/festival_verifier.py`
  - `tests/test_festival_verifier.py`
- Out of Scope:
  - Creating festival city seeds.
  - Reranking cities.
  - Changing selected city.
- Acceptance Criteria:
  - Verifier skips when `includeFestivals=false`.
  - Verifier reads only `selected_festival_candidates`.
  - Verifier handles empty candidate input as structured skip/no-candidate state.
- Verification:
  - `uv run pytest tests/test_festival_verifier.py -k "scope or skip"`

### Subtask 7.2: Date Normalization and Verification Policy

- Purpose: DynamoDB festival detail 날짜를 정규화하고 초기 confirmed 정책을 적용한다.
- Required Context:
  - Initial verification policy.
- Context Budget:
  - Must read: Full Spec `### R8. Festival Verifier Agent`, `### Festival Verification Output`, `## Error Handling and Fallback`.
  - Do not read: external web verification docs.
  - Optional read: `oh_my_documents/docs/05_agent_spec/festival_verifier_agent.md` date normalization section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R8. Festival Verifier Agent`
  - `### Festival Verification Output`
- Must Read Before Implementation:
  - `### R8. Festival Verifier Agent`
  - `### Festival Verification Output`
- Target Files:
  - `src/lovv_agent/agents/festival_verifier.py`
  - `tests/test_festival_verifier.py`
- Out of Scope:
  - Official web verification expansion.
  - Planner block placement.
- Acceptance Criteria:
  - `event_start_date`/`eventstartdate` normalize to `start_date`.
  - `event_end_date`/`eventenddate` normalize to `end_date`.
  - Initial `confirmed` requires `year(start_date) == travelYear`.
  - Trip applicability is recalculated for current `travelMonth`.
- Verification:
  - `uv run pytest tests/test_festival_verifier.py -k "date or confirmed or applicability"`

### Subtask 7.3: Cache Boundary and Verification Tests

- Purpose: `festival_id + travelYear` cache boundary를 구현 가능하게 두고 상태별 테스트를 고정한다.
- Required Context:
  - Cache key and output status policy.
- Context Budget:
  - Must read: Full Spec `### R8. Festival Verifier Agent`, `## Verification`.
  - Do not read: AgentCore memory docs.
  - Optional read: `oh_my_documents/docs/05_agent_spec/festival_verifier_agent.md` cache section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R8. Festival Verifier Agent`
  - `## Verification`
- Must Read Before Implementation:
  - `### R8. Festival Verifier Agent`
- Target Files:
  - `src/lovv_agent/agents/festival_verifier.py`
  - `tests/test_festival_verifier.py`
- Out of Scope:
  - Durable cache table creation.
  - Raw web payload persistence.
- Acceptance Criteria:
  - Cache key uses `festival_id + travelYear` when cache adapter is present.
  - Cached date status does not skip request-specific applicability recalculation.
  - Tests cover skipped, confirmed, tentative/unknown, outdated, and no-candidate states.
- Verification:
  - `uv run pytest tests/test_festival_verifier.py`

---

## Task 8. Planner Agent and Validation

- Purpose: grounded evidence를 안전한 itinerary internals로 변환한다.
- Scope: Planner node, status gates, slot templates, festival overlay, food link/CTA policy, grounded explanation generation, validation helper.
- Dependencies: Tasks 6 and 7.
- Context Budget: Planner sections and public API response shape only when mapping is needed.
- Acceptance Criteria: no hallucinated places/restaurants/festivals, status gates, festival overlay, placeholders, grounded recommendation reasons.
- Verification: Planner unit tests.

### Subtask 8.1: Status Gates and Slot Templates

- Purpose: Candidate Evidence status에 따라 일정 생성 여부와 slot template 사용을 결정한다.
- Required Context:
  - Planner status gate and tripType template requirements.
- Context Budget:
  - Must read: Full Spec `### R9. Planner Agent`, `### Planner Output`, `## Error Handling and Fallback`.
  - Do not read: Response Packager response mapping.
  - Optional read: `oh_my_documents/docs/05_agent_spec/planner_agent.md` input/status sections.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R9. Planner Agent`
  - `### Planner Output`
  - `## Error Handling and Fallback`
- Must Read Before Implementation:
  - `### R9. Planner Agent`
  - `## Error Handling and Fallback`
- Target Files:
  - `src/lovv_agent/agents/planner.py`
  - `tests/test_planner.py`
- Out of Scope:
  - Full route optimization.
  - Backend response packaging.
- Acceptance Criteria:
  - `ok` creates itinerary from grounded candidates.
  - `insufficient_candidates` creates reduced itinerary only when safe.
  - `no_candidate` and `error` do not create a normal itinerary.
  - TripType slot templates are used instead of route optimization.
- Verification:
  - `uv run pytest tests/test_planner.py -k "status or slot"`

### Subtask 8.2: Festival Overlay

- Purpose: confirmed and trip-applicable festival만 attraction baseline 위에 배치한다.
- Required Context:
  - Planner festival placement and verifier output policy.
- Context Budget:
  - Must read: Full Spec `### R8. Festival Verifier Agent`, `### R9. Planner Agent`, `### Festival Verification Output`.
  - Do not read: festival seed lookup implementation.
  - Optional read: `oh_my_documents/docs/05_agent_spec/planner_agent.md` festival overlay section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R8. Festival Verifier Agent`
  - `### R9. Planner Agent`
  - `### Festival Verification Output`
- Must Read Before Implementation:
  - `### R9. Planner Agent`
  - `### Festival Verification Output`
- Target Files:
  - `src/lovv_agent/agents/planner.py`
  - `tests/test_planner.py`
- Out of Scope:
  - Festival city selection.
  - Unconfirmed festival placement.
- Acceptance Criteria:
  - Planner places only `date_status=confirmed` and applicable festivals.
  - Planner does not place tentative, unknown, outdated, or unverified festivals.
  - Anchored mode keeps the anchored city.
  - Festival overlay does not invent schedule details beyond available evidence.
- Verification:
  - `uv run pytest tests/test_planner.py -k "festival"`

### Subtask 8.3: Gourmet Link/CTA and Placeholder Policy

- Purpose: 미식 테마를 식당 후보 생성이 아니라 선택 도시 기반 링크/CTA/placeholder로 반영한다.
- Required Context:
  - Current gourmet handling and output safety policy.
- Context Budget:
  - Must read: Full Spec `### R3. Candidate Evidence Agent`, `### R9. Planner Agent`, `### R10. Response Packager`.
  - Do not read: restaurant table or vector design.
  - Optional read: `oh_my_documents/docs/05_agent_spec/planner_agent.md` gourmet section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R9. Planner Agent`
  - `### R10. Response Packager`
- Must Read Before Implementation:
  - `### R9. Planner Agent`
- Target Files:
  - `src/lovv_agent/agents/planner.py`
  - `src/lovv_agent/tools/links.py`
  - `tests/test_planner.py`
- Out of Scope:
  - Restaurant DB query.
  - Named restaurant generation from model knowledge.
  - New public API endpoint.
- Acceptance Criteria:
  - Gourmet intent produces food search link requirement, meal CTA, or placeholder/user notice.
  - No named restaurant is generated without grounded source.
  - Placeholder items use `placeId=null`.
  - Link packaging remains compatible with Response Packager.
- Verification:
  - `uv run pytest tests/test_planner.py -k "gourmet or food or placeholder"`

### Subtask 8.4: Planner Validation Helper

- Purpose: Planner output에서 ungrounded claim과 구조 오류를 잡아낸다.
- Required Context:
  - Planner validation and retry policy.
- Context Budget:
  - Must read: Full Spec `### R9. Planner Agent`, `## Error Handling and Fallback`, `## Review Checklist`.
  - Do not read: frontend rendering code.
  - Optional read: `oh_my_documents/docs/05_agent_spec/planner_agent.md` validation section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R9. Planner Agent`
  - `## Error Handling and Fallback`
  - `## Review Checklist`
- Must Read Before Implementation:
  - `### R9. Planner Agent`
  - `## Review Checklist`
- Target Files:
  - `src/lovv_agent/tools/validation.py`
  - `src/lovv_agent/agents/planner.py`
  - `tests/test_planner.py`
- Out of Scope:
  - Supervisor retry implementation.
- Acceptance Criteria:
  - Validation rejects ungrounded place names.
  - Validation rejects named restaurants from model knowledge.
  - Validation rejects unconfirmed festival placement.
  - Validation result is structured for Supervisor retry/fallback.
- Verification:
  - `uv run pytest tests/test_planner.py -k "validation"`

### Subtask 8.5: Grounded Explanation Generation

- Purpose: verified `candidate_reason_claims`, raw/soft query, detail-enriched final itinerary items, and verified festivals를 사용해 사용자에게 보일 추천 근거와 일정 흐름 설명을 짧고 안전하게 생성한다.
- Required Context:
  - Candidate Evidence reason claim candidates and Planner output explanation fields.
- Context Budget:
  - Must read: Full Spec `### R9. Planner Agent`, `### Candidate Evidence Package`, `### Planner Output`, `### R10. Response Packager`.
  - Do not read: raw retrieval payloads or scoring implementation internals.
  - Optional read: `oh_my_documents/docs/05_agent_spec/planner_agent.md` explanation/validation sections.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### R9. Planner Agent`
  - `### Candidate Evidence Package`
  - `### Planner Output`
- Must Read Before Implementation:
  - `### R9. Planner Agent`
  - `### Planner Output`
- Target Files:
  - `src/lovv_agent/agents/planner.py`
  - `src/lovv_agent/tools/validation.py`
  - `tests/test_planner.py`
- Out of Scope:
  - Exposing raw scores or ranking formulas to users.
  - Creating new facts beyond verified `candidate_reason_claims`, raw/soft query, detail-enriched final itinerary items, verified festivals, and grounded itinerary items.
- Acceptance Criteria:
  - Planner prompt/input uses verified `candidate_reason_claims`, raw/soft query, and enriched final item details, not full raw retrieval or score audit payloads.
  - `recommendationReasons` explain how selected city/place overviews match `cleaned_raw_query` and `soft_preference_query`.
  - `itineraryFlowReason` stays concise and does not mention internal score values, top K values, or ranking formulas.
  - `explanation_audit` maps generated explanation text to evidence refs and reason codes for internal validation.
  - Missing overview or weak alignment produces conservative wording or `user_notice`, not invented detail.
- Verification:
  - `uv run pytest tests/test_planner.py -k "explanation or recommendation_reason"`

---

## Task 9. Response Packaging and Graph Integration

- Purpose: LangGraph node를 연결하고 user-facing response를 안전하게 포장한다.
- Scope: graph compile, deterministic response packaging, response masking, integration tests.
- Dependencies: Tasks 1-8.
- Context Budget: graph and response packaging sections only.
- Acceptance Criteria: canonical node sequence, deterministic Supervisor baseline, internal evidence/`candidate_reason_claims`/`explanation_audit` hidden, API response compatible, clarification path.
- Verification: mocked graph integration tests.

### Subtask 9.1: Graph Wiring

- Purpose: 구현된 node를 LangGraph sequence로 연결한다.
- Required Context:
  - Full Spec graph shape.
- Context Budget:
  - Must read: Full Spec `### Graph Shape`, `### Clarification Fallback`, `## Component Responsibilities`.
  - Do not read: every agent detail doc.
  - Optional read: current node tests if they exist.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### Graph Shape`
  - `### Clarification Fallback`
  - `## Component Responsibilities`
- Must Read Before Implementation:
  - `### Graph Shape`
  - `### Clarification Fallback`
- Target Files:
  - `src/lovv_agent/graph.py`
  - `tests/test_graph_integration.py`
- Out of Scope:
  - AgentCore deployment.
  - Live AWS invocation.
- Acceptance Criteria:
  - Baseline graph wiring uses the deterministic Supervisor.
  - Graph includes Intent, Supervisor, Candidate Evidence, optional Festival Verifier, Planner, Response Packager.
  - Clarification path reaches user-wait state.
  - Nodes receive and return typed state.
- Verification:
  - `uv run pytest tests/test_graph_integration.py -k "graph or route"`

### Subtask 9.2: Response Packager Masking

- Purpose: Planner internals를 MVP `/recommendations` response shape로 매핑하고 내부 payload를 숨긴다.
- Required Context:
  - Response Packager and MVP API response contract.
- Context Budget:
  - Must read: Full Spec `### R10. Response Packager`, `### Planner Output`; `mvp_confirmed_api_contract.md` `/recommendations` response section.
  - Do not read: unrelated auth/map API sections.
  - Optional read: `oh_my_documents/docs/05_agent_spec/05_agent_spec.md` API mapping notes.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
  - API Contract: `oh_my_documents/docs/07_api_spec/mvp_confirmed_api_contract.md`
- Required Sections:
  - Full Spec `### R10. Response Packager`
  - Full Spec `### Planner Output`
- Must Read Before Implementation:
  - `### R10. Response Packager`
  - `### Planner Output`
- Target Files:
  - `src/lovv_agent/tools/response_packager.py`
  - `src/lovv_agent/tools/links.py`
  - `tests/test_graph_integration.py`
- Out of Scope:
  - New endpoint creation.
  - Durable recommendation storage beyond current TTL behavior.
- Acceptance Criteria:
  - Public response includes only safe destination, itinerary, explainability, festivalDateVerifications, and links fields.
  - Candidate Evidence Package, `candidate_reason_claims`, `explanation_audit`, raw retrieval audit, raw tool payloads, and internal reasoning are hidden.
  - `foodSearch` packaging uses the existing response link strategy without creating a new endpoint.
- Verification:
  - `uv run pytest tests/test_graph_integration.py -k "response_packager or response_masking"`

### Subtask 9.3: End-to-End Mocked Graph Tests

- Purpose: 주요 사용자 흐름을 live AWS/LLM 없이 통합 검증한다.
- Required Context:
  - Full Spec verification suite and fallback matrix.
- Context Budget:
  - Must read: Full Spec `## User/System Flow`, `## Error Handling and Fallback`, `## Verification`.
  - Do not read: provider docs.
  - Optional read: specific Task test files.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `## User/System Flow`
  - `## Error Handling and Fallback`
  - `## Verification`
- Must Read Before Implementation:
  - `## User/System Flow`
  - `## Verification`
- Target Files:
  - `tests/test_graph_integration.py`
- Out of Scope:
  - Live AWS smoke test.
  - Browser/frontend tests.
- Acceptance Criteria:
  - Tests cover normal city discovery.
  - Tests cover festival-included city discovery.
  - Tests cover anchored search.
  - Tests cover insufficient candidates.
  - Tests cover no-candidate and clarification path.
  - Tests cover Planner validation retry exhaustion.
- Verification:
  - `uv run pytest tests/test_graph_integration.py`

Optional follow-up after this baseline passes:

- Swap the Supervisor implementation with an experimental LLM Supervisor behind the same graph boundary.
- Reuse the same E2E fixtures and compare route outcomes against deterministic hard-rule validation.
- Treat this as a user-observable experiment, not an MVP production gate.

---

## Task 10. AWS/LLM Integration and AgentCore-Ready Harness Boundary

- Purpose: local LangGraph 검증을 유지하면서 실제 AWS runtime adapter, Bedrock Converse-compatible LLM 호출, prompt asset, 그리고 future AgentCore Runtime 전환이 쉬운 harness boundary를 연결한다.
- Scope: handler boundary, request/response adapter, runtime injection, AWS config boundary, Bedrock/embedding/S3 Vector/DynamoDB adapter wiring, prompt registry, Planner copy/explanation composer, state summary, memory-safe payload selection.
- Dependencies: Task 9.
- Context Budget: AWS/LLM adapter와 prompt contract, harness boundary, memory safety만 읽는다.
- Acceptance Criteria: local harness invocation, injected AWS/LLM adapters, versioned prompt assets, schema-validated LLM copy/explanation output, memory-safe summaries, no AgentCore deployment coupling.
- Verification: harness smoke test, prompt contract tests, mocked AWS/LLM adapter tests, memory-safety tests.

### Subtask 10.1: Local Harness Entrypoint

- Purpose: graph를 local test harness와 future runtime handler에서 같은 방식으로 호출할 수 있게 한다.
- Required Context:
  - Full Spec AWS/LLM runtime and graph integration sections.
- Context Budget:
  - Must read: Full Spec `### Model Adapter Boundary`, `### AWS Runtime Boundary`, `### Task 10. AWS/LLM Integration and AgentCore-Ready Harness Boundary`.
  - Do not read: AgentCore deployment docs unless a later deployment task is approved.
  - Optional read: `oh_my_documents/docs/05_agent_spec/agent_harness_design.md`.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### Model Adapter Boundary`
  - `### AWS Runtime Boundary`
  - `### Task 10. AWS/LLM Integration and AgentCore-Ready Harness Boundary`
- Must Read Before Implementation:
  - `### Task 10. AWS/LLM Integration and AgentCore-Ready Harness Boundary`
- Target Files:
  - `src/lovv_agent/graph.py`
  - `src/lovv_agent/adapters/`
  - `tests/test_harness.py`
- Out of Scope:
  - AgentCore Runtime deployment configuration.
  - IAM/SAM template changes.
- Acceptance Criteria:
  - Graph can be invoked from a local harness function.
  - Runtime adapters are injected.
  - Harness has no hard dependency on live AWS credentials.
- Verification:
  - `uv run pytest tests/test_harness.py -k "local_harness"`

### Subtask 10.2: AWS Runtime Adapter Boundary

- Purpose: 실제 AWS 연결을 graph business logic과 분리된 adapter/config boundary로 고정한다.
- Required Context:
  - AWS runtime boundary and existing tool adapter contracts.
- Context Budget:
  - Must read: Full Spec `### AWS Runtime Boundary`, `### R5. DestinationSearchTool`, `### R5b. DynamoLookupTool`, `### Model Adapter Boundary`.
  - Do not read: AgentCore deployment docs or infrastructure templates.
  - Optional read: existing mocked AWS adapter tests from Tasks 4 and 9.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### AWS Runtime Boundary`
  - `### Model Adapter Boundary`
  - `## Runtime Retrieval and Tool Boundaries`
- Must Read Before Implementation:
  - `### AWS Runtime Boundary`
  - `### Model Adapter Boundary`
- Target Files:
  - `src/lovv_agent/adapters/`
  - `src/lovv_agent/config.py`
  - `src/lovv_agent/graph.py`
  - `tests/test_harness.py`
  - `tests/test_aws_smoke.py`
- Out of Scope:
  - Concrete model ID selection in the Spec.
  - Hardcoded bucket, index, table, profile, or credential values.
  - AgentCore Runtime deployment configuration.
- Acceptance Criteria:
  - Bedrock Converse-compatible LLM, embedding, S3 Vector, and DynamoDB clients are created through injected adapters/config.
  - Local tests can still run with mocked adapters and no AWS credentials.
  - Runtime config is read from environment/config injection and validated before use.
  - Live AWS smoke tests are optional and skipped unless non-secret runtime config is present.
- Verification:
  - `uv run pytest tests/test_harness.py -k "adapter or runtime"`
  - Optional: `uv run pytest tests/test_aws_smoke.py`

### Subtask 10.3: Prompt Registry and Structured LLM Contracts

- Purpose: 실제 LLM 호출에 사용할 prompt asset을 코드 밖의 명시적 contract로 분리하고, 출력 schema/fallback을 강제한다.
- Required Context:
  - Model adapter boundary and Planner explanation contract.
- Context Budget:
  - Must read: Full Spec `### Model Adapter Boundary`, `### R9. Planner Agent`, `### Planner Output`, `### R10. Response Packager`.
  - Do not read: raw retrieval payloads or full scoring internals.
  - Optional read: `oh_my_documents/docs/05_agent_spec/planner_agent.md` prompt/grounding policy.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### Model Adapter Boundary`
  - `### R9. Planner Agent`
  - `### Planner Output`
- Must Read Before Implementation:
  - `### Model Adapter Boundary`
  - `### R9. Planner Agent`
- Target Files:
  - `src/lovv_agent/prompts/`
  - `src/lovv_agent/adapters/`
  - `src/lovv_agent/tools/explanation_composer.py`
  - `src/lovv_agent/agents/planner.py`
  - `tests/test_harness.py`
  - `tests/test_planner.py`
- Out of Scope:
  - Exposing raw scores, top K, or ranking formulas to the user.
  - Generating named restaurants from model knowledge.
  - Allowing malformed JSON or free-form text into graph state.
- Acceptance Criteria:
  - Prompt assets are versioned and Korean-capable.
  - Planner copy/explanation prompt input is limited to final placed items, detail-enriched item fields, verified festival outputs, raw/soft query, and `candidate_reason_claims`.
  - LLM output is schema-validated before entering graph state.
  - Generated fields cover user-facing itinerary `title`, `body`, `reason`, recommendation reasons, and concise itinerary flow text where applicable.
  - Schema failure, timeout, or unavailable LLM falls back to deterministic copy without inventing facts.
- Verification:
  - `uv run pytest tests/test_planner.py -k "explanation or composer or fallback"`
  - `uv run pytest tests/test_harness.py -k "prompt or llm"`

### Subtask 10.4: Final Detail Enrichment and Copy Composer Integration

- Purpose: Planner가 최종 배치한 항목에 대해서만 DynamoDB detail을 보강한 뒤, 그 보강된 근거로 사용자-facing copy를 생성한다.
- Required Context:
  - Planner output, Dynamo final item enrichment, response packaging contract.
- Context Budget:
  - Must read: Full Spec `### AWS Runtime Boundary`, `### R5b. DynamoLookupTool`, `### R9. Planner Agent`, `### R10. Response Packager`.
  - Do not read: public API redesign or DB schema creation.
  - Optional read: `oh_my_documents/docs/07_api_spec/mvp_confirmed_api_contract.md` `/recommendations` response section.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### AWS Runtime Boundary`
  - `### R5b. DynamoLookupTool`
  - `### R9. Planner Agent`
  - `### R10. Response Packager`
- Must Read Before Implementation:
  - `### AWS Runtime Boundary`
  - `### R9. Planner Agent`
- Target Files:
  - `src/lovv_agent/tools/dynamo_lookup.py`
  - `src/lovv_agent/tools/explanation_composer.py`
  - `src/lovv_agent/agents/planner.py`
  - `src/lovv_agent/tools/response_packager.py`
  - `tests/test_planner.py`
  - `tests/test_graph_integration.py`
- Out of Scope:
  - Candidate Evidence broad detail hydration.
  - Restaurant table lookup.
  - Weather replacement planning.
- Acceptance Criteria:
  - Dynamo detail lookup is performed after final itinerary placement, not during broad retrieval.
  - Latitude/longitude and supported detail fields are copied into final itinerary items when available.
  - LLM composer uses only enriched final items and approved grounding fields.
  - Response packaging preserves API-compatible `links`, `latitude`, `longitude`, `title`, `body`, and `reason` fields.
- Verification:
  - `uv run pytest tests/test_planner.py -k "detail or composer or coordinate"`
  - `uv run pytest tests/test_graph_integration.py -k "response_packager or coordinate"`

### Subtask 10.5: Memory-Safe Summary Boundary

- Purpose: future AgentCore Memory에 넘길 수 있는 summary 후보와 금지 payload를 코드 경계로 분리한다.
- Required Context:
  - State storage and memory-safety policy.
- Context Budget:
  - Must read: Full Spec `### UnifiedAgentState`, `### Model Adapter Boundary`, `### Task 10. AWS/LLM Integration and AgentCore-Ready Harness Boundary`.
  - Do not read: long-term persistence design beyond the Spec.
  - Optional read: `oh_my_documents/docs/05_agent_spec/agent_harness_design.md`.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### UnifiedAgentState`
  - `### Task 10. AWS/LLM Integration and AgentCore-Ready Harness Boundary`
  - `## Non-Goals`
- Must Read Before Implementation:
  - `### UnifiedAgentState`
  - `## Non-Goals`
- Target Files:
  - `src/lovv_agent/state.py`
  - `src/lovv_agent/adapters/`
  - `tests/test_harness.py`
- Out of Scope:
  - Actual long-term memory persistence.
  - Raw evidence storage.
- Acceptance Criteria:
  - Summary boundary excludes raw evidence, full Candidate Evidence Package, raw web content, secrets, and PII.
  - Trace IDs and safe summaries are available for future harness use.
  - Memory behavior is opt-in and does not persist data by default.
- Verification:
  - `uv run pytest tests/test_harness.py -k "memory_safe"`

### Subtask 10.6: Runtime Adapter Injection Tests

- Purpose: local, mocked, and future runtime adapters can be swapped without changing graph business logic.
- Required Context:
  - Adapter boundaries and non-goals.
- Context Budget:
  - Must read: Full Spec `### Model Adapter Boundary`, `### AWS Runtime Boundary`, `## Non-Goals`.
  - Do not read: provider-specific production docs.
  - Optional read: existing adapter tests from Tasks 2 and 4.
- Source of Truth:
  - Full Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
- Required Sections:
  - `### Model Adapter Boundary`
  - `### AWS Runtime Boundary`
  - `## Non-Goals`
- Must Read Before Implementation:
  - `### Model Adapter Boundary`
  - `### AWS Runtime Boundary`
- Target Files:
  - `src/lovv_agent/adapters/`
  - `src/lovv_agent/graph.py`
  - `tests/test_harness.py`
- Out of Scope:
  - Concrete model ID selection.
  - Mandatory live AWS smoke tests.
- Acceptance Criteria:
  - Graph tests can run with mocked LLM, embedding, S3 Vector, and DynamoDB adapters.
  - No adapter is created as an import-time global singleton.
  - Runtime injection failures produce structured error states.
- Verification:
  - `uv run pytest tests/test_harness.py`

## Global Verification Commands

Run these as the implementation matures:

```powershell
uv run pytest tests/test_schemas.py
uv run pytest tests/test_intent.py
uv run pytest tests/test_supervisor.py
uv run pytest tests/test_destination_search.py
uv run pytest tests/test_scoring.py tests/test_candidate_selection.py
uv run pytest tests/test_candidate_evidence.py
uv run pytest tests/test_festival_verifier.py
uv run pytest tests/test_planner.py
uv run pytest tests/test_graph_integration.py
uv run pytest tests/test_harness.py
```

Optional after deterministic tests pass and non-secret runtime config is available:

```powershell
uv run pytest tests/test_aws_smoke.py
```

## Review Checklist

- Every Subtask has purpose, required context, context budget, target files, out of scope, acceptance criteria, and verification.
- Subtasks are ordered by dependency.
- No Subtask requires public API redesign, DB schema creation, fixed model IDs, or AgentCore deployment.
- Task 10 owns real AWS/LLM adapter wiring, prompt assets, and prompt-backed copy/explanation composer before any AgentCore deployment task.
- `includeFestivals` remains a boolean outside travel themes.
- Festival seed/fixed-city lookup remains Candidate Evidence responsibility.
- Festival Verifier only verifies selected-city festival candidates.
- Gourmet handling avoids restaurant DB/vector lookup and named restaurant hallucination.
- User-facing title/body/reason text is either schema-validated LLM output grounded in final enriched items or deterministic fallback copy.
- Candidate Evidence Package remains internal.
- `needs_clarification=true` blocks downstream Planner consumption.
