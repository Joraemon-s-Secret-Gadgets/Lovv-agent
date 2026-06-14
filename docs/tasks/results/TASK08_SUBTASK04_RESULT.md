# Task 8.4 Result: Minimal Planner Validation Helper

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 8.4 adds a deliberately minimal Planner validation helper.

The helper does not attempt broad itinerary policy judgment. It checks only the
current explicit safety rules: attraction items must use Candidate Evidence
place ids, restaurant items must not be generated, and festival items must be
confirmed/applicable/placeable according to Festival Verifier output.

## Completed Scope

- Added `validate_planner_output`.
- Added structured validation result fields:
  - `status`
  - `is_valid`
  - `valid`
  - `errors`
  - `retry_action`
- Connected normal Planner output to the validation helper.
- Added tests for grounded output, ungrounded attraction, named restaurant, and
  unconfirmed festival placement.

## Changed Files

```text
src/lovv_agent/agents/planner.py
src/lovv_agent/tools/validation.py
tests/test_planner.py
docs/tasks/results/TASK08_SUBTASK04_RESULT.md
```

## Verification

```powershell
uv run pytest tests/test_planner.py -k validation
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

## Notes and Constraints

- The validation helper is intentionally not a full itinerary quality checker.
- Planner does not rewrite invalid output in this subtask; the structured
  result is prepared for Supervisor retry/fallback handling.
