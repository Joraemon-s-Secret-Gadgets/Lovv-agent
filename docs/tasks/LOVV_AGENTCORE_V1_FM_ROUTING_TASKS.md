# Lovv AgentCore V1 FM Routing Tasks

Source spec: `docs/specs/LOVV_AGENTCORE_V1_FM_ROUTING_SPEC.md`

GitHub issue tracker: `Joraemon-s-Secret-Gadgets/Lovv-agent`

## Scope

Implement per-agent Foundation Model routing inside the existing single
`LovvAgentV1` AgentCore Runtime. Gateway remains a later additive phase and
must not change `/recommendations` behavior.

## Task Order

| Order | Issue | Task | Depends On |
| --- | --- | --- | --- |
| 1 | #1 | Audit and complete Task 10.5 memory-safe summary boundary | None |
| 2 | #2 | Break FM routing spec into implementation tasks | None |
| 3 | #3 | Add per-agent LLM routing config and resolver | #2 |
| 4 | #4 | Wire per-agent runtime invokers into harness | #3 |
| 5 | #5 | Sync deployment config and vendored runtime | #3, #4 |
| 6 | #6 | Verify FM routing and AgentCore validation gates | #3, #4, #5 |
| 7 | #7 | Preserve Gateway additive-phase boundaries | #2 through #6 |

## Task 1: Task 10.5 Memory-Safe Summary Boundary

**GitHub issue:** #1

**Purpose:** Ensure future AgentCore Memory handoff has an explicit opt-in
summary boundary that excludes raw evidence, full Candidate Evidence Package,
raw web content, secrets, and PII.

**Files likely touched:**

- `src/lovv_agent/state.py`
- `app/LovvAgentV1/lovv_agent/state.py`
- `tests/test_harness.py`
- `docs/tasks/results/TASK10_SUBTASK05_RESULT.md`

**Acceptance criteria:**

- [ ] Safe summary contains trace IDs and compact request/serving summaries.
- [ ] Safe summary excludes raw evidence and full in-run package payloads.
- [ ] Memory persistence remains disabled by default.

**Verification:**

- [ ] `$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_harness.py -k "memory_safe"`

## Task 2: FM Routing Task Breakdown

**GitHub issue:** #2

**Purpose:** Make the V1 FM routing spec executable through ordered,
issue-linked tasks.

**Files likely touched:**

- `docs/tasks/LOVV_AGENTCORE_V1_FM_ROUTING_TASKS.md`

**Acceptance criteria:**

- [ ] Each task has dependencies, acceptance criteria, and verification.
- [ ] Tasks link to GitHub issues #1 through #7.
- [ ] Boundaries preserve single Runtime and defer Gateway.

**Verification:**

- [ ] `rg "AgentCore V1|FM routing|GitHub issue" docs/tasks docs/specs -S`

## Task 3: Per-Agent LLM Routing Config

**GitHub issue:** #3

**Purpose:** Add model/adapter override config per LLM-using node while keeping
`LOVV_LLM_MODEL_ID` as the global fallback.

**Files likely touched:**

- `src/lovv_agent/config.py`
- `app/LovvAgentV1/lovv_agent/config.py`
- `tests/test_config.py`

**Acceptance criteria:**

- [ ] Env vars for Intent, Candidate Evidence, Planner, and Supervisor model IDs parse.
- [ ] Agent-specific model IDs override `LOVV_LLM_MODEL_ID`.
- [ ] Unset agent-specific values fall back to `LOVV_LLM_MODEL_ID`.
- [ ] Unsupported node names fail with clear config errors.

**Verification:**

- [ ] `$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_config.py`

## Task 4: Runtime Invoker Wiring

**GitHub issue:** #4

**Purpose:** Build and inject per-agent Converse runtime invokers without
splitting the AgentCore Runtime.

**Files likely touched:**

- `src/lovv_agent/adapters/aws_runtime.py`
- `src/lovv_agent/harness.py`
- `app/LovvAgentV1/lovv_agent/adapters/aws_runtime.py`
- `app/LovvAgentV1/lovv_agent/harness.py`
- `tests/test_harness.py`

**Acceptance criteria:**

- [ ] Intent uses the intent runtime/model.
- [ ] Candidate Evidence reason-claim generation uses the candidate runtime/model.
- [ ] Planner explanation generation uses the planner runtime/model.
- [ ] Existing single-model fallback behavior remains supported.

**Verification:**

- [ ] `$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_harness.py tests/test_config.py`

## Task 5: Deployment Config And Vendored Runtime Sync

**GitHub issue:** #5

**Purpose:** Keep AgentCore deployment artifacts aligned with canonical source.

**Files likely touched:**

- `agentcore/agentcore.json`
- `app/LovvAgentV1/lovv_agent/`
- `tests/test_config.py`

**Acceptance criteria:**

- [ ] `agentcore/agentcore.json` keeps `LOVV_AWS_REGION=us-east-1`.
- [ ] Agent-specific model env vars are non-secret and present for V1 routing.
- [ ] `agentCoreGateways` remains empty.
- [ ] Vendored app runtime files match canonical source changes.

**Verification:**

- [ ] `$env:UV_CACHE_DIR='.cache\uv'; uv run python -m compileall src tests app\LovvAgentV1`
- [ ] `agentcore validate --json`

## Task 6: Verification Gates

**GitHub issue:** #6

**Purpose:** Prove local behavior and record any environment-dependent AgentCore
validation limits.

**Acceptance criteria:**

- [ ] Focused config/harness tests pass.
- [ ] Full pytest passes or any skip/blocker is explained.
- [ ] Compileall passes.
- [ ] AgentCore validation result is recorded.

**Verification:**

- [ ] `$env:UV_CACHE_DIR='.cache\uv'; uv run pytest`
- [ ] `$env:UV_CACHE_DIR='.cache\uv'; uv run python -m compileall src tests app\LovvAgentV1`
- [ ] `agentcore validate --json`
- [ ] `$env:UV_CACHE_DIR='.cache\uv'; agentcore deploy --target v1 --dry-run --json` when available

## Task 7: Gateway Additive-Phase Boundary

**GitHub issue:** #7

**Purpose:** Preserve Gateway as a later tool-exposure phase instead of a V1
runtime split or retrieval rewrite.

**Acceptance criteria:**

- [ ] V1 keeps one `LovvAgentV1` Runtime.
- [ ] S3 Vector and DynamoDB retrieval remain in-process.
- [ ] Gateway open questions stay documented for later selection.
- [ ] `/recommendations` contract remains unchanged.

**Verification:**

- [ ] `rg "Gateway|agentCoreGateways|Runtime split|us-east-1" docs agentcore -S`

## Checkpoint

- [ ] All focused tests pass.
- [ ] Full test suite passes.
- [ ] Compileall passes.
- [ ] AgentCore validation is attempted and result recorded.
