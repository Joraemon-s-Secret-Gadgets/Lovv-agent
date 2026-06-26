# Lovv AgentCore V1 Production Readiness SPEC

> Status: Draft for review
> Date: 2026-06-22
> Repository: `Lovv-agent`
> Source Kiro spec: `.kiro/specs/agentcore-v1-production-readiness/`
> Runtime: `LovvAgentV1`
> Region baseline: `us-east-1`

## Objective

Make AgentCore v1 production-readiness repeatable and reviewable before a real
deployment.

The work validates model/profile availability in `us-east-1`, smoke-tests the
structured-output path used by each LLM node, preserves the canonical
`src/lovv_agent` to `app/LovvAgentV1/lovv_agent` parity boundary, and records
the final release decision in a durable report.

This spec is a documentation migration of the approved Kiro working spec. It
does not approve live AWS checks, production model updates, AgentCore
deployment, or runtime code changes by itself.

## Current Structure

```text
src/lovv_agent/                      Canonical LangGraph package
app/LovvAgentV1/lovv_agent/          Vendored AgentCore runtime package copy
agentcore/agentcore.json             AgentCore v1 runtime metadata
scripts/                             Local and live operator commands
tests/                               Unit, integration, and optional AWS smoke tests
docs/specs/                          Durable specs
docs/tasks/                          Durable implementation task breakdowns
docs/tasks/results/                  Execution and verification reports
.kiro/specs/                         Kiro requirements, design, and task specs
```

Relevant existing runtime boundaries:

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

## Assumptions

1. `LovvAgentV1` remains one AgentCore Runtime.
2. LangGraph recommendation behavior and the `/recommendations` public contract
   are already implemented and should not be redesigned in this work.
3. `src/lovv_agent` is the canonical package source, while
   `app/LovvAgentV1/lovv_agent` is the vendored AgentCore runtime copy.
4. Region baseline stays `us-east-1`.
5. Memory, Gateway, credentials, payments, evaluators, online eval configs, and
   policy engines stay out of scope unless a later spec explicitly adds them.
6. Live AWS checks require caller-provided AWS credentials and must not embed
   secrets in repo files.
7. `.kiro/specs/...` is the working specification surface, while `docs/specs`,
   `docs/tasks`, and `docs/tasks/results` are the durable repo documentation
   surfaces.

## Requirements

### Requirement 1: Live Model Availability Decision

**User Story:** As a Lovv operator, I want the AgentCore v1 model IDs to be
verified against live Bedrock availability before deployment, so that runtime
startup does not fail because a configured model or inference profile is absent.

**Acceptance Criteria:**

1. When validation is run, it queries `us-east-1` foundation models and
   inference profiles using AWS CLI or boto3.
2. When a configured `LOVV_*_LLM_MODEL_ID` is present, it is marked as available,
   unavailable, or requiring cross-region inference profile review.
3. When a model ID is unavailable, the implementation does not update
   `agentcore/agentcore.json` to that model as a production default.
4. When validation completes, a repo-local report records checked model IDs,
   region, command used, timestamp, and any blockers.

### Requirement 2: Per-Node Structured Output Smoke Coverage

**User Story:** As a Lovv developer, I want each LLM-using graph node to be
smoke-tested with its configured model, so that model availability alone is not
mistaken for schema compatibility.

**Acceptance Criteria:**

1. When the smoke command runs, it exercises the Intent, Candidate Evidence
   reason-claim, and Planner explanation structured-output paths.
2. When Supervisor model config is present, it is recorded as
   configured-but-unused for the current deterministic Supervisor path.
3. When a node response fails schema validation, the smoke result identifies the
   node, model ID, error type, and whether retry exhausted.
4. When all configured node smokes pass, the report states that AgentCore v1
   model routing is ready for deployment dry-run review.

### Requirement 3: Canonical/Vendored Runtime Parity

**User Story:** As a maintainer, I want automated parity checks between
canonical source and the vendored AgentCore runtime copy, so that deployment
artifacts do not drift from tested source.

**Acceptance Criteria:**

1. When parity verification runs, it compares relevant files under
   `src/lovv_agent` and `app/LovvAgentV1/lovv_agent`.
2. When a mismatch exists, the check fails with the mismatched relative paths.
3. When parity passes, the result is included in the readiness report.
4. When source changes are made for this spec, the vendored runtime copy is
   synced before verification is considered complete.

### Requirement 4: AgentCore Deployment Gate

**User Story:** As a release owner, I want the AgentCore validation and dry-run
commands to be part of the same readiness gate, so that code, config, and
deployment metadata are checked together.

**Acceptance Criteria:**

1. When local validation runs, the suite includes pytest, compileall, AgentCore
   config validation, and AgentCore v1 dry-run where the CLI is available.
2. When the AgentCore CLI is unavailable, the report records the exact command
   attempted and the environment blocker.
3. When `agentcore deploy --target v1 --dry-run --json` succeeds, the report
   includes target name and stack name.
4. When validation fails, deployment is treated as blocked until the blocker is
   resolved or explicitly accepted.

### Requirement 5: Scope Boundaries

**User Story:** As the project owner, I want this work to stay focused on
AgentCore v1 readiness, so that it does not reopen already-settled architecture
decisions.

