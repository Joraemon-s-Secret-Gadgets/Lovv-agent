# Task 6.1 Result: Candidate Evidence Mode and Theme Split

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 6.1 implements the deterministic Candidate Evidence entry context.

The node now resolves execution mode from `destinationId` and
`includeFestivals`, then splits active themes into searchable attraction themes
and selected-city external-link themes. This prepares the input contract used by
the later retrieval, scoring, festival seed, and package-building subtasks.

## Completed Scope

- Added `CandidateEvidenceAgent.prepare_context`.
- Added `prepare_candidate_evidence_context`.
- Added `resolve_candidate_evidence_mode`.
- Added `split_candidate_themes`.
- Added `CandidateEvidenceContext` and `CandidateThemeSplit`.
- Preserved anchored search when `destinationId` is present, even when
  `includeFestivals=true`.
- Routed `미식·노포` to `external_link_themes` and out of attraction search.
- Ignored legacy festival markers as theme labels at the Candidate Evidence
  boundary.

## Changed Files

```text
src/lovv_agent/agents/candidate_evidence.py
tests/test_candidate_evidence.py
docs/tasks/results/TASK06_SUBTASK01_RESULT.md
```

## Spec Alignment Checklist

- `city_discovery` mode is selected for no anchor and no festival request:
  done.
- `festival_seeded_city_discovery` mode is selected for no anchor and festival
  request: done.
- `anchored_place_search` mode is selected whenever `destinationId` exists:
  done.
- `includeFestivals` remains available in anchored mode: done.
- `미식·노포` is an external-link theme, not a searchable place theme: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_candidate_evidence.py -k "mode or theme_split"
```

Result:

```text
10 passed
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
114 passed
```

## Notes and Constraints

- This subtask does not perform AWS calls, retrieval, scoring, festival seed
  lookup, package construction, or LLM reason-claim generation.
- Candidate Evidence still receives normalized Intent output as its only input;
  the mode/theme split here is a defensive node-boundary contract.
