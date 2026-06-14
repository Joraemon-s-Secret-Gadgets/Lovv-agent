# Lovv LangGraph Agent Implementation SPEC

> Status: Draft for review  
> Date: 2026-06-14  
> Repository: `Lovv-agent`  
> Authoring guide: `Lovv-agent/LANGGRAPH_SPEC_AUTHORING_INSTRUCTIONS.md`  
> Implementation target: LangGraph-based Lovv recommendation agent before AgentCore Runtime migration

## User Request Original

```text
그러면 해당 instructions도 최신화해주시고, 실제 spec 생성까지 해주세요.
```

Context: "해당 instructions" refers to `Lovv-agent/LANGGRAPH_SPEC_AUTHORING_INSTRUCTIONS.md`. The requested SPEC must use the updated instruction file and the current Lovv Agent canonical documents.

## Structured Agent Contract

- Display Name: Lovv LangGraph Agent Spec Agent
- Core Role: Spec Agent
- Domain Focus: Lovv LangGraph agent implementation
- Work Focus: Update the authoring instructions and generate the implementation SPEC before detailed implementation
- Execution Mode: Sequential
- Goal: Produce an implementation-ready SPEC for `Lovv-agent` that follows the latest Lovv Agent canonical contracts
- Source of Truth: PRO20x Spec Workflow, Lovv project context, updated LangGraph SPEC authoring instructions, and the Lovv Agent reference documents listed below
- Scope: Documentation only under `Lovv-agent`
- Out of Scope: Implementation code, public API redesign, DB schema changes, fixed model ID selection, long-term memory persistence, direct AgentCore Runtime deployment
- Required Context: `LANGGRAPH_SPEC_AUTHORING_INSTRUCTIONS.md`, `05_agent_spec.md`, agent detail specs, runtime retrieval/tool specs, and current MVP API contract
- Output Format: Markdown SPEC with goals, requirements, design, contracts, task breakdown, and verification plan
- Verification: Required references are listed, stale festival/restaurant assumptions are removed, internal contracts match current canonical documents
- Stop Condition: SPEC draft is generated and ready for user review

## Source Of Truth

Primary Lovv Agent references:

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

Compatibility references:

```text
oh_my_documents/docs/05_agent_spec/agent_harness_design.md
oh_my_documents/docs/07_api_spec/mvp_confirmed_api_contract.md
```

Rules:

- If this SPEC conflicts with the primary references, update this SPEC.
- `langgraph_app/SPEC.md` is a previous implementation draft and is not the source of truth for this repository.
- This SPEC may describe internal adapter boundaries, but it must not invent new public API endpoints or DB tables.

## Summary

`Lovv-agent` will implement the Lovv recommendation pipeline as an explicit LangGraph graph. The graph receives the current `/recommendations` structured request, normalizes it through `Intent_Agent`, retrieves grounded candidate evidence, optionally verifies festival dates, plans an itinerary, and packages a safe user-facing response.

The implementation must keep four boundaries strict:

- `Intent_Agent` structures input. It does not search, score, or plan.
- `Candidate_Evidence_Agent` searches and ranks grounded city/place evidence. Its package is internal Planner input, not an external API response or user-facing explanation.
- `Festival_Verifier_Agent` verifies selected-city festival candidates only. It does not create festival city seeds, rerank cities, or change the selected city.
- `Planner_Agent` writes itinerary internals from grounded evidence. It must not invent missing places, named restaurants, festivals, prices, opening hours, or live conditions.

Runtime retrieval uses S3 Vector search for candidate evidence and DynamoDB detail enrichment only after Planner final placement. JSON/local fixture search must not be introduced as the runtime source.

## Goals

- Implement the latest Lovv Agent canonical flow in `Lovv-agent` as a testable LangGraph graph.
- Define a stable `UnifiedAgentState` aligned with the canonical agent specs.
- Implement these graph nodes:
  - `Intent_Agent`
  - `Supervisor_Router`
  - `Candidate_Evidence_Agent`
  - `Festival_Verifier_Agent`
  - `Planner_Agent`
  - `Response_Packager` deterministic terminal component
- Implement these tool/helper boundaries:
  - `DestinationSearchTool`
  - `DynamoLookupTool`
  - `ScoringTool`
  - query embedding adapter
  - candidate selection helper
  - planner validation helper
  - response/link packaging helper
- Support these Candidate Evidence modes:
  - `city_discovery`
  - `anchored_place_search`
  - `festival_seeded_city_discovery`
- Support `includeFestivals=true` in both city discovery and anchored city flows.
- Keep restaurant DB/table/vector lookup out of the current runtime path; gourmet intent is handled by selected-city `foodSearch` link or meal CTA/placeholder policy.
- Keep model calls behind replaceable Bedrock Converse-compatible adapters without fixing a concrete model ID in this SPEC.
- Keep the design AgentCore-ready by isolating graph state, harness I/O, memory-safe summaries, and runtime adapters.
- Use `uv` as the canonical Python project, dependency, and verification runner.

## Non-Goals

- Do not implement code as part of this SPEC step.
- Do not define a new public API contract or endpoint.
- Do not create new DB tables, indexes, GSIs, or persistence policies in this SPEC.
- Do not persist in-progress chat messages or unfinished plan drafts server-side.
- Do not introduce WebSocket as the default transport.
- Do not use Neo4j or another graph database.
- Do not use S3 Vector metadata alone as confirmed detailed facts.
- Do not use JSON/local fixture files as runtime retrieval source.
- Do not hardcode AWS credentials, profiles, secrets, or model IDs.
- Do not migrate to AgentCore Runtime in the first implementation task.
- Do not introduce ad hoc `pip`, global Python, or local virtualenv instructions as the normal project workflow.

## User/System Flow

### Normal City Discovery

