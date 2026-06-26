# AgentCore V1 FM Routing Result

> Completion Date: 2026-06-22
> Branch: `agentcore-v1-migration`
> Related Issues: #1, #2, #3, #4, #5, #6, #7
> Source Spec: `docs/specs/v1/LOVV_AGENTCORE_V1_FM_ROUTING_SPEC.md`
> Task Plan: `docs/tasks/LOVV_AGENTCORE_V1_FM_ROUTING_TASKS.md`

## Summary

The AgentCore V1 FM routing work is implemented locally. The single
`LovvAgentV1` Runtime remains intact while Intent, Candidate Evidence, Planner,
and Supervisor now have optional per-agent LLM model configuration with
`LOVV_LLM_MODEL_ID` as the global fallback.

Gateway remains deferred as an additive phase. S3 Vector and DynamoDB retrieval
remain in-process.

## Completed Scope

- Created GitHub task issues #1 through #7 in
  `Joraemon-s-Secret-Gadgets/Lovv-agent`.
- Added a durable task plan for AgentCore V1 FM routing.
- Completed the missing Task 10.5 memory-safe summary boundary and result doc.
- Added per-agent model and adapter env parsing.
- Added central model/adapter resolver helpers.
- Built per-node Converse runtime invokers in the AWS runtime bundle.
- Injected Intent, Candidate Evidence, and Planner runtime invokers separately
  in the harness.
- Synced canonical source changes to `app/LovvAgentV1/lovv_agent/`.
- Added AgentCore config env vars for per-agent V1 model routing.
- Added focused config, harness, memory-safety, and AgentCore config tests.

## Changed Files

```text
agentcore/agentcore.json
app/LovvAgentV1/lovv_agent/adapters/aws_runtime.py
app/LovvAgentV1/lovv_agent/config.py
app/LovvAgentV1/lovv_agent/harness.py
app/LovvAgentV1/lovv_agent/state.py
docs/specs/v1/LOVV_AGENTCORE_V1_FM_ROUTING_SPEC.md
docs/tasks/LOVV_AGENTCORE_V1_FM_ROUTING_TASKS.md
docs/tasks/results/AGENTCORE_V1_FM_ROUTING_RESULT.md
docs/tasks/results/TASK10_SUBTASK05_RESULT.md
src/lovv_agent/adapters/aws_runtime.py
src/lovv_agent/config.py
src/lovv_agent/harness.py
src/lovv_agent/state.py
tests/test_config.py
tests/test_harness.py
```

## Verification

```powershell
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_harness.py -k "memory_safe" -q
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest tests/test_config.py tests/test_harness.py -q
$env:UV_CACHE_DIR='.cache\uv'; uv run pytest -q
$env:UV_CACHE_DIR='.cache\uv'; uv run python -m compileall src tests app\LovvAgentV1
agentcore validate --json
$env:UV_CACHE_DIR='D:\bootcamp\workspace\project\03_final\04_Lovv-agent\.cache\uv'; agentcore deploy --target v1 --dry-run --json
```

Results:

```text
memory_safe: 1 passed, 12 deselected
focused config/harness: 25 passed
full pytest: 212 passed, 1 skipped, 2 subtests passed
compileall: passed
agentcore validate: {"success":true}
agentcore deploy dry-run: {"success":true,"targetName":"v1","stackName":"AgentCore-LovvAgentCore-v1"}
```

## Notes

- A first dry-run attempt failed because the CDK synth child process tried to
  use the user-global uv cache and hit a Windows access-denied error.
- Re-running with an absolute workspace-local `UV_CACHE_DIR` succeeded.
- Pytest emitted a cache warning for `.pytest_cache` access, but test execution
  completed successfully.
- Final production model IDs still require the separate live availability and
  structured-output smoke decision described in the source spec.
