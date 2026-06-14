# Task 8.5 Result: Grounded Explanation Generation

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 8.5 adds grounded Planner explanation generation.

Planner now selects public recommendation reasons from
`candidate_reason_claims` only when the claim is public eligible, its required
place ids are present in the final itinerary, and the text does not expose raw
score/top-K style internals. When a placed item has a detail overview, Planner
can attach that short grounded overview to the reason.

## Completed Scope

- Added grounded recommendation reason selection.
- Added conservative fallback reason when no claim is safe to publish.
- Added public-safe itinerary flow reason.
- Added `PlannerExplanationAudit` with reason refs, flow refs, and hidden
  internal notes.
- Added tests for overview use, missing required place ids, internal term
  blocking, and public-safe flow text.

## Changed Files

```text
src/lovv_agent/agents/planner.py
tests/test_planner.py
docs/tasks/results/TASK08_SUBTASK05_RESULT.md
```

## Verification

```powershell
uv run pytest tests/test_planner.py -k "explanation or recommendation_reason"
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

- `cleaned_raw_query` and `soft_preference_query` are currently present in
  Candidate Evidence input, not as direct fields on the Candidate Evidence
  Package consumed by Planner. The current implementation therefore promotes
  already-grounded `candidate_reason_claims` and placed item overviews.
- Raw scores, ranking formulas, and top-K mechanics remain excluded from public
  explanation text.