```text
POST /recommendations structured request
→ Intent_Agent
→ Supervisor_Router
→ Candidate_Evidence_Agent(mode=city_discovery)
→ Supervisor_Router
→ Festival_Verifier_Agent skipped when includeFestivals=false
→ Planner_Agent
→ Supervisor_Router
→ Response_Packager
→ END
```

### Festival-Included City Discovery

```text
POST /recommendations with includeFestivals=true and destinationId=null
→ Intent_Agent preserves includeFestivals and canonical themes
→ Candidate_Evidence_Agent runs Festival City Seed Channel first
→ seed rule: festival.month == travelMonth AND festival theme OR selected travel themes
→ only seeded cities enter attraction retrieval/scoring
→ selected_city is chosen from seeded cities
→ selected_festival_candidates for selected_city are handed to Festival_Verifier_Agent
→ Planner overlays only confirmed, trip-applicable festival blocks
```

If no city satisfies the festival seed rule, Candidate Evidence returns `needs_clarification=true`. The Supervisor must not call Festival Verifier or Planner. It sends the clarifying question to the user and ends the turn at `END_WAIT_USER`.

### Anchored Place Search

```text
POST /recommendations with destinationId
→ Intent_Agent preserves destinationId
→ Candidate_Evidence_Agent(mode=anchored_place_search)
→ all attraction retrieval/scoring is restricted to the anchored city
→ Planner keeps the anchored city
```

When `includeFestivals=true` is also selected, Candidate Evidence runs a fixed-city festival lookup inside the anchored city only. If no matching festival exists, the city is not changed automatically. The graph asks whether to continue without festivals or relax the anchor/festival condition.

### Clarification Fallback

Any worker node may return:

```json
{
  "needs_clarification": true,
  "clarifying_question": "..."
}
```

In that state the Supervisor:

- does not consume the partial output as Planner input,
- does not call downstream nodes,
- packages the question for the user,
- terminates the current run at `END_WAIT_USER`,
- lets the next user turn re-enter through `Intent_Agent`.

## Requirements

### R1. Intent Agent

- Accept the current `/recommendations` request shape:
  - `entryType`
  - `destinationId`
  - `country`
  - `travelYear`
  - `travelMonth`
  - `tripType`
  - `themes`
  - `includeFestivals`
  - `naturalLanguageQuery`
  - `userLocation`
- Treat API structured input as the source of truth for core fields.
- Do not infer or overwrite `country`, `travelMonth`, `tripType`, canonical travel `themes`, `destinationId`, or `includeFestivals` from natural language.
- Use `naturalLanguageQuery` only for:
  - `cleaned_raw_query`
  - `soft_preference_query`
  - unsupported conditions
  - explicit change-request signals
- MVP natural-language policy is intentionally conservative:
  - if trimmed `naturalLanguageQuery` is empty or shorter than the configured minimum, default `5` characters, skip Intent LLM extraction,
  - set `cleaned_raw_query=""`, `soft_preference_query=""`, and `unsupported_conditions=[]`,
  - continue from valid structured API input instead of asking a clarification question.
- Short or weak natural-language input is not a fallback/stop condition by itself.
- Normalize API `userLocation` into internal `user_location`.
- Convert canonical theme IDs into Candidate Evidence labels.
- Keep festival intent out of `active_required_themes`; festival inclusion is controlled only by `includeFestivals`.
- Produce `candidate_evidence_input`.
- Initialize `fulfilled_matrix` with `evidence`, `festival`, and `planning`.
- Use structured output enforcement through schema/tool output where supported.
- Validate the generated object against the local schema and use bounded retry/fallback on parse/schema failure.
- Must not search, score, choose a city, or write itinerary text.

### R2. Supervisor Router

- The MVP/default Supervisor is deterministic; production routing must not depend on an LLM decision.
- Keep Supervisor routing behind a replaceable implementation boundary so an experimental LLM Supervisor can later be swapped in after deterministic E2E tests pass.
- Any experimental LLM Supervisor must be checked by hard routing rules or fall back to the deterministic Supervisor before it can be considered for production use.
- Route by `fulfilled_matrix` and worker status.
- Use only `X`, `O`, `△`, and `N/A`.
- Standard keys are:
  - `evidence`
  - `festival`
  - `planning`
- Process pending work in this order:
  1. `evidence`
  2. `festival`
  3. `planning`
- Skip Festival Verifier when `includeFestivals=false` and mark `festival=N/A`.
- If any worker returns `needs_clarification=true`, route to `END_WAIT_USER`.
- Enforce `validation_retry_count <= 2` for Planner validation loops.
- Keep raw RAG payloads, raw web payloads, and full raw tool responses out of Supervisor state.

### R3. Candidate Evidence Agent

- Accept only `candidate_evidence_input` from Intent.
- Determine mode from `destinationId` and `includeFestivals`.
- Supported modes:

| Mode | Trigger | Meaning |
| --- | --- | --- |
| `city_discovery` | `destinationId == null` and `includeFestivals=false` | Search eligible cities and select one city by attraction evidence |
| `anchored_place_search` | `destinationId != null` | Keep the anchored city and search within that city only |
| `festival_seeded_city_discovery` | `destinationId == null` and `includeFestivals=true` | Build festival city seed first, then retrieve/score attractions inside seeded cities |

- Split themes into:
  - `active_required_themes`: all user-selected travel themes after normalization.
  - `searchable_place_themes`: themes that can use attraction S3 Vector search.
  - `external_link_themes`: themes handled through external link/CTA policy.
- Current gourmet handling:
  - `미식·노포` maps to `external_link_themes`.
  - It is not used for attraction S3 Vector search.
  - It is not a scoring target.
  - It is passed to Planner as a selected-city `foodSearch`/meal CTA requirement.
