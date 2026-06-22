# Lovv AgentCore V1 FM Routing and Gateway SPEC

> Status: Draft for review
> Date: 2026-06-18
> Repository: `Lovv-agent`
> Implementation target: AgentCore `v1` goal reset to per-agent Foundation Model routing inside a single `LovvAgentV1` Runtime, with Gateway as a later additive tool-exposure phase
> Region baseline: `us-east-1`

## Document Review

Related documents already exist and point in the same direction:

- `docs/reports/02_MODEL_SELECTION.md`
  - Uses `us-east-1` as the model-selection baseline.
  - Says current code has one `LOVV_LLM_MODEL_ID`.
  - Recommends node-level tiering for cost, quality, and rate-limit distribution.
  - Says provider choice should not be Anthropic-only.
  - Says context window is not Lovv's main constraint; TPM/RPM and input-token size are more important.
  - Warns that each candidate model/profile must be verified in `us-east-1` before deploy.
- `docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`
  - Keeps model calls behind replaceable Bedrock Converse-compatible adapters.
  - Does not fix concrete model IDs in the core spec.
  - Requires schema validation and fallback for every LLM output entering graph state.
- `docs/reports/LANGGRAPH_SPEC_AUTHORING_INSTRUCTIONS.md`
  - Says model ID, provider tier, and runtime config must not be fixed in specs unless needed.
  - Requires structured output/tool schema/JSON Schema validation where available.
- `docs/reports/05_TRANSITION_PLAN.md`
  - Keeps Phase 1 as single AgentCore Runtime lift-and-shift.
  - Moves tool externalization/Gateway to a later log-gated phase.

Gap found:

- Existing documents mention node-level tiering as a need, but there was no dedicated V1 implementation spec that makes **per-agent FM routing** the primary AgentCore V1 goal.
- A separate Gateway draft existed, but it treated Gateway as its own Spec. This document merges that Gateway direction into the V1 roadmap as a follow-on additive phase.

## Claude Opus Review Summary

Claude Opus review conclusion:

- Do not split AgentCore Runtime only to use different FMs per agent.
- Keep a single `LovvAgentV1` Runtime.
- Implement FM separation as per-node model adapter/config routing inside the existing LangGraph harness.
- Runtime split is justified only when independent deployment, scaling, IAM/VPC isolation, failure isolation, or incompatible runtime/process boundaries become real requirements.

This spec adopts that conclusion.

## V1 Goal

`LovvAgentV1` remains a **single AgentCore Runtime** in `us-east-1`, while the LangGraph harness supports **per-agent Foundation Model routing**.

Each LLM-using agent/node can select its own model at runtime through configuration:

- Intent Agent
- Candidate Evidence reason-claim generation
- Planner copy/explanation generation
- Optional future LLM Supervisor experiment

Provider choice must remain unrestricted at the architecture level. The implementation should prefer the existing Bedrock Converse-compatible adapter path for AgentCore V1, but the config model must not encode Anthropic-only, OpenAI-only, or any other provider-specific assumption.

Gateway remains in scope only as an additive tool-exposure phase after the FM-routing boundary is implemented and verified. Gateway must not force Runtime split.

## Non-Goals

- Do not split `Intent_Agent`, `Candidate_Evidence_Agent`, `Festival_Verifier_Agent`, or `Planner_Agent` into separate AgentCore Runtimes for V1.
- Do not change `/recommendations` request or response shape.
- Do not introduce AgentCore Gateway as the primary V1 goal. Gateway is a follow-on additive phase.
- Do not move S3 Vectors or DynamoDB retrieval behind Gateway in this work.
- Do not hardcode a concrete model ID in core code.
- Do not restrict supported FM providers to Anthropic.
- Do not switch to a provider API that bypasses existing schema validation unless a later approved adapter spec covers it.

## Runtime Topology Decision

### Use Single Runtime

```text
AgentCore Runtime: LovvAgentV1
  -> LangGraph harness
    -> Intent Agent                  -> resolved FM: intent
    -> Candidate Evidence Agent       -> resolved FM: candidate_evidence
    -> Festival Verifier              -> no FM by default
    -> Planner Agent                  -> resolved FM: planner
    -> Response Packager              -> no FM
```

Reason:

- FM selection is an adapter-routing concern, not a deployment-boundary concern.
- Current LangGraph state is in-process and mutable.
- Splitting Runtime would force state serialization, network hops, extra IAM, extra deploy targets, harder rollback, and more cold-start surfaces.
- A single Runtime preserves deterministic Supervisor routing and current response-contract safety.

### When Runtime Split Becomes Valid

