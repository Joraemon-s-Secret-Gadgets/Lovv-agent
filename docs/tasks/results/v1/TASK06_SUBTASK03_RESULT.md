# Task 6.3 Result: Festival Seed Gate and Fixed-City Festival Lookup

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 6.3 implements the festival-included Candidate Evidence gate.

When `includeFestivals=true`, Candidate Evidence now queries festival seed data
before attraction retrieval. City discovery is restricted to seeded festival
cities, and anchored search requires a matching festival in the fixed city
before any attraction retrieval/scoring runs.

## Completed Scope

- Added injected `dynamo_lookup` dependency to `CandidateEvidenceAgent`.
- Added festival seed lookup before attraction retrieval.
- Used non-festival active theme pool for festival theme matching.
- Returned `no_required_theme_for_festival_seed` when the theme pool is empty.
- Returned `no_festival_city_seed` before retrieval when no seeded city exists.
- Returned `no_festival_in_anchor_city` before retrieval for anchored festival
  misses.
- Restricted festival-included city discovery to seeded city ids before
  attraction scoring.
- Restricted selected festival candidates to the final selected city.
- Added compact `festival_seed_audit`, `festival_candidates`, and
  `selected_festival_candidates` package fields.

## Changed Files

```text
src/lovv_agent/agents/candidate_evidence.py
tests/test_candidate_evidence.py
docs/tasks/results/TASK06_SUBTASK03_RESULT.md
```

## Spec Alignment Checklist

- Festival city seed lookup runs before attraction retrieval: done.
- Seed failure prevents Planner consumption: done.
- Empty theme pool returns `no_required_theme_for_festival_seed`: done.
- Empty city seed returns `no_festival_city_seed`: done.
- Empty anchored festival lookup returns `no_festival_in_anchor_city`: done.
- Festival candidates are not scored as places: preserved.
- `selected_festival_candidates` are limited to final selected city: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_candidate_evidence.py -k "festival_seed or fixed_city_festival"
```

Result:

```text
6 passed, 13 deselected
```

Candidate Evidence test suite:

```powershell
uv run pytest tests/test_candidate_evidence.py
```

Result:

```text
19 passed
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
123 passed
```

## Notes and Constraints

- This subtask only confirms month/theme seed eligibility. Festival date-year
  verification remains Task 7 and must not be started before Task 6 completes.
- Candidate Evidence uses festival seeds to restrict city candidates. It does
  not rerank cities with festival place scores.
- Final DynamoDB detail enrichment remains Planner-owned after final placement.