- Use `DestinationSearchTool` for S3 Vector attraction retrieval.
- Use `DynamoLookupTool` for DynamoDB festival seed lookup and final item detail enrichment.
- Use `ScoringTool` for deterministic place/city scoring.
- Merge duplicate candidates by stable `place_id`.
- Apply searchable-place theme AND gate to searchable themes only.
- Select primary and reserve attraction candidates based on trip budget and theme quota.
- Return a Candidate Evidence Package with:
  - `status`
  - `needs_clarification`
  - `clarifying_question`
  - `mode`
  - `selected_city`
  - `city_rankings`
  - `recommended_places`
  - `reserve_places`
  - `festival_candidates`
  - `selected_festival_candidates`
  - `festival_seed_audit`
  - `coverage_audit`
  - `retrieval_audit`
  - `candidate_counts`
  - `warnings`
  - `fallback_audit`
  - `candidate_reason_claims`
- Use the Candidate Evidence LLM to build `candidate_reason_claims` as compact, evidence-referenced Korean claim candidates when `status` permits Planner consumption:
  - `claim_id`
  - `scope`
  - `text_ko`
  - `evidence_refs`
  - `required_place_ids`
  - `public_eligible`
- Candidate Evidence LLM must not change retrieval, scoring, city selection, quota, or fallback decisions.
- If claim generation fails schema validation after bounded retry, keep the package valid with empty or templated non-public claims and record a warning.
- Keep scoring values and retrieval details in internal audits; do not expose them as user-facing explanation text.
- Must not create itinerary text or final user-facing recommendation copy.

### R4. Festival Candidate Channel

- Run inside Candidate Evidence only when `includeFestivals=true`.
- Use DynamoDB festival data before attraction retrieval/scoring.
- For city discovery, use this hard gate:

```text
festival.month == travelMonth
AND
(
  festival.assigned_theme in non_festival_theme_pool
  OR any(festival.theme_tags in non_festival_theme_pool)
)
```

- Multiple user-selected themes are interpreted as OR for festival theme matching.
- `festival_event` or `축제·이벤트` must not be added to the theme pool.
- If theme pool is empty, return:

```json
{
  "status": "no_candidate",
  "failure_signals": ["no_required_theme_for_festival_seed"],
  "needs_clarification": true
}
```

- If no seeded city exists, return:

```json
{
  "status": "no_candidate",
  "failure_signals": ["no_festival_city_seed"],
  "needs_clarification": true
}
```

- For anchored search, query only the anchored city. If no matching festival exists, return `no_festival_in_anchor_city` with `needs_clarification=true`.
- Festival candidates are not included in place/city scoring.
- `selected_festival_candidates` must contain only candidates from the final selected city.

### R5. DestinationSearchTool

- Wrap S3 Vector attraction search, attraction candidate normalization, city grouping, and searchable theme gate.
- Provide `search_candidates(query_vector, city_id=None, theme=None, top_k=...)`.
- `top_k` must be configuration-driven and test-covered. This SPEC does not hardcode a universal value.
- Use S3 Vector query configuration through environment/runtime config:
  - vector bucket name
  - index name
  - query vector
  - top K
  - metadata return
  - distance return
- Apply metadata filters:
  - `entity_type="attraction"` for place search
  - optional `city_id`
  - optional single active `theme` through `theme_tags == theme`
- General place search must not use `entity_type="festival"` or restaurant entity search in the current phase.
- `미식·노포` must not trigger S3 Vector place search; it is handled later as
  a selected-city external food search/link requirement.
- Normalize chunk keys into stable `place_id`.

### R5b. DynamoLookupTool

- Wrap DynamoDB-backed festival seed lookup and final placed item detail enrichment.
- Provide `search_festival_city_seeds(country, travel_month, theme_pool, city_id=None, max_candidates=...)`.
- Provide `enrich_final_places(final_places)`.
- Festival seed lookup runs before attraction retrieval when `includeFestivals=true`.
- Use `ddb_pk` and `ddb_sk` for final item DynamoDB `GetItem`.
- Detail enrichment is called only after Planner final placement, not during Candidate Evidence package construction.
- Missing detail keys or lookup failures must produce warnings and `details=null`, not graph crashes.
- Must not perform S3 Vector search, scoring, quota selection, or itinerary writing.

### R6. ScoringTool

- Remain deterministic Python logic with no AWS calls and no LLM calls.
- Score only attraction candidates in the current phase.
- Provide `score_place`.
- Provide `score_city`.
- Provide distance helper logic where needed.
- Produce score breakdown fields:
  - `semantic_evidence`
  - `theme_coverage`
  - `theme_balance`
  - `scale_correction`
  - `candidate_sufficiency`
  - `distance_penalty`
  - `congestion_penalty`
- Accept congestion/visitor signals from orchestration; do not query external statistics directly.
- Must not select primary quota or write itinerary text.

### R7. Candidate Selection Helper

- Apply title dedup before primary selection.
- Fill minimum searchable theme quota first.
- Use soft max quota to reduce single-theme dominance.
- Relax soft max quota only when primary slots would otherwise remain empty.
- Preserve audit fields for:
  - quota shortfall
  - relaxed slots
  - deduplicated titles
  - unfilled primary slots
- Keep reserves as internal fallback candidates, not a user-facing list.

### R8. Festival Verifier Agent

- Run only when `includeFestivals=true` and Candidate Evidence has `selected_festival_candidates`.
- Verify candidates from the final selected city only.
- Do not create city seeds.
- Do not rerank cities.
- Do not change selected city or anchored city.
- Initial implementation uses DynamoDB normalized festival detail first.
- Normalize `event_start_date`/`eventstartdate` and `event_end_date`/`eventenddate` into `start_date`/`end_date`.
- Initial confirmed condition:

```text
year(start_date) == travelYear
```

- Recalculate trip applicability from current request:
  - travel month overlap when only `travelMonth` exists,
  - date range overlap when a future request provides a concrete range.
- Return structured verification JSON only.
- Do not pass raw web snippets or HTML to Planner.
- Suggested cache key is `festival_id + travelYear`, with request-specific applicability recalculated per run.

### R9. Planner Agent

