# Task 4.2 Result: Attraction Search Filter and Candidate Normalization

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 4.2 added attraction-only S3 Vector request construction and raw vector
record normalization for `DestinationSearchTool`.

The implementation keeps city scoring, festival seed lookup, and DynamoDB
rehydration out of scope. It only builds the attraction search payload, calls
the injected S3 Vector repository, and normalizes returned attraction records.

## Completed Scope

- Added `DestinationSearchTool.search_candidates`.
- Added `AttractionCandidate`.
- Added `build_attraction_search_request`.
- Added `build_attraction_filter`.
- Added `normalize_attraction_candidate`.
- Added S3 Vector response record extraction helper.
- Added attraction-only filter enforcement:
  - `entity_type == attraction`
  - optional `city_id`
  - optional single active `theme` matched through `theme_tags == theme`
- Added current non-place theme handling:
  - `미식·노포` does not trigger S3 Vector place search,
  - festival labels do not trigger general place search.
- Added configurable `top_k` handling:
  - call argument wins when provided,
  - otherwise injected `SearchBudgetSettings.per_theme_attraction_top_k` is used.
- Added chunk-key to stable `place_id` normalization.
- Added `prune_cities` for allowed-city restriction and searchable place theme
  AND gate.
- Added tests for search request construction, filter composition, top K policy,
  food-theme exclusion, chunk normalization, metadata `place_id` override,
  city pruning, and non-attraction rejection.

## Changed Files

```text
src/lovv_agent/tools/destination_search.py
src/lovv_agent/repositories/s3_vectors.py
tests/test_destination_search.py
docs/tasks/results/TASK04_SUBTASK02_RESULT.md
```

## Spec Alignment Checklist

- `search_candidates` builds attraction-only filters: done.
- Optional `city_id` filter is applied: done.
- Optional active `theme` filter is applied as `theme_tags == theme`: done.
- General place search does not use festival or restaurant entity search: done.
- `미식·노포` is excluded from S3 Vector place search: done.
- Chunk keys normalize to stable `place_id`: done.
- `prune_cities` applies allowed city pool and searchable theme AND gate: done.
- `top_k` is not hardcoded globally and comes from call/config: done.
- City scoring remains out of scope: done.
- Festival search remains out of scope for Task 4.3: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_destination_search.py -k "search_candidates or filter or normalize"
```

Result:

```text
8 passed, 11 deselected
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

- The request/filter structure now follows the `destination_search_tool.md`
  S3 Vector payload contract: `queryVector`, `topK`, `returnMetadata`,
  `returnDistance`, and `$eq`/`$and` metadata filters.
- DynamoDB festival seed/fixed-city lookup helpers are left for Task 4.3.
- Primary-only detail rehydration and warning policy are left for Task 4.4.
