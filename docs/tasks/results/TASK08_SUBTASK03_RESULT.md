# Task 8.3 Result: Gourmet Link/CTA and Placeholder Policy

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 8.3 implements the current gourmet handling policy.

When Candidate Evidence marks `미식·노포` as an `external_link_themes`
requirement, Planner no longer tries to retrieve or invent restaurants. It
adds a selected-city `foodSearch` link and a meal-choice placeholder with
`placeId=null`.

## Completed Scope

- Added deterministic food search link builder.
- Added Planner gourmet-theme detection from `coverage_audit.external_link_themes`.
- Added selected-city `foodSearch` link packaging in Planner internals.
- Added meal placeholder item with `source=placeholder` and `placeId=null`.
- Added regression tests to prevent named restaurant generation.

## Changed Files

```text
src/lovv_agent/agents/planner.py
src/lovv_agent/tools/links.py
tests/test_planner.py
docs/tasks/results/TASK08_SUBTASK03_RESULT.md
```

## Verification

```powershell
uv run pytest tests/test_planner.py -k "gourmet or food or placeholder"
```

Result:

```text
3 passed
```

Compile check:

```powershell
uv run python -m compileall src tests
```

Result: passed.

## Notes and Constraints

- The link builder does not call external services.
- Planner still does not query restaurant tables or generate named restaurant
  recommendations from model knowledge.
- Response Packager will later convert the `foodSearch` payload into the public
  `/recommendations` response shape.
