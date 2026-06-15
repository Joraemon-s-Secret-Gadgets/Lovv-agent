# Hotfix Result: Primary Capacity-Aware City Selection

> Completion Date: 2026-06-15
> Responsible Agent: Codex
> Change Type: Urgent recommendation-flow correction
> Affected Runtime: `Lovv-agent` and AgentCore vendored `MyAgent/lovv_agent`

## Summary

This hotfix prevents city discovery from always forwarding the city with the
highest city score when that city does not have enough primary attractions to
fill the requested itinerary.

Candidate Evidence now derives the required attraction count from `tripType`
and checks ranked cities in score order. The first city whose primary place pool
can fill the itinerary becomes `selected_city`. If no ranked city satisfies the
requirement, the original rank-1 city remains selected and Planner produces a
reduced itinerary from the available primary places.

The final hotfix policy intentionally does not use `reserve_places` for city
sufficiency or Planner backfill. Reserve candidates remain in the internal
Candidate Evidence Package for audit and future policy changes only.

## Final Policy

| Condition | Behavior |
| --- | --- |
| Rank-1 city has enough primary places | Keep rank-1 city |
| Rank-1 city is short, later city has enough primary places | Select the first sufficient city in score order |
| Every ranked city is short | Keep rank-1 city and return an `insufficient_candidates` package |
| Anchored place search | Never change the user-fixed city |
| Planner attraction pool | Use `recommended_places` only |
| Reserve places | Do not use for sufficiency or itinerary backfill |

Required primary place counts are aligned with the current Planner slot
templates.

| `tripType` | Required primary places |
| --- | ---: |
| `daytrip` | 3 |
| `2d1n` | 5 |
| `3d2n` | 8 |
| `4d3n` | 11 |
| `5d4n` | 14 |

## Completed Scope

- Added a shared `tripType` to itinerary-place-count mapping.
- Evaluated primary selection results for every ranked city before final city
  selection.
- Added score-order fallback to the next city with sufficient primary places.
- Preserved the rank-1 city when no city can fill the itinerary.
- Preserved fixed-city behavior for `anchored_place_search`.
- Kept festival-seeded city discovery inside the festival seed city pool.
- Changed Candidate Evidence status to use primary itinerary capacity rather
  than the larger candidate-selection budget.
- Added city ranking audit fields:
  - `available_place_count`
  - `required_place_count`
  - `itinerary_sufficient`
  - `selected`
- Added fallback audit fields:
  - `selected_city_rank`
  - `city_reselected_for_itinerary_capacity`
- Explicitly recorded that reserve places are not considered for itinerary
  capacity.
- Kept Planner placement limited to `recommended_places`.
- Synchronized the business-logic changes into the AgentCore vendored package.

## Changed Files

Primary implementation and tests:

```text
src/lovv_agent/tools/candidate_selection.py
src/lovv_agent/agents/candidate_evidence.py
src/lovv_agent/agents/planner.py
tests/test_candidate_evidence.py
tests/test_planner.py
docs/tasks/results/HOTFIX_20260615_PRIMARY_CAPACITY_CITY_SELECTION_RESULT.md
```

AgentCore vendored runtime synchronization:

```text
../myagent/app/MyAgent/lovv_agent/tools/candidate_selection.py
../myagent/app/MyAgent/lovv_agent/agents/candidate_evidence.py
../myagent/app/MyAgent/lovv_agent/agents/planner.py
```

## Verification

Full `Lovv-agent` unit test suite:

```powershell
uv run --python 3.12 python -m unittest discover -s tests
```

Result:

```text
Ran 198 tests
OK (skipped=1)
```

Focused tests against the AgentCore vendored `lovv_agent` package:

```powershell
$env:PYTHONPATH="D:\skn_aicamp\5th_final_project\myagent\app\MyAgent;D:\skn_aicamp\5th_final_project\Lovv-agent"
uv run --project Lovv-agent --python 3.12 python -m unittest tests.test_candidate_evidence tests.test_planner
```

Result:

```text
Ran 53 tests
OK
```

Additional verification:

- Python compile checks passed for both package locations.
- Scoped `git diff --check` passed for all hotfix files.
- The three synchronized runtime files are identical between `Lovv-agent` and
  `myagent/app/MyAgent/lovv_agent`.
- Ruff was not available in the current uv environment and was not run.

## Test Cases Added or Updated

- A rank-1 city with insufficient primary places is skipped when rank 2 can
  fill the requested itinerary.
- An anchored city remains selected even when its primary pool is insufficient.
- Planner does not backfill a primary shortage with reserve places.
- Existing Candidate Evidence, Planner, graph, schema, and response tests remain
  green.

## Notes and Constraints

- `reserve_places` are still generated and serialized. This hotfix only removes
  them from the current selection and placement policy.
- The city score order itself is not changed. Capacity acts as a selection gate
  applied after deterministic city ranking.
- Anchored mode prioritizes the user's fixed city over itinerary completeness.
- When every city is insufficient, the response remains usable but contains a
  reduced itinerary and the existing insufficient-candidate notice.
- Festival inclusion does not change the capacity rule. Candidate Evidence
  evaluates only cities that survived the festival seed restriction.
- This hotfix does not add route optimization, opening-hour validation, or
  distance-aware itinerary placement.