Runtime split can be reconsidered only when at least one condition is true:

- An agent needs an independent release/canary schedule.
- An agent needs isolated scaling, concurrency, or quota management that cannot be handled by model tiering or in-process limits.
- An agent needs materially different IAM, VPC, network, or data-boundary isolation.
- An agent must use a non-Converse runtime or a provider SDK that cannot safely coexist in the current process.
- An agent is exposed as a standalone product/service for external consumers.
- Observability shows that Runtime split improves p95 latency, fault isolation, or cost after in-process tuning.

Different FM per agent alone is **not** enough to split Runtime.

## Configuration Design

### Environment Variables

Keep the existing global fallback:

```text
LOVV_LLM_MODEL_ID
```

Add per-agent model overrides:

```text
LOVV_INTENT_LLM_MODEL_ID
LOVV_CANDIDATE_EVIDENCE_LLM_MODEL_ID
LOVV_PLANNER_LLM_MODEL_ID
LOVV_SUPERVISOR_LLM_MODEL_ID
```

Optional adapter overrides, to keep provider assumptions out of the config shape:

```text
LOVV_LLM_ADAPTER_ID
LOVV_INTENT_LLM_ADAPTER_ID
LOVV_CANDIDATE_EVIDENCE_LLM_ADAPTER_ID
LOVV_PLANNER_LLM_ADAPTER_ID
LOVV_SUPERVISOR_LLM_ADAPTER_ID
```

Region remains global for V1:

```text
LOVV_AWS_REGION=us-east-1
```

Resolution rule:

1. If agent-specific model ID is set, use it.
2. Else use `LOVV_LLM_MODEL_ID`.
3. If no model resolves for a live LLM path, fail early with a clear config error.
4. Log the resolved agent-to-model map at startup without credentials or prompt payloads.

### Naming Rationale

Use `LOVV_INTENT_LLM_MODEL_ID`, not `LOVV_LLM_MODEL__INTENT`, because the existing config style is flat, explicit, and environment-friendly on Windows/PowerShell.

## Provider Policy

V1 architecture must not restrict providers.

Allowed model sources:

- Any `us-east-1` Bedrock model or inference profile that supports the required structured-output behavior.
- Cross-region inference profiles reachable from `us-east-1`, when model availability requires them.
- Future provider adapters, if they implement the same runtime invocation and structured validation contract.

Current practical constraint:

- Existing code uses a Bedrock Converse structured-output adapter.
- Any selected model must support the current structured output path or must be introduced with a separate adapter change and tests.

## Context And Rate-Limit Policy

Context:

- Existing model-selection docs state Lovv's current LLM inputs fit within common 128K+ context windows.
- Context window is not the main selection constraint for V1.
- Planner has the largest input and should be monitored for token growth.

Rate limits:

- Node-level FM routing helps distribute RPM/TPM across model buckets.
- Intent can use a smaller, cheaper, schema-stable model.
- Candidate Evidence reason-claim generation can use a low/medium tier model.
- Planner can use a higher-quality or larger-context model because it controls final copy/explanation quality.

V1 must measure:

- per-node prompt tokens
- per-node completion tokens
- per-node latency
- per-node structured-output retry count
- per-node throttling count

## Recommended Initial Model Routing

This spec does not hardcode production model IDs. The following is a candidate routing pattern to validate in `us-east-1`:

| Node | Selection Strategy | Notes |
| --- | --- | --- |
| Intent Agent | low-cost structured-output model | Small input, strict schema, deterministic fallback available |
| Candidate Evidence reason claim | low/medium structured-output model | Must not change selected city, status, or scoring |
| Planner copy/explanation | higher-quality Korean-capable structured-output model | Largest input and highest user-facing quality impact |
| Supervisor | unset for V1 | Deterministic Supervisor remains default |

Before deploy, every selected model/profile must be verified with:

```powershell
aws bedrock list-foundation-models --region us-east-1
aws bedrock list-inference-profiles --region us-east-1
```

And with one minimal Converse structured-output smoke call for each configured node model.

## Gateway Additive Phase

Gateway is retained in this merged Spec as a later phase, not as the primary V1 goal.

Purpose:

- Expose selected Lovv tools through AgentCore-managed tool infrastructure.
- Preserve the main `LovvAgentV1` Runtime as the owner of `/recommendations`.
- Validate Gateway packaging, auth, IAM, invocation, and observability with a low-risk tool before moving any higher-risk logic.

### Gateway Strategy

Recommended first Gateway target: `LinkBuilder` / `build_default_city_links`.

Reason:

