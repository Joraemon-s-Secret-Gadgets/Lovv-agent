# Lovv AgentCore V1 Production Readiness Tasks

Source spec: `docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md`

Source Kiro task plan: `.kiro/specs/agentcore-v1-production-readiness/tasks.md`

## Scope

Make AgentCore v1 production-readiness repeatable and reviewable before a real
deployment. This task plan preserves the single `LovvAgentV1` Runtime, keeps
`src/lovv_agent` as canonical source, and treats `app/LovvAgentV1/lovv_agent` as
the vendored AgentCore runtime copy.

This plan does not authorize production model changes, live deployment, AgentCore
Memory, Gateway, credentials, account-local files, or `/recommendations` schema
changes.

## Task Order

| Order | Task | Depends On | Requirements |
| --- | --- | --- | --- |
| 1 | Add a canonical/vendored runtime parity check | None | 3.1, 3.2, 3.3 |
| 2 | Add a live model availability check | None | 1.1, 1.2, 1.3 |
| 3 | Add per-node structured-output smoke coverage | 2 | 2.1, 2.2, 2.3 |
| 4 | Write the readiness result report | 1, 2, 3, 6, 7 | 1.4, 2.4, 3.3, 4.3 |
| 5 | Prepare docs migration handoff | None | 6.1, 6.2, 6.3, 6.4, 6.5, 6.6 |
| 6 | Run local verification gates | 1, 3 | 4.1 |
| 7 | Run AgentCore validation gates | 1, 2, 3, 6 | 4.1, 4.2, 4.3, 4.4 |
| 8 | Review production model ID decision | 2, 3, 4, 7 | 1.3, 5.1, 5.5 |

## Tasks

### Task 1: Canonical/Vendored Runtime Parity Check

**Purpose:** Detect drift between tested source and the AgentCore runtime copy
before deployment gates run.

**Implementation notes:**

- Implement either a focused pytest test or a script that compares
  `src/lovv_agent` against `app/LovvAgentV1/lovv_agent`.
- Print mismatched relative paths on failure.
- Exclude cache files and package metadata.

**Acceptance criteria:**

- [ ] Relevant files under `src/lovv_agent` and `app/LovvAgentV1/lovv_agent` are compared.
- [ ] Mismatches fail the check with relative paths.
- [ ] Parity result can be included in the readiness report.

**Verification:**

- [ ] `$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest -q`

**Requirements:** 3.1, 3.2, 3.3

### Task 2: Live Model Availability Check

**Purpose:** Verify configured AgentCore v1 model IDs against live Bedrock
availability before production defaults are accepted.

**Implementation notes:**

- Read configured model IDs through `RuntimeConfig.from_env()`.
- Check `us-east-1` Bedrock foundation models and inference profiles.
- Classify each configured LLM node model as available, profile-backed,
  unavailable, or environment-blocked.
- Avoid writing credentials, account IDs, or raw AWS auth details.

**Acceptance criteria:**

- [ ] `us-east-1` foundation models and inference profiles are queried.
- [ ] Each configured `LOVV_*_LLM_MODEL_ID` receives an availability classification.
- [ ] Unavailable models are not promoted to production defaults.

**Verification:**

- [ ] `aws bedrock list-foundation-models --region us-east-1`
- [ ] `aws bedrock list-inference-profiles --region us-east-1`

**Requirements:** 1.1, 1.2, 1.3

### Task 3: Per-Node Structured-Output Smoke Coverage

**Purpose:** Prove that configured models can satisfy the structured-output
schema paths used by the current graph.

**Implementation notes:**

- Exercise Intent, Candidate Evidence reason-claim, and Planner explanation
  structured-output paths with compact fixtures.
- Record Supervisor as configured-but-unused while deterministic Supervisor
  remains the v1 default.
- Report node, model ID, pass/fail status, and schema error class.

**Acceptance criteria:**

- [ ] Intent structured output is smoke-tested.
- [ ] Candidate Evidence reason-claim structured output is smoke-tested.
- [ ] Planner explanation structured output is smoke-tested.
- [ ] Supervisor model config is reported as unused in v1 instead of faking a call.
- [ ] Schema failures identify node, model ID, error type, and retry exhaustion.

**Verification:**

- [ ] `$env:LOVV_ENABLE_AWS_SMOKE='1'`
- [ ] `$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest tests/test_aws_smoke.py -q`

**Requirements:** 2.1, 2.2, 2.3

### Task 4: Readiness Result Report

**Purpose:** Produce the durable execution evidence for a production-readiness
review.

**Target file:**

- `docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md`

**Report contents:**

- Branch
- Timestamp
- Region
- Configured model IDs
- Model availability
- Structured-output smoke results
- Parity result
- Pytest and compileall result
- AgentCore validate result
- AgentCore dry-run result
- Blockers
- Release recommendation

