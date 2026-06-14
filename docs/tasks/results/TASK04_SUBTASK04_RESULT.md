# Task 4.4 Result: Final Item Detail Enrichment and Warning Policy

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 4.4 now defines DynamoDB detail lookup as a final item enrichment helper,
not as a Candidate Evidence package-time detail lookup.

Candidate Evidence keeps lightweight attraction candidates, fallback signals,
and audit fields. DynamoDB detail lookup is delayed until Planner has selected
the concrete itinerary place items that need user-facing wording or API
packaging support.

## Completed Scope

- Added `DynamoDbRepository.get_detail_item`.
- Added `DynamoLookupTool.enrich_final_places`.
- Added standalone `enrich_final_places` helper under `dynamo_lookup.py`.
- Added `DetailEnrichmentResult`.
- Added `DetailEnrichmentWarning`.
- Added DynamoDB AttributeValue deserialization for detail `GetItem` responses.
- Added warning policies for:
  - missing `ddb_pk` or `ddb_sk`,
  - DynamoDB detail lookup failure,
  - missing DynamoDB `Item`.
- Kept broad candidate, reserve, and scoring-stage detail lookup out of the
  default path. Callers pass only final placed attraction items.
- Kept `DestinationSearchTool` free of DynamoDB detail reads.

## Changed Files

```text
src/lovv_agent/repositories/dynamodb.py
src/lovv_agent/tools/dynamo_lookup.py
src/lovv_agent/tools/destination_search.py
src/lovv_agent/tools/__init__.py
tests/test_destination_search.py
docs/tasks/results/TASK04_SUBTASK04_RESULT.md
```

## Spec Alignment Checklist

- Candidate Evidence does not generate user-facing natural-language reasons:
  done.
- Candidate Evidence does not call DynamoDB detail lookup for primary/reserve
  package construction: done.
- Final placed itinerary items can be enriched through DynamoDB `PK`/`SK`:
  done.
- Missing `ddb_pk`/`ddb_sk` creates warning and `details=null`: done.
- DynamoDB failures create warning and do not crash the graph boundary: done.
- Missing DynamoDB detail item produces warning and `details=null`: done.
- Detail data is converted from DynamoDB AttributeValue shape to plain Python
  values: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_destination_search.py -k "enrich or warning"
```

Result:

```text
5 passed, 19 deselected
```

Full DestinationSearch tests:

```powershell
uv run pytest tests/test_destination_search.py
```

Result:

```text
24 passed
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
87 passed
```

## Notes and Constraints

- The helper is intentionally conservative: failures never remove the placed
  item, but they leave `details=None` and emit a warning.
- Planner or a later explanation step must treat `details=None` as insufficient
  detail evidence and avoid overclaiming facts.
- `미식·노포` remains an external link/CTA theme in the current phase. The
  helper is for placed attraction items, not restaurant discovery.