- It is deterministic and side-effect free.
- It does not call AWS, Bedrock, S3 Vectors, DynamoDB, or external web services.
- It has a small stable input shape: city name and country.
- It is public-safe because it returns map/search CTA links instead of generated factual claims.
- It validates Gateway mechanics without expanding IAM risk.

Tool contract draft:

```json
{
  "name": "build_city_links",
  "description": "Build safe public map, stay search, and food search links for a selected Lovv city.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["cityNameKo", "country"],
    "properties": {
      "cityNameKo": {
        "type": "string",
        "minLength": 1
      },
      "country": {
        "type": "string",
        "minLength": 1
      }
    }
  },
  "outputSchema": {
    "type": "object",
    "additionalProperties": true,
    "required": ["map", "staySearch", "foodSearch"],
    "properties": {
      "map": { "type": "object" },
      "staySearch": { "type": "object" },
      "foodSearch": { "type": "object" }
    }
  }
}
```

Example input:

```json
{
  "cityNameKo": "고성군",
  "country": "KR"
}
```

### Deferred Gateway Targets

`ScoringTool` is a reasonable second target only after LinkBuilder proves Gateway mechanics.

Reasons to wait:

- Its input shape is larger and tied to internal candidate schemas.
- It may become latency-sensitive.
- Keeping scoring in-process preserves deterministic ranking until Gateway overhead is measured.

Still deferred:

- S3 Vector search, because it requires IAM, latency, and retrieval-quality validation.
- DynamoDB enrichment, because it is part of the current repository boundary.
- Planner or LLM calls, because they would alter orchestration and cost behavior.

### Gateway Project Structure

Gateway work may add:

```text
src/lovv_agent/gateway/
  __init__.py
  link_builder.py             # Gateway handler adapter for LinkBuilder
  schemas.py                  # reusable Gateway schema constants if useful

app/LovvGatewayV1/
  main.py or handler.py       # slim Gateway compute app, if using AgentCoreRuntime compute
  lovv_agent/                 # synced minimal package copy only if CodeZip requires it
  pyproject.toml

tests/
  test_agentcore_gateway_link_builder.py
  test_agentcore_gateway_config.py
```

Sync rule:

- If Gateway code imports `lovv_agent` from a deployed `app/*` CodeZip directory, keep the deployed copy in sync with `src/lovv_agent` in the same change.
- Do not edit only a vendored `app/*/lovv_agent` copy and forget canonical `src/lovv_agent`.

Gateway adapter style:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent.tools.links import build_default_city_links


def handle_build_city_links(payload: Mapping[str, Any]) -> dict[str, Any]:
    city_name_ko = _required_text(payload.get("cityNameKo"), "cityNameKo")
    country = _required_text(payload.get("country"), "country")
    return build_default_city_links(city_name_ko=city_name_ko, country=country)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized
```

### Gateway Verification

Unit tests:

- Validate `handle_build_city_links` accepts valid Gateway input.
- Validate whitespace trimming and empty/missing field rejection.
- Assert output contains `map`, `staySearch`, and `foodSearch`.
- Assert generated URLs remain deterministic.

Contract tests:

- Validate `agentcore/agentcore.json` contains the Gateway and expected tool name when Gateway phase starts.
- Validate the tool input schema requires `cityNameKo` and `country`.
- Validate the Gateway target does not request AWS data-plane permissions for LinkBuilder.

Deployment smoke:

- `agentcore validate --json` succeeds.
- `agentcore deploy --target v1 --dry-run --json` succeeds.
- `agentcore deploy --target v1 --diff --json` shows only intended Gateway resources.
- Deployed Gateway tool invocation returns deterministic LinkBuilder output.
- Deployed `LovvAgentV1` recommendation smoke still succeeds after Gateway deploy.

Gateway invocation command remains CLI-version dependent and must be finalized during implementation.

## Code Structure

Expected source changes:

```text
src/lovv_agent/config.py
  - add per-agent LLM config fields
  - preserve global fallback

src/lovv_agent/adapters/aws_runtime.py
  - create separate RuntimeInvoker instances per resolved agent model
  - keep Bedrock client shared

src/lovv_agent/harness.py
  - inject intent runtime into Intent call
  - inject candidate_evidence runtime into CandidateEvidenceAgent
  - inject planner runtime into PlannerAgent

tests/test_config.py
tests/test_harness.py
  - validate fallback and agent-specific override behavior
```

If AgentCore deployment uses vendored code:

```text
app/LovvAgentV1/lovv_agent/
  - sync the same source changes after canonical src changes
```

Expected AgentCore config changes:

```text
agentcore/agentcore.json
  - keep LOVV_AWS_REGION=us-east-1
  - keep LOVV_LLM_MODEL_ID as global fallback
  - add optional per-agent model env vars
  - keep agentCoreGateways empty until Gateway additive phase starts
