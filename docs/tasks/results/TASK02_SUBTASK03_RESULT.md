# Task 2.3 Result: Structured Output Adapter and Fallback

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 2.3 added a provider-SDK-free Bedrock Converse structured-output boundary
and Intent Agent validation/fallback handling.

The implementation does not call AWS, does not select a concrete model ID, and
does not initialize credentials at import time. Runtime callers inject a
Converse-compatible callable, which keeps local tests and future AgentCore
harnesses deterministic.

## Completed Scope

- Added JSON Schema text-format request construction for Intent structured output.
- Added a generic structured-output adapter boundary in `bedrock_converse.py`.
- Added structured output extraction from:
  - direct JSON strings
  - direct structured-output mappings
  - Converse message content JSON blocks
  - tool-use style `input` payloads
- Added bounded retry behavior for parse/schema/provider boundary failures.
- Added `validate_intent_agent_output`.
- Added `invoke_intent_structured_output`.
- Added safe clarification fallback when all structured-output attempts fail.
- Added core-field override protection so LLM output cannot change structured API values.
- Added Task 2.3 tests with injected fake runtimes.
- Added fixture-like Intent normalization scenarios translated from `langgraph_app/fixtures/mock_agent_inputs.py` into the current MVP API contract:
  - autumn festival chat
  - anchored map marker
  - gourmet/healing festival chat

## Changed Files

```text
src/lovv_agent/adapters/bedrock_converse.py
src/lovv_agent/agents/intent.py
tests/test_intent.py
docs/tasks/results/TASK02_SUBTASK03_RESULT.md
```

## Spec Alignment Checklist

- Adapter supports schema-style structured output request construction: done.
- Adapter supports tool-output style structured payload extraction: done.
- Malformed output is retried within a bounded limit: done.
- Final parse/schema failure returns safe clarification/fallback: done.
- Malformed output is not passed downstream as graph state: done.
- Every accepted Intent LLM output passes local schema/business validation: done.
- Structured API core fields are not overwritten by LLM output: done.
- No concrete model ID or AWS credential is introduced: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_intent.py -k "structured_output or schema_failure"
```

Result:

```text
tests/test_intent.py .....                                               [100%]

5 passed, 16 deselected
```

Additional fixture-like scenario check:

```powershell
uv run pytest tests/test_intent.py -k "fixture_like or structured_output or schema_failure"
```

Result:

```text
tests/test_intent.py ........                                            [100%]

8 passed, 16 deselected
```

Full current test suite:

```powershell
uv run pytest
```

Result:

```text
tests/test_config.py ........                                            [ 20%]
tests/test_import_skeleton.py ...                                        [ 27%]
tests/test_intent.py ........................                            [ 81%]
tests/test_schemas.py ........                                           [100%]

43 passed
```

## Notes and Constraints

- This task adds the adapter boundary and validation/retry behavior, not a live Bedrock client.
- Production Bedrock client construction remains a future runtime/harness responsibility.
- The current Intent structured-output schema covers structural constraints; local validation still enforces business rules that JSON Schema should not own.
- This change is intentionally left uncommitted for user review.
