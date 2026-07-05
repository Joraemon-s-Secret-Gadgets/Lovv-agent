# Task 2.1 Result: API Input Normalization and Theme Mapping

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 2.1 implemented deterministic Intent Agent normalization for the MVP
`POST /recommendations` request.

The implementation treats structured API fields as the source of truth. It does
not infer `country`, `travelMonth`, `tripType`, `themes`, `destinationId`, or
`includeFestivals` from natural language.

## Completed Scope

- Added `normalize_recommendation_request`.
- Added canonical API theme ID to Candidate Evidence label mapping.
- Added theme grouping:
  - `active_required_themes`
  - `searchable_place_themes`
  - `external_link_themes`
- Added current gourmet handling by keeping `food_local` active while excluding it from attraction search themes.
- Added legacy festival theme normalization to `includeFestivals=true` without adding a festival label to `active_required_themes`.
- Added Candidate Evidence execution mode resolution:
  - `city_discovery`
  - `anchored_place_search`
  - `festival_seeded_city_discovery`
- Added strict structured field validation for entry type, country, year, month, trip type, theme count, destination anchor, include-festival flag, and optional `userLocation`.
- Added `tests/test_intent.py`.

## Changed Files

```text
src/lovv_agent/agents/intent.py
tests/test_intent.py
docs/tasks/results/TASK02_SUBTASK01_RESULT.md
```

## Spec Alignment Checklist

- API core fields are preserved and not inferred from natural language: done.
- `userLocation` is normalized to internal `user_location`: done.
- Canonical theme IDs map to Candidate Evidence labels: done.
- `includeFestivals` controls festival inclusion separately from theme labels: done.
- `destinationId` produces `anchored_place_search`: done.
- `destinationId` and `includeFestivals=true` are compatible: done.
- `destinationId == null` and `includeFestivals=true` produces `festival_seeded_city_discovery`: done.
- Legacy `festival_event` is not treated as an active required travel theme: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_intent.py -k "normalization or theme_mapping"
```

Result:

```text
tests/test_intent.py ...........                                         [100%]

11 passed
```

Full current test suite:

```powershell
uv run pytest
```

Result:

```text
tests/test_config.py ........                                            [ 26%]
tests/test_import_skeleton.py ...                                        [ 36%]
tests/test_intent.py ...........                                         [ 73%]
tests/test_schemas.py ........                                           [100%]

30 passed
```

## Notes and Constraints

- Natural-language raw/soft query extraction is intentionally not implemented in Task 2.1.
- Structured-output adapter and bounded LLM retry are intentionally not implemented in Task 2.1.
- Invalid structured input returns a clarification result instead of raising through the graph boundary.
