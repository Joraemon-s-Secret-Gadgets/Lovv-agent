# Task 3.2 Result: Routing Decisions and Clarification Stop

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 3.2 added the deterministic Supervisor routing boundary.

The implementation decides the next node from the fulfilled matrix, request
festival flag, and worker status. It also stops the graph at `END_WAIT_USER`
when any worker asks for clarification.

## Completed Scope

- Added route node constants:
  - `candidate_evidence_agent`
  - `festival_verifier_agent`
  - `planner_agent`
  - `response_packager`
  - `END_WAIT_USER`
- Added `SupervisorRouteDecision`.
- Added `SupervisorRouter` as the swappable deterministic routing boundary.
- Added `decide_supervisor_route`.
- Added request-level festival skip handling.
- Added clarification stop handling.
- Added Candidate Evidence status handling:
  - `ok`
  - `insufficient_candidates`
  - `no_candidate`
  - `error`
- Added a Planner safety gate for `ok` and `insufficient_candidates`.
- Added routing tests for normal, festival-included, festival-skipped,
  clarification, safe insufficient, and unsafe insufficient paths.

## Changed Files

```text
src/lovv_agent/agents/supervisor.py
tests/test_supervisor.py
docs/tasks/results/TASK03_SUBTASK02_RESULT.md
```

## Spec Alignment Checklist

- Deterministic Supervisor remains the MVP source of truth: done.
- Routing logic is exposed through a swappable boundary: done.
- `needs_clarification=true` routes to `END_WAIT_USER`: done.
- Clarification blocks Festival Verifier and Planner: done.
- `includeFestivals=false` marks `festival=N/A`: done.
- Routing order is evidence, festival, planning: done.
- Safe `insufficient_candidates` may proceed to Planner: done.
- Unsafe `insufficient_candidates` does not call Planner: done.
- Live LLM Supervisor routing was not added: done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_supervisor.py -k "routing or clarification"
```

Result:

```text
7 passed, 8 deselected
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
58 passed
```

## Notes and Constraints

- Graph compilation remains out of scope for Task 3.2.
- Planner validation retry-limit behavior is intentionally left for Task 3.3.
- The optional LLM Supervisor swap remains a post-baseline E2E experiment, not
  MVP routing behavior.
