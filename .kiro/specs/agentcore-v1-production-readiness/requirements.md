# Requirements Document

## Introduction

Lovv Agent already has a Python 3.12 LangGraph recommendation workflow and a
single `LovvAgentV1` AgentCore Runtime wrapper. Recent FM-routing work added
per-agent model configuration, local tests, compile checks, `agentcore validate`,
and AgentCore dry-run verification.

This spec covers the remaining modification surface: make AgentCore v1
production-readiness repeatable and reviewable before a real deployment. The
work must validate model/profile availability in `us-east-1`, smoke-test the
structured-output path used by each LLM node, preserve the canonical
`src/lovv_agent` to `app/LovvAgentV1/lovv_agent` parity boundary, and document
the final release decision. The Kiro spec must also be easy to migrate into the
repo's durable `docs/` surfaces when the user approves the migration.

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

#### Acceptance Criteria

1. WHEN the validation is run THEN it SHALL query `us-east-1` foundation models
   and inference profiles using AWS CLI or boto3.
2. WHEN a configured `LOVV_*_LLM_MODEL_ID` is present THEN it SHALL be marked as
   available, unavailable, or requiring cross-region inference profile review.
3. WHEN a model ID is unavailable THEN the implementation SHALL not update
   `agentcore/agentcore.json` to that model as a production default.
4. WHEN validation completes THEN a repo-local report SHALL record checked model
   IDs, region, command used, timestamp, and any blockers.

### Requirement 2: Per-Node Structured Output Smoke Coverage

**User Story:** As a Lovv developer, I want each LLM-using graph node to be
smoke-tested with its configured model, so that model availability alone is not
mistaken for schema compatibility.

#### Acceptance Criteria

1. WHEN the smoke command runs THEN it SHALL exercise the Intent, Candidate
   Evidence reason-claim, and Planner explanation structured-output paths.
2. WHEN Supervisor model config is present THEN it SHALL be recorded as
   configured-but-unused for the current deterministic Supervisor path.
3. WHEN a node response fails schema validation THEN the smoke result SHALL
   identify the node, model ID, error type, and whether retry exhausted.
4. WHEN all configured node smokes pass THEN the report SHALL state that
   AgentCore v1 model routing is ready for deployment dry-run review.

### Requirement 3: Canonical/Vendored Runtime Parity

**User Story:** As a maintainer, I want automated parity checks between
canonical source and the vendored AgentCore runtime copy, so that deployment
artifacts do not drift from tested source.

#### Acceptance Criteria

1. WHEN parity verification runs THEN it SHALL compare relevant files under
   `src/lovv_agent` and `app/LovvAgentV1/lovv_agent`.
2. WHEN a mismatch exists THEN the check SHALL fail with the mismatched relative
   paths.
3. WHEN parity passes THEN the result SHALL be included in the readiness report.
4. WHEN source changes are made for this spec THEN the vendored runtime copy
   SHALL be synced before verification is considered complete.

### Requirement 4: AgentCore Deployment Gate

**User Story:** As a release owner, I want the AgentCore validation and dry-run
commands to be part of the same readiness gate, so that code, config, and
deployment metadata are checked together.

#### Acceptance Criteria

1. WHEN local validation runs THEN the suite SHALL include pytest, compileall,
   AgentCore config validation, and AgentCore v1 dry-run where the CLI is
   available.
2. WHEN the AgentCore CLI is unavailable THEN the report SHALL record the exact
   command attempted and the environment blocker.
3. WHEN `agentcore deploy --target v1 --dry-run --json` succeeds THEN the
   report SHALL include target name and stack name.
4. WHEN validation fails THEN deployment SHALL be treated as blocked until the
   blocker is resolved or explicitly accepted.

### Requirement 5: Scope Boundaries

**User Story:** As the project owner, I want this work to stay focused on
AgentCore v1 readiness, so that it does not reopen already-settled architecture
decisions.

#### Acceptance Criteria

1. WHEN implementing this spec THEN it SHALL preserve one `LovvAgentV1` Runtime.
2. WHEN implementing this spec THEN it SHALL not change the `/recommendations`
   request or response schema.
3. WHEN implementing this spec THEN it SHALL not move S3 Vector or DynamoDB
   retrieval behind Gateway.
4. WHEN implementing this spec THEN it SHALL not enable AgentCore Memory.
5. WHEN implementing this spec THEN it SHALL not commit secrets, AWS credentials,
   local account files, or live payloads containing PII.

### Requirement 6: Docs Migration Readiness

**User Story:** As a maintainer, I want the Kiro spec to include an explicit
handoff request for docs migration, so that Kiro or a docs-writing skill can
move the approved content into `docs/` without guessing target paths or scope.

#### Acceptance Criteria

1. WHEN docs migration is requested THEN the source files SHALL be the Kiro
   files under `.kiro/specs/agentcore-v1-production-readiness/`.
2. WHEN docs migration is requested THEN the target spec path SHALL be
   `docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md`.
3. WHEN docs migration is requested THEN the target task path SHALL be
   `docs/tasks/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_TASKS.md`.
4. WHEN docs migration is requested THEN runtime execution evidence SHALL be
   written to `docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md`.
5. WHEN converting Kiro content to docs THEN the migrator SHALL preserve
   requirements, architecture decisions, boundaries, commands, open questions,
   and task acceptance criteria.
6. WHEN converting Kiro content to docs THEN the migrator SHALL not start live
   AWS checks or deployment commands unless the user explicitly asks to execute
   implementation tasks.

## Commands

Use these commands as the baseline validation surface.

```powershell
$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest -q
$env:UV_CACHE_DIR='.cache\\uv'; uv run python -m compileall src tests app\\LovvAgentV1
agentcore validate --json
$env:UV_CACHE_DIR='D:\\bootcamp\\workspace\\project\\03_final\\04_Lovv-agent\\.cache\\uv'; agentcore deploy --target v1 --dry-run --json
aws bedrock list-foundation-models --region us-east-1
aws bedrock list-inference-profiles --region us-east-1
```

## Project Structure

```text
src/lovv_agent/                      Canonical LangGraph package
app/LovvAgentV1/lovv_agent/          Vendored AgentCore runtime package copy
agentcore/agentcore.json             AgentCore v1 runtime metadata
scripts/                             Local and live operator commands
tests/                               Unit, integration, and optional AWS smoke tests
docs/specs/                          Existing durable specs
docs/tasks/                          Existing implementation task breakdowns
docs/tasks/results/                  Execution and verification reports
.kiro/specs/                         Kiro requirements, design, and task specs
```

## Code Style

Python code should keep the existing typed, injectable style:

```python
def build_live_harness(
    *,
    config: RuntimeConfig | None = None,
    client_factory: AwsClientFactory | None = None,
) -> LovvLangGraphHarness:
    resolved_config = RuntimeConfig.from_env() if config is None else config
    factory = client_factory or create_boto3_client_factory(
        profile_name=resolved_config.aws.profile_name,
    )
    adapters = build_aws_runtime_adapters(
        client_factory=factory,
        config=resolved_config,
    )
    return build_harness(config=resolved_config, adapters=adapters)
```

Key conventions:

- Keep environment reads at application boundaries.
- Keep AWS clients injectable for tests.
- Raise explicit schema/config errors instead of returning partial live state.
- Keep repo docs and commands Windows/PowerShell friendly.

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
3. Should live smoke commands be implemented as a dedicated script, pytest marker,
   or both?
4. Should the Kiro spec remain as the working source after migration, or should
   `docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md` become the source
   of truth?