```

## Code Style

Use explicit node names and a central resolver.

```python
def resolve_llm_model_id(settings: LlmRoutingSettings, node: str) -> str | None:
    override = settings.model_ids_by_node.get(node)
    if override:
        return override
    return settings.default_model_id
```

Do not branch on provider names in graph nodes. Graph nodes receive a callable runtime and do not care which provider/model created it.

## Testing Strategy

Unit tests:

- `RuntimeConfig.from_env` parses all new env vars.
- Agent-specific model IDs override `LOVV_LLM_MODEL_ID`.
- Unset agent-specific values fall back to `LOVV_LLM_MODEL_ID`.
- Missing live model config fails with a clear error.

Harness tests:

- Intent request uses the intent model.
- Candidate Evidence reason-claim request uses the candidate-evidence model.
- Planner explanation request uses the planner model.
- Existing single-model tests continue to pass through fallback.

AgentCore config tests:

- `agentcore/agentcore.json` keeps `LOVV_AWS_REGION=us-east-1`.
- Agent-specific model env vars are optional and non-secret.
- No provider-specific env var is required.

Live smoke tests:

- For each configured model, run a minimal structured-output Converse request.
- Run one full `/recommendations` smoke call.
- Confirm CloudWatch has no model AccessDenied, unsupported model, or structured-output failures.

## Commands

Local tests:

```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest
```

Focused config/harness tests:

```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_harness.py tests/test_config.py
```

Compile check:

```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run python -m compileall src tests app\LovvAgentV1
```

AgentCore validation:

```powershell
agentcore validate --json
```

Deploy dry run:

```powershell
$env:UV_CACHE_DIR='.cache\uv'; agentcore deploy --target v1 --dry-run --json
```

## Boundaries

Always:

- Keep one `LovvAgentV1` Runtime for V1.
- Keep `us-east-1` as the deployment and validation baseline.
- Keep provider choice open at the architecture level.
- Keep structured-output validation and deterministic fallback.
- Keep deterministic Supervisor as the V1 default.
- Keep model IDs in config/env, not hardcoded in core code.
- Keep Gateway as additive and tool-scoped; it must not change `/recommendations` behavior.

Ask first:

- Adding a new non-Bedrock provider adapter.
- Moving an agent into a separate Runtime.
- Making Supervisor LLM-driven in production.
- Selecting final production model IDs.
- Changing region away from `us-east-1`.
- Moving S3 Vector or DynamoDB retrieval behind Gateway.
- Making the main Runtime call Gateway instead of in-process tool functions.
- Adding Lambda instead of AgentCoreRuntime compute for Gateway.

Never:

- Do not split Runtime just because models differ by agent.
- Do not make Anthropic, OpenAI, or any other provider mandatory in core architecture.
- Do not bypass schema validation for an LLM output entering graph state.
- Do not log prompts, raw RAG payloads, credentials, or secrets while logging model routing.
- Do not alter recommendation outputs only to prove Gateway integration.
- Do not expose ungrounded restaurant, festival, price, or availability claims through Gateway.

## Success Criteria

- V1 goal is documented as per-agent FM routing, not Runtime split.
- Current single Runtime structure remains intact.
- Per-agent model configuration exists with global fallback.
- Provider choice remains unrestricted in architecture.
- `us-east-1` remains the region baseline.
- Tests prove each LLM-using node can use a different configured model.
- Existing `/recommendations` behavior remains contract-compatible.
- AgentCore deployment validates with the new env config.
- Gateway direction is documented in the same V1 Spec as an additive phase, not as a competing primary goal.

## Open Questions

1. Which concrete model IDs should be used for the first deployed V1 routing set?
   - Recommendation: choose after `us-east-1` availability and structured-output smoke checks.
2. Should `FestivalVerifier` remain deterministic in V1?
   - Recommendation: yes.
3. Should `Supervisor` get an LLM model env var now even if deterministic?
   - Recommendation: include optional config for future experiments, but leave unset in production.
4. Should Gateway work continue in parallel?
   - Recommendation: not as the primary V1 goal. Gateway can remain a later additive tool-exposure phase.
5. Gateway first tool: confirm `LinkBuilder`, or choose `ScoringTool`.
   - Recommendation: `LinkBuilder`.
6. Gateway authorizer: use `NONE` for short-lived smoke testing, or start with `AWS_IAM` immediately?
   - Recommendation: `AWS_IAM` if the CLI/deploy flow supports it cleanly; otherwise `NONE` only for controlled dev smoke.
