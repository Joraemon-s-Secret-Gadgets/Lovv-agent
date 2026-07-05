# Task 10.2 Result: AWS Runtime Adapter Boundary

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 10.2 starts the live AWS integration boundary without coupling graph
business logic to boto3 imports, credentials, or global clients.

The implementation now provides a lazy boto3 client factory, Bedrock Runtime
client wiring, AWS-backed repository/tool assembly, a Bedrock embedding adapter,
and a Bedrock Converse runtime wrapper. Unit tests use mocked clients only.

## Completed Scope

- Added lazy boto3 client factory that creates AWS clients only at harness/app
  runtime.
- Extended `AwsClientProvider` to create S3 Vector, DynamoDB, and Bedrock
  Runtime clients from the same injected factory.
- Added AWS runtime assembly that wires configured clients into:
  - `S3VectorRepository`
  - `DynamoDbRepository`
  - `DestinationSearchTool`
  - `DynamoLookupTool`
  - optional Bedrock embedding adapter
  - optional Bedrock Converse runtime
- Implemented Bedrock embedding adapter for live query embedding generation.
- Added Bedrock Converse runtime wrapper that injects the configured model id.
- Added mocked harness tests for client creation, adapter assembly, embedding,
  and Converse runtime behavior.
- Added optional AWS smoke test guard. It is skipped by default and uses
  `gpt-oss-120b` as the default smoke-test LLM model when enabled.
- Added `boto3` as the live AWS SDK dependency through `uv`.

## Changed Files

```text
src/lovv_agent/adapters/__init__.py
src/lovv_agent/adapters/aws_clients.py
src/lovv_agent/adapters/aws_runtime.py
src/lovv_agent/adapters/bedrock_converse.py
src/lovv_agent/adapters/boto3_clients.py
src/lovv_agent/adapters/embeddings.py
tests/test_harness.py
tests/test_aws_smoke.py
docs/tasks/results/TASK10_SUBTASK02_RESULT.md
pyproject.toml
uv.lock
```

## Verification

Focused verification:

```powershell
uv run pytest tests/test_harness.py tests/test_destination_search.py tests/test_config.py
uv run pytest tests/test_aws_smoke.py
```

Result:

```text
38 passed
1 skipped
```

Full verification:

```powershell
uv run pytest
```

Result:

```text
185 passed, 1 skipped
```

## Notes and Constraints

- No real AWS call is made by default.
- `tests/test_aws_smoke.py` runs only when `LOVV_ENABLE_AWS_SMOKE=1`.
- Runtime config remains non-secret; real credentials must come from the AWS
  environment/profile chain.
- `gpt-oss-120b` is used only as the optional smoke-test default model, not as a
  fixed model in the implementation spec.
- The project still does not import boto3 at package import time.
- `boto3` is now declared as a project dependency so live AWS smoke/runtime
  execution can create real clients when the environment is configured.
