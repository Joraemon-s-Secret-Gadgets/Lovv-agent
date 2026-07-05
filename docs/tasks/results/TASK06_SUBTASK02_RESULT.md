# Task 6.2 Result: Candidate Evidence Attraction Orchestration

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 6.2 connects non-festival Candidate Evidence modes to retrieval, scoring,
city ranking, and primary/reserve candidate selection.

The implementation uses injected tools, so tests do not perform AWS calls.
Candidate Evidence now builds a valid internal package for `city_discovery` and
`anchored_place_search`, while keeping final DynamoDB detail enrichment out of
this node.

## Completed Scope

- Added `CandidateEvidenceAgent.run`.
- Called attraction retrieval once per searchable place theme.
- Merged duplicate vector hits by stable `place_id`.
- Applied searchable theme AND gate through `DestinationSearchTool.prune_cities`.
- Scored survived candidates with `ScoringTool`.
- Ranked cities with deterministic city scoring.
- Selected primary and reserve candidates with `CandidateSelectionHelper`.
- Built lightweight recommended/reserve place payloads without `details`.
- Built valid packages for `ok`, `insufficient_candidates`, and no-city
  fallback paths.
- Enforced anchored city isolation even when a search tool returns another city.

## Changed Files

```text
src/lovv_agent/agents/candidate_evidence.py
tests/test_candidate_evidence.py
docs/tasks/results/TASK06_SUBTASK02_RESULT.md
```

## Spec Alignment Checklist

- City discovery uses retrieval, scoring, and candidate selection helpers:
  done.
- Anchored search applies a fixed city filter and does not mix another city:
  done.
- Candidate Evidence passes lightweight candidates only: done.
- Candidate Evidence does not call final detail enrichment: done.
- Package validates for `ok` and `insufficient_candidates`: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_candidate_evidence.py -k "city_discovery or anchored"
```

Result:

```text
8 passed, 6 deselected
```

Candidate Evidence test suite:

```powershell
uv run pytest tests/test_candidate_evidence.py
```

Result:

```text
14 passed
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
118 passed
```

## Notes and Constraints

- Festival-seeded discovery still returns a temporary internal error package
  until Task 6.3 implements the festival seed gate.
- Query embedding generation remains outside this subtask; callers inject the
  already-built query vector.
- Final DynamoDB detail enrichment remains Planner-owned after final placement.