- Convert Candidate Evidence Package and Festival Verifier output into itinerary internals.
- Use `recommended_places` first and `reserve_places` only as fallback.
- Keep the final itinerary centered on one selected city.
- In `anchored_place_search`, never change the anchored city.
- Place festivals only when:
  - `includeFestivals=true`,
  - verification `date_status=confirmed`,
  - the festival is applicable to the trip month/date,
  - provenance matches selected-city festival candidates.
- Treat festival placement as an overlay on the attraction baseline, typically Day 1 afternoon when a slot is available.
- Do not place tentative, unknown, outdated, or unverified festivals as confirmed itinerary blocks.
- For `no_candidate` or `error`, do not generate a normal itinerary.
- For `insufficient_candidates`, generate a reduced itinerary only when a selected city and grounded candidates exist.
- Use tripType slot templates in MVP; do not attempt full route optimization.
- Do not generate named restaurants from model knowledge.
- For gourmet themes, provide a selected-city food search link, meal CTA, or placeholder/user notice according to available response packaging.
- Use `source=placeholder` and `placeId=null` for unavoidable free-time or meal-choice placeholders.
- Enrich final placed attraction items from DynamoDB before generating user-facing reasons when detail keys are available.
- Generate user-facing recommendation reasons from verified `candidate_reason_claims`, raw/soft query, enriched itinerary items, verified festivals, and validation results.
- Reject or rewrite any claim whose `required_place_ids` are not present in the final itinerary or whose `evidence_refs`/details do not support the text.
- Do not mention raw scores, ranking formulas, top K values, or internal audit fields in user-facing explanation text.
- Produce `explanation_audit` that maps public explanation sentences to evidence refs and reason codes for internal validation.
- Generate `user_notice` when candidate shortage, unsupported conditions, unconfirmed festivals, or live-info limitations affect the result.
- Validate that output does not contain ungrounded place/festival claims.

### R10. Response Packager

- Convert Planner internal output to the current `/recommendations` response shape.
- Remain deterministic: do not call an LLM, run recommendation reasoning, or alter selected evidence.
- Hide internal Candidate Evidence Package, `candidate_reason_claims`, `explanation_audit`, raw retrieval audit, raw evidence, raw tool payloads, and internal reasoning.
- Expose only safe user-facing fields:
  - destination
  - itinerary
  - explainability
  - festivalDateVerifications
  - links
- Package selected-city `foodSearch` under the response link strategy without creating a new endpoint in this SPEC.
- Keep `recommendationId` TTL behavior aligned with the MVP API contract.
- Do not persist in-progress conversation or plan drafts.

## Design

### Proposed Package Shape

The first implementation should use a small Python package with stable contracts.

```text
Lovv-agent/
  pyproject.toml
  uv.lock
  docs/
    specs/
      LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md
  src/
    lovv_agent/
      __init__.py
      graph.py
      state.py
      config.py
      models/
        schemas.py
      agents/
        intent.py
        supervisor.py
        candidate_evidence.py
        festival_verifier.py
        planner.py
      tools/
        destination_search.py
        dynamo_lookup.py
        scoring.py
        candidate_selection.py
        validation.py
        links.py
        response_packager.py
      adapters/
        bedrock_converse.py
        aws_clients.py
        embeddings.py
      repositories/
        dynamodb.py
        s3_vectors.py
  tests/
```

Task breakdown may refine exact filenames, but responsibility boundaries must remain intact.

### Python Project and Dependency Management

`Lovv-agent` uses `uv` as the canonical Python workflow.

Rules:

- Python runtime is pinned to Python 3.12.
- `pyproject.toml` must keep `requires-python = "==3.12.*"`.
- `.python-version` must stay aligned with Python 3.12 for `uv` interpreter selection.
- `pyproject.toml` is the single source of truth for Python package metadata and dependencies.
- `uv.lock` is the reproducibility artifact and should be updated whenever dependencies change.
- Verification commands must run through `uv run ...` from the `Lovv-agent` root.
- Development setup should use `uv sync`.
- Runtime dependencies and dev dependencies must be separated.
- AgentCore migration may copy or adapt the package into an AgentCore app, but dependency resolution should still start from `pyproject.toml`/lockfile rather than unmanaged global environments.

Initial development commands:

```powershell
uv sync
uv run python -c "import lovv_agent; print(lovv_agent.__version__)"
uv run pytest
```

### Graph Shape

```text
START
→ intent_agent
→ supervisor_router
→ candidate_evidence_agent
→ supervisor_router
→ festival_verifier_agent or skip
→ supervisor_router
→ planner_agent
→ supervisor_router
→ response_packager
→ END
```

Clarification path:

```text
worker returns needs_clarification=true
→ supervisor_router
→ response_packager packages clarifying question
→ END_WAIT_USER
```

### Model Adapter Boundary

- LLM calls must go through a replaceable Bedrock Converse-compatible adapter.
- This SPEC does not fix a concrete model ID.
- Prompt contracts must be Korean-capable and schema-oriented.
- Structured output should be enforced by tool/schema features where available.
- Every LLM output that enters graph state must pass local schema validation.
- On schema failure:
  - retry within a bounded limit,
  - record validation failure,
  - return a safe clarification or fallback instead of passing malformed data downstream.

### AWS Runtime Boundary

```text
query embedding adapter
→ DestinationSearchTool
→ S3 Vector attraction search
→ city grouping and searchable theme gate
→ ScoringTool
→ candidate selection
→ Candidate Evidence Package
→ Planner final placement
→ DynamoLookupTool.enrich_final_places()
→ Planner explanation generation
```

Festival seed boundary:

```text
includeFestivals=true
→ DynamoLookupTool.search_festival_city_seeds()
→ DynamoDB festival candidates
→ seed city pool or fixed-city festival candidates
→ Candidate Evidence Package.selected_festival_candidates
→ Festival_Verifier_Agent
```

Runtime config must come from environment/config injection:

- AWS region
- optional local AWS profile
- S3 Vector bucket/index
- DynamoDB table name
- embedding model or embedding adapter identifier
- search top K budgets
- verifier candidate K
- retry and timeout settings

No real credentials or secrets may be hardcoded.

## Component Responsibilities

| Component | Owns | Must Not Own |
| --- | --- | --- |
| Intent Agent | API input normalization, raw/soft query split, unsupported conditions, initial matrix | search, scoring, itinerary |
| Supervisor Router | routing, matrix transitions, retry/clarification stop | raw retrieval or raw web interpretation |
| Candidate Evidence Agent | evidence package, mode selection, festival seed/fixed-city lookup, city/place ranking, primary/reserve, evidence-referenced reason claim candidates, fallback audit | final user response, final recommendation reasons, festival date verification |
| DestinationSearchTool | S3 Vector attraction search, attraction candidate normalization, city grouping, searchable theme gate | DynamoDB reads, scoring, itinerary, public response |
| DynamoLookupTool | DynamoDB festival seed helper, final placed item detail enrichment | S3 Vector search, scoring, quota, itinerary, public response |
| ScoringTool | deterministic place/city scores and score audit | AWS calls, search, quota, itinerary |
| Festival Verifier | selected-city festival year/date verification and Planner policy | city seed creation, city reranking, itinerary writing |
| Planner Agent | itinerary internals, DynamoLookupTool final item detail enrichment call, explanation, validation, notices, festival overlay, food link/CTA policy | broad candidate retrieval, ungrounded live facts |
| Response Packager | deterministic API response packaging and internal payload hiding | LLM calls, recommendation reasoning changes |

## State and Data Contracts

### UnifiedAgentState

Implementation should start from a Pydantic model or TypedDict-compatible schema.

| Group | Fields |
| --- | --- |
| Request | `request_id`, `entry_type`, `country`, `travel_year`, `travel_month`, `trip_type`, `destination_id`, `themes`, `include_festivals`, `natural_language_query`, `user_location` |
| Conversation | `messages`, `conversation_summary`, `turn_index`, `session_id` |
| Trace | `recommendation_request_id`, `agent_run_id`, `node_timings` |
| Intent | `extracted_inputs`, `active_required_themes`, `searchable_place_themes`, `external_link_themes`, `cleaned_raw_query`, `soft_preference_query`, `unsupported_conditions`, `candidate_evidence_input` |
| Routing | `next_node`, `fulfilled_matrix`, `validation_retry_count`, `needs_clarification`, `clarifying_question` |
| Evidence | `candidate_evidence_package`, `selected_destination` |
| Festival | `festival_verifications` |
| Planning | `planner_output`, `validation_result` |
| Serving | `response_payload`, `response_status` |

State storage policy:

- Raw messages may be present during one run, but Supervisor should route from summaries/status fields.
- Raw RAG results, raw web content, full Candidate Evidence Package, embedding cache, secrets, and PII must not be stored in long-term memory or normal logs.
- Full Candidate Evidence Package is an in-run payload only.
- AgentCore Memory, if added later, may store summary fields only after a separate approved persistence/memory spec.

### Candidate Evidence Input

```json
{
  "country": "KR",
  "travelMonth": 6,
  "travelYear": 2026,
  "tripType": "2d1n",
  "destinationId": null,
  "active_required_themes": ["바다·해안", "미식·노포"],
  "cleaned_raw_query": "바다를 보고 오래된 지역 맛집도 가고 싶다",
  "soft_preference_query": "너무 붐비지 않는 조용한 분위기",
  "unsupported_conditions": [],
  "user_location": {
    "latitude": 37.5665,
    "longitude": 126.978
  },
  "includeFestivals": false
}
```

Implementation may add:

```json
{
  "execution_mode": "city_discovery",
  "fixed_city_id": null,
  "city_anchor": null
}
```

### Candidate Evidence Package

```json
{
  "status": "ok",
  "failure_signals": [],
  "needs_clarification": false,
  "clarifying_question": null,
  "mode": "city_discovery",
  "selected_city": {
    "city_id": "uuid",
    "city_name_ko": "도시명",
    "country": "KR",
    "selection_reason_code": ["theme_coverage", "candidate_sufficiency"]
  },
  "city_anchor": null,
  "city_rankings": [],
  "recommended_places": [],
  "reserve_places": [],
  "festival_candidates": [],
  "selected_festival_candidates": [],
  "festival_seed_audit": {},
  "coverage_audit": {},
  "retrieval_audit": {},
  "candidate_counts": {},
  "warnings": {},
  "fallback_audit": {},
  "candidate_reason_claims": [
    {
      "claim_id": "city_reason_1",
      "scope": "city_selection",
      "text_ko": "선택 도시는 바다·해안 테마 후보가 충분합니다.",
      "evidence_refs": ["selected_city", "city_rankings[0]", "coverage_audit"],
      "required_place_ids": [],
      "public_eligible": true
    },
    {
      "claim_id": "place_pool_1",
      "scope": "place_pool",
      "text_ko": "대표 후보들은 사용자의 바다 산책 요청과 연결됩니다.",
      "evidence_refs": ["recommended_places:place-1"],
      "required_place_ids": ["place-1"],
      "public_eligible": true
    }
  ]
}
```

Allowed `status` values:

- `ok`
- `insufficient_candidates`
- `no_candidate`
- `error`

Downstream agents must branch on `status` and `needs_clarification` before assuming `selected_city` or places exist.

`candidate_reason_claims` are not final public explanation text. Candidate
Evidence may use an LLM to compress deterministic audits into these short
Korean claim candidates, but each claim must carry evidence references and
place requirements so Planner can verify it against final placed,
detail-enriched items before public use.

### Festival Verification Output

