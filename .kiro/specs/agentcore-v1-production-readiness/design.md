# Design Document

## Overview

AgentCore v1 production readiness should be implemented as a small validation
and reporting layer around the existing code. The current architecture already
has the important runtime boundaries:

- `src/lovv_agent/config.py` parses non-secret runtime settings and per-node LLM
  model overrides.
- `src/lovv_agent/adapters/aws_runtime.py` builds per-node Bedrock Converse
  runtimes while keeping one Bedrock client and one AgentCore Runtime.
- `src/lovv_agent/harness.py` injects separate Intent, Candidate Evidence, and
  Planner runtimes into the LangGraph nodes.
- `src/lovv_agent/agentcore_entrypoint.py` normalizes AgentCore/HTTP wrappers
  into the public `/recommendations` payload.
- `agentcore/agentcore.json` declares the `LovvAgentV1` CodeZip runtime and its
  non-secret environment selectors.

The design adds repeatable checks and durable evidence without changing the
recommendation graph. It also adds a docs-migration handoff so another Kiro run
or docs-writing skill can move the approved Kiro content into `docs/` with
stable paths and boundaries.

## Architecture

```text
Operator / CI
  -> pytest and compileall
  -> parity check
       -> compare src/lovv_agent to app/LovvAgentV1/lovv_agent
  -> model availability check
       -> Bedrock list-foundation-models
       -> Bedrock list-inference-profiles
  -> structured-output smoke
       -> Intent runtime
       -> Candidate Evidence runtime
       -> Planner runtime
  -> AgentCore validation
       -> agentcore validate --json
       -> agentcore deploy --target v1 --dry-run --json
  -> readiness report
  -> optional docs migration
       -> docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md
       -> docs/tasks/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_TASKS.md
       -> docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md
```

## Components and Interfaces

### Readiness Report

Create one dated Markdown report under `docs/tasks/results/`, for example:

```text
docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md
```

The report should contain:

- timestamp and branch
- checked region
- current configured model IDs
- model availability result
- per-node structured-output smoke result
- parity check result
- pytest and compileall result
- AgentCore validate and dry-run result
- blockers and final release recommendation

### Model Availability Check

Implementation options:

- Add a script under `scripts/` that uses boto3.
- Or implement an opt-in pytest module that is skipped unless
  `LOVV_ENABLE_AWS_SMOKE=1`.

The check should inspect configured model IDs from `RuntimeConfig.from_env()` and
classify each model ID:

```text
available_foundation_model
available_inference_profile
not_found
not_checked_environment_blocker
```

No AWS credentials, account IDs, or raw tokens should be written to the report.

### Structured Output Smoke

The smoke should call the same adapters used by `build_live_harness()`, but it
can use minimal node-specific payloads rather than a full recommendation request
when that keeps diagnosis clearer.

Minimum node coverage:

- Intent: API-shaped recommendation payload plus short conversation context.
- Candidate Evidence reason claim: one compact candidate package fixture.
- Planner explanation: one compact itinerary fixture.

The Supervisor model ID is allowed to be configured, but the current Supervisor
is deterministic. The report should label this as unused in v1 rather than
forcing a fake call.

### Parity Check

The parity check should compare all relevant files mirrored into the AgentCore
runtime package:

```text
src/lovv_agent/**/*.py
src/lovv_agent/prompts/*.md
app/LovvAgentV1/lovv_agent/**/*.py
app/LovvAgentV1/lovv_agent/prompts/*.md
```

The check should ignore cache files and package metadata. A script or pytest
test is acceptable, but it must print mismatched relative paths on failure.

### AgentCore Gate

The gate keeps using the repo's existing commands:

```powershell
agentcore validate --json
$env:UV_CACHE_DIR='D:\\bootcamp\\workspace\\project\\03_final\\04_Lovv-agent\\.cache\\uv'; agentcore deploy --target v1 --dry-run --json
```

The absolute `UV_CACHE_DIR` is intentional on this Windows setup because a prior
dry-run hit access-denied behavior with the user-global uv cache.

### Docs Migration Handoff

Create a prompt-style handoff file inside the Kiro spec directory:

```text
.kiro/specs/agentcore-v1-production-readiness/docs-migration-request.md
```

That file is the request to give to Kiro or a docs-writing skill. It should name
the exact source Kiro files, target docs files, conversion rules, non-goals, and
verification commands.

Migration mapping:

| Kiro source | Docs target | Rule |
| --- | --- | --- |
| `requirements.md` + `design.md` | `docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md` | Merge into one durable spec with objective, requirements, design, commands, boundaries, success criteria, and open questions. |
| `tasks.md` | `docs/tasks/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_TASKS.md` | Preserve task order, acceptance criteria, verification commands, and requirement references. |
| implementation evidence | `docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md` | Create only after checks are executed or explicitly record blockers. |

The migration handoff must say that docs conversion is a documentation movement
only. It must not run live AWS checks, update model IDs, deploy AgentCore, or
change runtime code unless the user asks for implementation execution.

## Data Models

The report can use plain Markdown tables. If a script emits intermediate JSON,
use this shape:

```json
{
  "region": "us-east-1",
  "models": [
    {
      "node": "intent",
      "modelId": "openai.gpt-oss-120b-1:0",
      "availability": "available_foundation_model",
      "structuredOutput": "passed"
    }
  ],
  "parity": {
    "status": "passed",
    "mismatchedFiles": []
  },
  "agentcore": {
    "validate": "passed",
    "dryRun": "passed",
    "targetName": "v1",
    "stackName": "AgentCore-LovvAgentCore-v1"
  }
}
```

## Error Handling

- Missing AWS credentials should produce an environment-blocker result, not a
  false model failure.
- Unavailable model IDs should block production default updates.
- Schema validation failures should include node and model ID, but not prompt
  payloads or raw model output unless explicitly redacted.
- AgentCore CLI absence should be recorded with command and executable error.
- Parity mismatches should fail fast before live deployment gates.
- Docs migration should fail review if it drops scope boundaries, verification
  commands, or open questions from the Kiro source.

## Testing Strategy

Local required checks:

```powershell
$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest -q
$env:UV_CACHE_DIR='.cache\\uv'; uv run python -m compileall src tests app\\LovvAgentV1
```

Optional live checks:

```powershell
$env:LOVV_ENABLE_AWS_SMOKE='1'
$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest tests/test_aws_smoke.py -q
```

AgentCore checks:

```powershell
agentcore validate --json
$env:UV_CACHE_DIR='D:\\bootcamp\\workspace\\project\\03_final\\04_Lovv-agent\\.cache\\uv'; agentcore deploy --target v1 --dry-run --json
```

## Boundaries

- Always preserve the single `LovvAgentV1` Runtime.
- Always keep `src/lovv_agent` as canonical source.
- Always sync or verify `app/LovvAgentV1/lovv_agent` before deploy checks.
- Ask before changing production model IDs in `agentcore/agentcore.json`.
- Ask before adding dependencies or changing CI.
- Never commit credentials, local `agentcore/aws-targets.json`, raw PII, or
  prompt/model-response dumps.
- Never enable AgentCore Memory or Gateway in this readiness spec.
- Never treat docs migration as approval to run live deployment commands.
