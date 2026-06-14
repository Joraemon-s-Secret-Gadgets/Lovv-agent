# Task 5.2 Result: Candidate Selection Quota and Audit

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 5.2 implements deterministic primary/reserve attraction candidate
selection after scoring.

The helper applies title deduplication first, fills minimum searchable theme
quota, applies soft max quota, relaxes the soft max only when primary slots
would otherwise remain unfilled, and records quota audit fields for Candidate
Evidence.

## Completed Scope

- Added `CandidateSelectionHelper.select_primary_with_theme_quotas`.
- Added standalone `select_primary_with_theme_quotas`.
- Added `candidate_budgets_for_trip`.
- Added `SelectionCandidate` and `CandidateSelectionResult`.
- Implemented trip candidate budgets:
  - `daytrip`: primary 6, reserve 4,
  - `2d1n`: primary 10, reserve 8,
  - `3d2n`: primary 14, reserve 10,
  - `4d3n` and `5d4n`: primary 18, reserve 12.
- Implemented `strip + casefold` title deduplication before primary selection.
- Implemented `theme_min_quota = floor(primary_budget / theme_count * 0.6)`.
- Implemented `theme_max_quota = ceil(primary_budget / 2)`.
- Added coverage audit fields for quota shortfall, soft max relaxation,
  deduplicated titles, and unfilled primary slots.

## Changed Files

```text
src/lovv_agent/tools/candidate_selection.py
tests/test_candidate_selection.py
docs/tasks/results/TASK05_SUBTASK02_RESULT.md
```

## Spec Alignment Checklist

- Title dedup runs before primary selection: done.
- Minimum searchable theme quota is filled first: done.
- Soft max quota prevents single-theme dominance where possible: done.
- Relaxation is audited when needed: done.
- Reserve candidates remain internal fallback candidates: done.
- Selection helper does not call AWS, LLMs, scoring, or Planner logic:
  preserved.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_candidate_selection.py
```

Result:

```text
6 passed
```

Task 5 combined tests:

```powershell
uv run pytest tests/test_scoring.py tests/test_candidate_selection.py
```

Result:

```text
13 passed
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
100 passed
```

## Notes and Constraints

- Quota applies to primary candidates only. Reserve candidates are built from
  remaining title-deduplicated candidates by score order.
- `assigned_theme` and `_assigned_theme` are internal audit fields. They should
  not be treated as public explanation text.