```json
{
  "festival_id": "FEST-123",
  "name": "축제명",
  "date_status": "confirmed",
  "start_date": "2026-06-10",
  "end_date": "2026-06-12",
  "is_applicable_to_trip": true,
  "planner_policy": "placeable",
  "source_type": "dynamodb_detail",
  "confidence": 0.8,
  "evidence_summary": "내부 정규화 detail의 시작일자가 입력 travelYear와 일치함을 확인했다."
}
```

Planner may place only `date_status=confirmed` and trip-applicable festivals.

### Planner Output

Planner internal output must include:

- `itinerary`
- `alternativeItinerary` when safe and useful
- `recommendationReasons`
- `itineraryFlowReason`
- `externalLinks`
- `confidence`
- `user_notice`
- `validation_result`
- `explanation_audit`

`explanation_audit` maps generated explanation text back to evidence refs and reason codes. Response Packager maps safe public fields to the `/recommendations` response and hides internal evidence packages, `candidate_reason_claims`, and `explanation_audit`.

## Runtime Retrieval and Tool Boundaries

### S3 Vector Metadata Contract

Attraction candidate records must support at least:

| Field | Purpose |
| --- | --- |
| `key` | chunk identifier |
| `place_id` | stable place identifier after chunk removal |
| `distance` | vector distance |
| `metadata.entity_type` | current place search uses `attraction` |
| `metadata.city_id` | grouping and anchor filter |
| `metadata.city_name_ko` | fallback display/group helper |
| `metadata.theme_tags` | active theme filter, searchable theme gate, and quota |
| `metadata.title` | display and dedup |
| `metadata.latitude`, `metadata.longitude` | scoring and route hints |
| `metadata.ddb_pk`, `metadata.ddb_sk` | DynamoDB detail enrichment after final placement |

Festival seed records come from DynamoDB and must preserve:

- `festival_id`
- `name` or `title`
- `country`
- `city_id`
- `city_name`
- `month`
- `theme_tags` or `assigned_theme`
- `event_start_date` or `eventstartdate`
- `event_end_date` or `eventenddate`
- source/provenance fields

### Search Budgets

Search budgets must be runtime-configurable:

- per-theme attraction top K,
- optional raw/soft channel top K,
- max festival seed candidates,
- verifier top K.

Implementation tests should cover small budgets and sufficient budgets. This SPEC intentionally does not hardcode a universal `top_k`.

## Error Handling and Fallback

| Condition | Required behavior |
| --- | --- |
| Missing required structured input | Intent returns `needs_clarification=true` |
| Empty or short `naturalLanguageQuery` | Intent skips LLM extraction, sets raw/soft query fields empty, and proceeds from structured API input |
| Natural language conflicts with structured core fields | Intent records clarification/change request; do not silently override |
| LLM output schema failure | bounded retry, then safe clarification/fallback |
| Query embedding failure | Candidate Evidence `status=error` |
| S3 Vector call failure | Candidate Evidence `status=error` |
| No attraction candidates | Candidate Evidence `status=no_candidate` or `insufficient_candidates` with audit |
| No city survives searchable theme gate | Candidate Evidence `status=no_candidate` |
| `includeFestivals=true` but theme pool empty | `no_required_theme_for_festival_seed`, `needs_clarification=true` |
| Festival city seed empty | `no_festival_city_seed`, `needs_clarification=true` |
| Anchored city has no matching festival | `no_festival_in_anchor_city`, `needs_clarification=true` |
| Missing `ddb_pk`/`ddb_sk` on final placed item | warning, `details=null`, no crash |
| DynamoDB detail failure on final placed item | warning, `details=null`, confidence impact |
| Festival unconfirmed | Planner must not place festival block |
| Planner validation failure | rewrite/remove offending item; stop after retry limit |
| Candidate Evidence `needs_clarification=true` | Supervisor routes to `END_WAIT_USER`; Planner not called |

## Acceptance Criteria

This SPEC is accepted when:

- It preserves `User Request Original`.
- It contains a `Structured Agent Contract`.
- It lists current primary Lovv Agent reference documents.
- It pins the local Python runtime to Python 3.12.
- It defines short `naturalLanguageQuery` handling as LLM extraction skip, not a clarification fallback.
- It defines the LangGraph node sequence and Supervisor matrix routing.
- It defines `END_WAIT_USER` clarification behavior.
- It defines responsibilities for Intent, Candidate Evidence, Festival Verifier, Planner, Response Packager, DestinationSearchTool, DynamoLookupTool, and ScoringTool.
- It keeps Candidate Evidence Package internal.
- It uses S3 Vector and DynamoDB as runtime retrieval/detail sources.
- It rejects JSON/local fixture runtime retrieval.
- It avoids fixed LLM model IDs.
- It treats `includeFestivals` as a boolean outside canonical travel themes.
- It uses festival month/theme seed as a hard gate before city discovery scoring when festivals are included.
- It supports anchored city festival lookup without automatic city changes.
- It removes restaurant candidate lookup/scoring from the current runtime path.
- It defines state, input, output, status, fallback, validation, and test contracts.
- It contains implementation-ready Task Breakdown but does not write implementation code.

## Constraints and Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| AWS metadata schema drift | Candidate parsing or ranking breaks | Contract tests for required metadata and DynamoDB fields |
| Festival seed misses valid festivals | Festival-included recommendations may over-fallback | Audit seed query, preserve failure signals, add fixture tests |
| Search top K too small | Cities with enough evidence may be missed | Runtime-configurable budgets and regression tests |
| Fixed-city festival miss | User may be blocked even when city has weak festival data | Clear clarification question and audit reason |
| DynamoDB detail missing | Planner may overclaim facts | Warning, `details=null`, conservative Planner wording |
| Planner overgeneration | Ungrounded places/festivals/restaurant names | Validation helper, source checks, placeholders |
| Public API link ambiguity | Food search link placement may drift | Keep link packaging behind the Response Packager component and align with MVP API `links` object |
| AgentCore coupling too early | Local verification becomes harder | Implement local LangGraph first; keep harness adapters isolated |
| Memory leakage | Raw evidence or PII could be persisted | Store only summaries in future memory specs; no raw payload logging |

