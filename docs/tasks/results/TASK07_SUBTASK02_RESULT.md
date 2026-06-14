# Task 7.2 Result: Festival Date Policy

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 7.2 adds date normalization and the initial festival verification policy.

Selected festival candidates now produce `FestivalVerification` payloads. A
festival is `confirmed` only when the normalized start date year matches the
request `travelYear`; trip applicability is recalculated against the current
`travelMonth`.

## Completed Scope

- Added `verify_festival_candidate`.
- Added `normalize_festival_date`.
- Normalized `event_start_date`/`eventstartdate` and
  `event_end_date`/`eventenddate`.
- Applied initial `confirmed` policy: `year(start_date) == travelYear`.
- Recalculated month applicability from start/end date range.
- Returned `placeable` only for confirmed and applicable festivals.
- Added tests for date formats, confirmed, outdated, unknown, range overlap,
  and agent-level verification tuple output.

## Changed Files

```text
src/lovv_agent/agents/festival_verifier.py
tests/test_festival_verifier.py
docs/tasks/results/TASK07_SUBTASK02_RESULT.md
```

## Verification

```powershell
uv run pytest tests/test_festival_verifier.py -k "date or confirmed or applicability"
```

Result:

```text
8 passed, 2 deselected
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
139 passed
```

## Notes and Constraints

- Official web verification is still out of scope.
- Cache key and cache adapter behavior remain Task 7.3.
