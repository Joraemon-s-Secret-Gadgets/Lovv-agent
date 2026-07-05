# Task 5.1 Result: Place and City Scoring

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 5.1 implements deterministic ScoringTool logic for attraction place scores
and city ranking scores.

The implementation remains pure Python. It does not call AWS, LLMs, retrieval,
candidate quota selection, or itinerary generation.

## Completed Scope

- Added `ScoringTool.score_place`.
- Added `ScoringTool.score_city`.
- Added standalone `score_place`, `score_city`, and `haversine_distance`.
- Added `PlaceScoreResult`, `ScoreBreakdown`, and `CityScoreResult`.
- Implemented place score components:
  - raw similarity,
  - soft similarity,
  - theme match bonus,
  - metadata completeness quality score,
  - local distance penalty.
- Implemented city score breakdown:
  - `semantic_evidence`,
  - `theme_coverage`,
  - `theme_balance`,
  - `scale_correction`,
  - `candidate_sufficiency`,
  - `distance_penalty`,
  - `congestion_penalty`.
- Kept restaurant and festival entities outside scoring in the current phase.
- Accepted congestion and user-distance signals as inputs only.

## Changed Files

```text
src/lovv_agent/tools/scoring.py
tests/test_scoring.py
docs/tasks/results/TASK05_SUBTASK01_RESULT.md
```

## Spec Alignment Checklist

- `score_place` is deterministic: done.
- `score_city` is deterministic: done.
- Score breakdown includes all required fields: done.
- Restaurant and festival candidates are not scored in the current phase: done.
- Congestion/visitor signals are accepted as inputs, not fetched internally:
  done.
- Primary/reserve quota selection remains out of scope for Task 5.1:
  preserved.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_scoring.py
```

Result:

```text
7 passed
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
94 passed
```

## Notes and Constraints

- `ScoringTool` computes audit fields only. These score values must remain
  internal and must not be copied verbatim into user-facing explanation text.
- Candidate quota, title deduplication, soft max relaxation, and reserve
  selection are intentionally left for Task 5.2.