## Task Breakdown

### Task 1. Project Skeleton and Schemas

- Purpose: Create the importable Python package and shared contracts before node logic.
- Scope: package skeleton, config schema, state schema, enum/status types, test skeleton.
- Dependencies: This SPEC approved.
- Target Files:
  - `.gitignore`
  - `pyproject.toml`
  - `uv.lock`
  - `src/lovv_agent/state.py`
  - `src/lovv_agent/config.py`
  - `src/lovv_agent/models/schemas.py`
  - `tests/`
- Acceptance Criteria:
  - Package imports successfully.
  - `UnifiedAgentState` includes required groups.
  - Candidate Evidence, Festival Verification, and Planner output schemas validate sample payloads.
  - No AWS or LLM calls are implemented yet.
  - `uv` is the canonical verification runner.
- Verification: `uv run` import smoke test and schema unit tests.

### Task 2. Intent Agent and Structured Output Adapter

- Purpose: Normalize `/recommendations` structured input into Candidate Evidence input.
- Scope: Intent node, theme mapping, raw/soft query extraction, unsupported conditions, schema-enforced LLM output adapter.
- Dependencies: Task 1.
- Target Files:
  - `src/lovv_agent/agents/intent.py`
  - `src/lovv_agent/adapters/bedrock_converse.py`
  - `tests/test_intent.py`
- Acceptance Criteria:
  - API core fields are not re-parsed from natural language.
  - Empty or shorter-than-threshold natural language skips LLM extraction and proceeds from structured input.
  - `includeFestivals` is preserved independently from themes.
  - `userLocation` is normalized to `user_location`.
  - Missing or conflicting core input returns `needs_clarification=true`.
  - LLM output is schema-validated with bounded retry/fallback.
- Verification: unit tests for API priority, conflict handling, theme mapping, structured output failure.

### Task 3. Supervisor Router

- Purpose: Implement deterministic graph routing and clarification stop behavior while preserving a swappable Supervisor boundary for later experiments.
- Scope: Supervisor node, matrix transition helper, retry limit, `END_WAIT_USER` route, replaceable router interface/boundary.
- Dependencies: Task 1.
- Target Files:
  - `src/lovv_agent/agents/supervisor.py`
  - `src/lovv_agent/graph.py`
  - `tests/test_supervisor.py`
- Acceptance Criteria:
  - Deterministic Supervisor routing remains the default and source of truth for MVP graph execution.
  - No LLM call is introduced for baseline Supervisor routing in Task 3.
  - Graph wiring can later swap the deterministic Supervisor with an experimental Supervisor implementation without changing worker agent contracts.
  - Matrix uses only `X`, `O`, `△`, `N/A`.
  - Routing order is evidence, festival, planning.
  - `includeFestivals=false` skips verifier.
  - `needs_clarification=true` prevents downstream calls.
- Verification: unit tests for routing states and retry limits.

### Task 4. DestinationSearchTool, DynamoLookupTool, and AWS Retrieval Adapters

- Purpose: Implement S3 Vector attraction search through `DestinationSearchTool` and DynamoDB lookup through `DynamoLookupTool`.
- Scope: S3 Vector repository, DynamoDB repository, S3 filter construction, festival seed lookup, final detail enrichment warning handling.
- Dependencies: Task 1.
- Target Files:
  - `src/lovv_agent/tools/destination_search.py`
  - `src/lovv_agent/tools/dynamo_lookup.py`
  - `src/lovv_agent/repositories/s3_vectors.py`
  - `src/lovv_agent/repositories/dynamodb.py`
  - `src/lovv_agent/adapters/aws_clients.py`
  - `tests/test_destination_search.py`
- Acceptance Criteria:
  - Builds correct attraction S3 Vector filters.
  - Does not use festival or restaurant entity search for general place retrieval.
  - Implements festival seed/fixed-city lookup logical contract.
  - Normalizes chunk key to `place_id`.
  - Keeps DynamoDB reads out of `DestinationSearchTool`.
  - Missing DynamoDB keys on final placed items produce warnings.
- Verification: mocked S3/DynamoDB unit tests.

### Task 5. ScoringTool and Candidate Selection

- Purpose: Rank attractions/cities deterministically and select primary/reserve candidates.
- Scope: place/city scoring, score breakdown, title dedup, quota logic, audit.
- Dependencies: Task 4 candidate shape.
- Target Files:
  - `src/lovv_agent/tools/scoring.py`
  - `src/lovv_agent/tools/candidate_selection.py`
  - `tests/test_scoring.py`
  - `tests/test_candidate_selection.py`
- Acceptance Criteria:
  - ScoringTool has no AWS or LLM calls.
  - Festival and gourmet external-link themes are not scored.
  - Score breakdown is present.
  - Score and ranking audits remain internal and are not used verbatim as user-facing explanation text.
  - Selection audit records quota shortfall and relaxation.
- Verification: deterministic scoring and selection unit tests.

### Task 6. Candidate Evidence Agent

- Purpose: Orchestrate mode selection, retrieval, scoring, fallback, and package output.
- Scope: Candidate Evidence node, mode handling, festival seed gate, package builder, audit.
- Dependencies: Tasks 2, 4, 5.
- Target Files:
  - `src/lovv_agent/agents/candidate_evidence.py`
  - `tests/test_candidate_evidence.py`
- Acceptance Criteria:
  - Supports `city_discovery`, `anchored_place_search`, and `festival_seeded_city_discovery`.
  - Festival-included city discovery excludes non-seeded cities before attraction scoring.
  - Anchored search never mixes another city.
  - Seed failures return `needs_clarification=true`.
  - `candidate_reason_claims` contain evidence-referenced Korean claim candidates without exposing raw scores or finalizing public explanation text.
  - Package schema validates for `ok`, `insufficient_candidates`, `no_candidate`, and `error`.
