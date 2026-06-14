# Task 4.3 Result: Festival Seed and Fixed-City Lookup Helper

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 4.3 added the `DynamoLookupTool` festival seed lookup path used before
attraction retrieval when `includeFestivals=true`.

The implementation treats festivals as a city-seeding channel, not as attraction
search or city scoring records. It applies the month/theme gate, supports an
optional fixed city, and returns structured clarification signals for the known
no-candidate cases.

## Completed Scope

- Added `DynamoDbRepository.query_festival_candidates`.
- Added `DynamoLookupTool.search_festival_city_seeds`.
- Added standalone `search_festival_city_seeds` and
  `normalize_festival_candidate` helpers under `dynamo_lookup.py`.
- Added `FestivalCandidate` and `FestivalSeedResult`.
- Added festival theme-pool normalization that excludes festival-only labels.
- Added month matching through `festival.month == travelMonth`.
- Added non-festival travel theme OR matching:
  - `festival.theme in theme_pool`,
  - `festival.assigned_theme in theme_pool`, or
  - any `festival.theme_tags in theme_pool`.
- Added `entity_type == festival` to the DynamoDB festival seed query request.
- Added anchored-city filtering for `anchored_place_search`.
- Kept `DestinationSearchTool` scoped to S3 Vector attraction search.
- Added fallback signals:
  - `no_required_theme_for_festival_seed`
  - `no_festival_city_seed`
  - `no_festival_in_anchor_city`
- Added DynamoDB AttributeValue normalization for festival records.

## Changed Files

```text
src/lovv_agent/repositories/dynamodb.py
src/lovv_agent/tools/dynamo_lookup.py
src/lovv_agent/tools/destination_search.py
src/lovv_agent/tools/__init__.py
tests/test_destination_search.py
docs/tasks/results/TASK04_SUBTASK03_RESULT.md
```

## Spec Alignment Checklist

- Festival helper runs before attraction search when festival inclusion is
  requested: done at tool boundary.
- Festival seed lookup uses `festival.month == travelMonth`: done.
- Festival seed lookup applies non-festival theme OR matching: done.
- Festival seed lookup checks `theme`, `assigned_theme`, and `theme_tags`:
  done.
- Festival seed query includes `entity_type=festival`: done.
- `festival_event`/festival-only labels are not used as travel themes: done.
- Empty non-festival theme pool returns `no_required_theme_for_festival_seed`:
  done.
- Empty city discovery seed returns `no_festival_city_seed`: done.
- Empty anchored city lookup returns `no_festival_in_anchor_city`: done.
- Festival candidates remain outside attraction retrieval/scoring: done.
- Festival year verification remains out of scope for this task: preserved.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_destination_search.py -k "festival_seed or fixed_city"
```

Result:

```text
6 passed, 11 deselected
```

Full DestinationSearch tests:

```powershell
uv run pytest tests/test_destination_search.py
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
82 passed
```

## Notes and Constraints

- The DynamoDB query expression is intentionally mockable and minimal. A future
  live adapter may map the same logical request to a production table/GSI shape.
- City ranking and final festival verification are still handled by later
  stages, not by this helper.
- Final item detail enrichment and warning policy are handled by Task 4.4.
