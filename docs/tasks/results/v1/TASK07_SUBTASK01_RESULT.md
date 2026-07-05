# Task 7.1 Result: Festival Verifier Input Scope

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 7.1 implements the Festival Verifier input boundary.

The verifier now builds its input only from Candidate Evidence
`selected_festival_candidates`, skips cleanly when `includeFestivals=false`, and
returns a structured no-candidate state when no selected festival candidate is
available.

## Completed Scope

- Added `FestivalVerifierAgent`.
- Added `FestivalVerifierInput`.
- Added `FestivalVerifierResult`.
- Added `build_festival_verifier_input`.
- Preserved the rule that Festival Verifier must not create city seeds, rerank
  cities, or change the selected city.
- Added tests for scope extraction, skip behavior, empty selected candidates,
  and mapping package input.

## Changed Files

```text
src/lovv_agent/agents/festival_verifier.py
tests/test_festival_verifier.py
docs/tasks/results/TASK07_SUBTASK01_RESULT.md
```

## Verification

```powershell
uv run pytest tests/test_festival_verifier.py -k "scope or skip"
```

Result:

```text
4 passed
```

Compile check:

```powershell
uv run python -m compileall src tests
```

Result: passed.

Full current test suite:

```powershell
uv run pytest
```

Result:

```text
133 passed
```

## Notes and Constraints

- Date normalization and confirmed/outdated policy are intentionally left for
  Task 7.2.
- Cache boundary tests are intentionally left for Task 7.3.