- Verification: mocked orchestration tests for normal, anchored, festival seed, and fallback paths.

### Task 7. Festival Verifier Agent

- Purpose: Verify selected-city festival candidates before Planner placement.
- Scope: verifier node, date normalization, cache boundary, status/policy calculation.
- Dependencies: Task 6.
- Target Files:
  - `src/lovv_agent/agents/festival_verifier.py`
  - `tests/test_festival_verifier.py`
- Acceptance Criteria:
  - Skips when `includeFestivals=false`.
  - Verifies only `selected_festival_candidates`.
  - Confirms initial date status only when `year(start_date) == travelYear`.
  - Recalculates applicability for current trip month.
  - Does not pass raw web payloads.
- Verification: unit tests for skipped, confirmed, tentative/unknown, outdated, and no-candidate states.

### Task 8. Planner Agent and Validation

- Purpose: Convert grounded evidence into safe itinerary internals.
- Scope: Planner node, status gates, slot templates, festival overlay, food link/CTA policy, validation helper.
- Dependencies: Tasks 6 and 7.
- Target Files:
  - `src/lovv_agent/agents/planner.py`
  - `src/lovv_agent/tools/validation.py`
  - `src/lovv_agent/tools/links.py`
  - `tests/test_planner.py`
- Acceptance Criteria:
  - `ok` creates itinerary from grounded evidence.
  - `insufficient_candidates` creates a reduced itinerary only when safe.
  - `no_candidate/error` does not create a normal itinerary.
  - Confirmed applicable festivals can be overlaid.
  - Unconfirmed festivals are not placed.
  - Gourmet intent does not produce named restaurants from model knowledge.
  - Placeholder items use `placeId=null`.
  - Recommendation reasons use verified `candidate_reason_claims`, raw/soft query, detail-enriched final itinerary items, and verified festival outputs, and produce an internal `explanation_audit`.
- Verification: Planner normal/fallback/festival/gourmet/validation tests.

### Task 9. Response Packaging and Graph Integration

- Purpose: Wire nodes into LangGraph and package safe user-facing output.
- Scope: graph compile, deterministic response packaging, response masking, integration tests.
- Dependencies: Tasks 1-8.
- Target Files:
  - `src/lovv_agent/graph.py`
  - `src/lovv_agent/tools/response_packager.py`
  - `tests/test_graph_integration.py`
- Acceptance Criteria:
  - Graph executes the canonical node sequence.
  - Baseline E2E graph tests use the deterministic Supervisor.
  - Clarification path ends at `END_WAIT_USER`.
  - Internal evidence, `candidate_reason_claims`, `explanation_audit`, and audit are hidden from default response.
  - Response shape aligns with the MVP `/recommendations` contract.
  - Retry limit is enforced.
  - After baseline E2E passes, the same fixture suite can be reused for an optional LLM Supervisor swap experiment that compares routing outcomes against deterministic hard rules.
- Verification: end-to-end mocked graph tests for normal, festival-included, anchored, insufficient, no-candidate, and clarification paths.

### Task 10. AgentCore-Ready Harness Boundary

- Purpose: Prepare the implementation for later AgentCore Runtime migration without coupling the first implementation to AgentCore.
- Scope: handler boundary, request/response adapter, state summary policy, trace IDs, memory-safe payload selection.
- Dependencies: Task 9.
- Target Files:
  - `src/lovv_agent/graph.py`
  - `src/lovv_agent/adapters/`
  - future harness files defined by approved AgentCore task
- Acceptance Criteria:
  - Graph can be invoked by a local test harness.
  - Runtime adapters are injected, not global singletons.
  - Long-term memory candidates exclude raw evidence, full Candidate Evidence Package, raw web content, secrets, and PII.
  - No AgentCore deployment config is required for local tests.
- Verification: local harness smoke test and memory-safety unit tests.

## Verification

Minimum verification suite:

- Schema tests for `UnifiedAgentState`, Candidate Evidence input/package, Festival verification, Planner output.
- Intent tests for structured API priority, conflict handling, theme mapping, `includeFestivals`, and schema-enforced output.
- Supervisor tests for matrix transition, retry limit, and `END_WAIT_USER`.
- DestinationSearchTool mocked AWS tests for S3 filter payload and key normalization.
- DynamoLookupTool mocked AWS tests for festival seed lookup and final item detail enrichment warnings.
- ScoringTool deterministic tests for place/city scores and excluded categories.
- Candidate Evidence orchestration tests for `city_discovery`, `anchored_place_search`, `festival_seeded_city_discovery`, and clarification fallbacks.
- Festival Verifier tests for date status and planner policy.
- Planner tests for status gates, slot templates, festival overlay, gourmet link/CTA policy, placeholder safety, and validation failure.
- Graph integration tests with mocked adapters.
- Optional LLM Supervisor swap experiment after deterministic graph integration passes; it must use the same E2E fixtures and compare route decisions against deterministic hard-rule validation.
- Optional AWS smoke test using non-secret environment config after deterministic tests pass.

## Review Checklist

- `User Request Original` is preserved.
- `Structured Agent Contract` is included.
- Primary reference documents are listed.
- Candidate Evidence Package remains internal.
- Runtime retrieval uses S3 Vector for candidate evidence and DynamoDB detail enrichment after Planner final placement.
- JSON/local fixture runtime retrieval is not introduced.
- No concrete LLM model ID is fixed.
- `includeFestivals` is not modeled as a travel theme.
- Festival seed/fixed-city lookup responsibility belongs to Candidate Evidence.
- Festival Verifier only verifies selected-city candidates.
- Planner cannot create ungrounded places, named restaurants, festivals, or live facts.
- Candidate Evidence `needs_clarification=true` routes to user wait, not Planner.
- Deterministic Supervisor remains the MVP default; any LLM Supervisor is an optional post-baseline experiment guarded by deterministic route validation.
- Task Breakdown is implementation-ready but no code has been written.