**Acceptance Criteria:**

1. Implementing this spec preserves one `LovvAgentV1` Runtime.
2. Implementing this spec does not change the `/recommendations` request or
   response schema.
3. Implementing this spec does not move S3 Vector or DynamoDB retrieval behind
   Gateway.
4. Implementing this spec does not enable AgentCore Memory.
5. Implementing this spec does not commit secrets, AWS credentials, local account
   files, or live payloads containing PII.

### Requirement 6: Docs Migration Readiness

**User Story:** As a maintainer, I want the Kiro spec to include an explicit
handoff request for docs migration, so that Kiro or a docs-writing skill can
move the approved content into `docs/` without guessing target paths or scope.

**Acceptance Criteria:**

1. When docs migration is requested, the source files are the Kiro files under
   `.kiro/specs/agentcore-v1-production-readiness/`.
2. When docs migration is requested, the target spec path is
   `docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md`.
3. When docs migration is requested, the target task path is
   `docs/tasks/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_TASKS.md`.
4. When runtime execution evidence exists, it is written to
   `docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md`.
5. When converting Kiro content to docs, the migrator preserves requirements,
   architecture decisions, boundaries, commands, open questions, and task
   acceptance criteria.
6. When converting Kiro content to docs, the migrator does not start live AWS
   checks or deployment commands unless the user explicitly asks to execute
   implementation tasks.

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

## Components And Interfaces

### Readiness Report

Create one Markdown report under `docs/tasks/results/`:

```text
docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md
```

The report should contain branch, timestamp, checked region, configured model
IDs, model availability, per-node structured-output smoke result, parity check
result, pytest and compileall result, AgentCore validate and dry-run result,
blockers, and final release recommendation.

Do not create this result report for documentation migration alone. It is an
execution-evidence artifact.

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

The check should ignore cache files and package metadata. A script or pytest test
is acceptable, but it must print mismatched relative paths on failure.

### AgentCore Gate

The gate keeps using the repo's existing commands:

```powershell
agentcore validate --json
$env:UV_CACHE_DIR='D:\\bootcamp\\workspace\\project\\03_final\\04_Lovv-agent\\.cache\\uv'; agentcore deploy --target v1 --dry-run --json
```

The absolute `UV_CACHE_DIR` is intentional on this Windows setup because a prior
dry-run hit access-denied behavior with the user-global uv cache.

### Docs Migration Handoff

The Kiro working spec includes a prompt-style handoff file:

```text
.kiro/specs/agentcore-v1-production-readiness/docs-migration-request.md
```

Migration mapping:

| Kiro source | Docs target | Rule |
| --- | --- | --- |
| `requirements.md` + `design.md` | `docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md` | Merge into one durable spec with objective, requirements, design, commands, boundaries, success criteria, and open questions. |
| `tasks.md` | `docs/tasks/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_TASKS.md` | Preserve task order, acceptance criteria, verification commands, and requirement references. |
| implementation evidence | `docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md` | Create only after checks are executed or explicitly record blockers. |

Docs conversion is a documentation movement only. It must not run live AWS
checks, update model IDs, deploy AgentCore, or change runtime code unless the
user asks for implementation execution.

## Data Model

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

## Commands

Baseline validation surface:

```powershell
$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest -q
$env:UV_CACHE_DIR='.cache\\uv'; uv run python -m compileall src tests app\\LovvAgentV1
agentcore validate --json
$env:UV_CACHE_DIR='D:\\bootcamp\\workspace\\project\\03_final\\04_Lovv-agent\\.cache\\uv'; agentcore deploy --target v1 --dry-run --json
aws bedrock list-foundation-models --region us-east-1
aws bedrock list-inference-profiles --region us-east-1
```

Optional live smoke checks:

```powershell
$env:LOVV_ENABLE_AWS_SMOKE='1'
$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest tests/test_aws_smoke.py -q
```

## Testing Strategy

- Unit tests cover config parsing, resolver behavior, entrypoint payload
  extraction, and parity utilities.
- Focused integration tests cover harness assembly with mocked adapters.
- Optional live smoke tests are opt-in and require AWS credentials.
- AgentCore validation and deploy dry-run are required readiness gates when the
  CLI is installed.
- Docs migration can be verified by checking that the target `docs/specs` and
  `docs/tasks` files contain the same approved scope and boundaries as the Kiro
  source.

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

## Success Criteria

- A readiness report records model/profile availability in `us-east-1`.
- Per-node structured-output smoke results are recorded for all configured LLM
  nodes used by the current graph.
- Canonical/vendored runtime parity is machine-checked.
- Existing local pytest and compile gates pass.
- `agentcore validate --json` and v1 dry-run succeed or have documented
  environment blockers.
- A docs-migration handoff request exists and names exact source and target
  paths.

## Open Questions

1. Which production model IDs should replace the current v1 defaults if
   `openai.gpt-oss-120b-1:0` is unavailable or schema-incompatible?
2. Should the readiness report live in `docs/tasks/results/` only, or should a
   shorter operator-facing summary also be added under `docs/reports/`?
3. Should live smoke commands be implemented as a dedicated script, pytest
   marker, or both?
4. Should the Kiro spec remain as the working source after migration, or should
   `docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md` become the source
   of truth?
