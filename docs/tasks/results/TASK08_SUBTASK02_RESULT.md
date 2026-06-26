# Task 8.2 Result: Planner Festival Overlay

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 8.2 adds the Planner festival overlay policy.

Planner now places only Festival Verifier outputs that are confirmed,
applicable to the trip, placeable, and linked to the selected festival
candidate from Candidate Evidence. Tentative, unknown, outdated, inapplicable,
or otherwise unplaceable festival candidates are not inserted into the
itinerary.

## Completed Scope

- Added verified festival overlay generation.
- Added selected-festival provenance checks.
- Added planner validation metadata for placed and skipped festivals.
- Added user notice behavior when festival candidates are skipped.
- Added anchored-mode regression coverage to keep the selected city stable.

## Changed Files

```text
src/lovv_agent/agents/planner.py
tests/test_planner.py
docs/tasks/results/TASK08_SUBTASK02_RESULT.md
```

## Verification

```powershell
uv run pytest tests/test_planner.py -k festival
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

- Planner still treats attractions as the baseline schedule and overlays
  confirmed festivals after the first attraction slot.
- Festival schedule details are not invented; the item only uses verifier
  fields already present in the verified payload.
- Gourmet link/CTA policy remains Task 8.3.