**Acceptance criteria:**

- [ ] The report records checked model IDs, region, command used, timestamp, and blockers.
- [ ] The report states whether AgentCore v1 model routing is ready for deployment dry-run review.
- [ ] The report includes parity check result.
- [ ] The report includes AgentCore target and stack name when dry-run succeeds.

**Verification:**

- [ ] `rg "LovvAgentV1|us-east-1|pytest|compileall|agentcore validate|dry-run" docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md`

**Requirements:** 1.4, 2.4, 3.3, 4.3

### Task 5: Docs Migration Handoff

**Purpose:** Make the approved Kiro working spec available in durable repo docs
without guessing paths or scope.

**Implementation notes:**

- Create or preserve
  `.kiro/specs/agentcore-v1-production-readiness/docs-migration-request.md`.
- Name exact source Kiro files and target `docs/` paths.
- Include conversion rules, non-goals, verification commands, and approval
  boundary.

**Acceptance criteria:**

- [ ] Source files are named as `.kiro/specs/agentcore-v1-production-readiness/requirements.md`, `design.md`, and `tasks.md`.
- [ ] Target spec path is `docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md`.
- [ ] Target task path is `docs/tasks/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_TASKS.md`.
- [ ] Runtime evidence target is `docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md`.
- [ ] Conversion preserves requirements, architecture decisions, boundaries, commands, open questions, and task acceptance criteria.
- [ ] Docs conversion does not start live AWS checks or deployment commands.

**Verification:**

- [ ] `rg "LovvAgentV1|production readiness|src/lovv_agent|app/LovvAgentV1|AgentCore Memory|Gateway" docs/specs/v1/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_SPEC.md docs/tasks/LOVV_AGENTCORE_V1_PRODUCTION_READINESS_TASKS.md`

**Requirements:** 6.1, 6.2, 6.3, 6.4, 6.5, 6.6

### Task 6: Local Verification Gates

**Purpose:** Prove local behavior before treating the readiness package as
reviewable.

**Acceptance criteria:**

- [ ] Full pytest passes or any skip/blocker is explained.
- [ ] Compileall passes for source, tests, and AgentCore runtime copy.
- [ ] Code or docs issues found by checks are fixed or recorded.

**Verification:**

- [ ] `$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest -q`
- [ ] `$env:UV_CACHE_DIR='.cache\\uv'; uv run python -m compileall src tests app\\LovvAgentV1`

**Requirements:** 4.1

### Task 7: AgentCore Validation Gates

**Purpose:** Check AgentCore config and dry-run metadata as part of the same
readiness gate.

**Acceptance criteria:**

- [ ] `agentcore validate --json` is run or the exact CLI blocker is recorded.
- [ ] `agentcore deploy --target v1 --dry-run --json` is run or the exact environment blocker is recorded.
- [ ] Successful dry-run result records target name and stack name.
- [ ] Any failure blocks deployment until resolved or explicitly accepted.

**Verification:**

- [ ] `agentcore validate --json`
- [ ] `$env:UV_CACHE_DIR='D:\\bootcamp\\workspace\\project\\03_final\\04_Lovv-agent\\.cache\\uv'; agentcore deploy --target v1 --dry-run --json`

**Requirements:** 4.1, 4.2, 4.3, 4.4

### Task 8: Production Model ID Decision

**Purpose:** Decide final v1 production model IDs only after availability and
structured-output compatibility are known.

**Implementation notes:**

- If all live checks pass, keep or update final v1 model IDs only after owner
  confirmation.
- If a model is unavailable or schema-incompatible, document candidate
  replacements and leave production config unchanged until approved.

**Acceptance criteria:**

- [ ] One `LovvAgentV1` Runtime is preserved.
- [ ] Unavailable or schema-incompatible models do not become production defaults.
- [ ] Secrets, credentials, local account files, and live PII payloads are not committed.

**Verification:**

- [ ] `rg "LOVV_.*_LLM_MODEL_ID|LovvAgentV1|agentcore/agentcore.json" docs agentcore -S`

**Requirements:** 1.3, 5.1, 5.5

## Checkpoint

- [ ] Parity check exists and reports mismatched relative paths.
- [ ] Model availability check records `us-east-1` results or environment blockers.
- [ ] Structured-output smoke covers Intent, Candidate Evidence reason-claim, and Planner explanation.
- [ ] Full pytest passes or blockers are recorded.
- [ ] Compileall passes or blockers are recorded.
- [ ] AgentCore validation is attempted and result recorded.
- [ ] AgentCore dry-run is attempted and result recorded.
- [ ] Readiness report exists only after implementation or verification has actually run.
