# Task 2.2 Result: Raw/Soft Query and Unsupported Condition Extraction

> Completion Date: 2026-06-14  
> Responsible Agent: Codex  
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`  
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 2.2 added conservative natural-language handling to the Intent Agent.

The implementation still treats structured API input as the source of truth. It
does not infer or overwrite `country`, `travelMonth`, `tripType`,
`destinationId`, canonical `themes`, or `includeFestivals` from
`naturalLanguageQuery`.

## Completed Scope

- Added `NaturalLanguageExtraction`.
- Added `extract_natural_language_query`.
- Added short-query skip behavior using the configured default threshold of `5` characters.
- Added deterministic raw query preservation for searchable travel intent.
- Added deterministic soft preference extraction for atmosphere/preference phrases.
- Added unsupported condition separation for:
  - lodging price / reservation availability
  - real-time crowding
  - real-time opening status
  - parking guarantees
  - weather / fallback requests
- Added handoff notes for explicit structured-field conflict signals without overriding API values.
- Updated Intent normalization to pass extracted raw/soft/unsupported fields into `CandidateEvidenceInput`.
- Added Task 2.2 tests in `tests/test_intent.py`.

## Changed Files

```text
src/lovv_agent/agents/intent.py
tests/test_intent.py
docs/tasks/results/TASK02_SUBTASK02_RESULT.md
```

## Spec Alignment Checklist

- `cleaned_raw_query` preserves searchable travel intent: done.
- `soft_preference_query` captures atmosphere/preference terms: done.
- Unsupported live or unavailable conditions are separated into `unsupported_conditions`: done.
- Empty or shorter-than-threshold natural language skips extraction and proceeds from structured input: done.
- Short natural language sets raw/soft/unsupported fields empty: done.
- Natural-language conflicts with structured core fields are recorded as handoff notes, not used to override API values: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_intent.py -k "raw_soft or unsupported or conflict"
```

Result:

```text
tests/test_intent.py ....                                                [100%]

4 passed, 12 deselected
```

Full current test suite:

```powershell
uv run pytest
```

Result:

```text
tests/test_config.py ........                                            [ 22%]
tests/test_import_skeleton.py ...                                        [ 31%]
tests/test_intent.py ................                                    [ 77%]
tests/test_schemas.py ........                                           [100%]

35 passed
```

## Notes and Constraints

- This is a conservative deterministic extractor, not the final LLM structured-output adapter.
- Structured-output enforcement and bounded retry remain Task 2.3 scope.
- Conflict signals are recorded in `handoff_notes`; structured API fields remain unchanged.
