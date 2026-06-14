# Task 6.4 Result: Candidate Evidence Package Audit and Reason Claims

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `Lovv-agent/docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `Lovv-agent/docs/specs/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 6.4 finalizes Candidate Evidence package construction around status,
audits, warnings, and compact Korean `candidate_reason_claims`.

Reason claims are generated only after retrieval, scoring, city selection, and
fallback decisions are already fixed. The optional LLM runtime can compress safe
package summaries into claim candidates, but its output cannot change package
decisions. Schema failure is retried within the configured bound and degrades to
non-public template claims plus a warning.

## Completed Scope

- Added Candidate Evidence reason-claim JSON Schema request builder.
- Added reason-claim output validator.
- Added optional injected structured-output runtime for claim generation.
- Added deterministic template reason claims when no LLM runtime is injected.
- Added schema-failure fallback with warning and non-public template claims.
- Prevented reason claim generation for `no_candidate` and `error` packages.
- Kept raw scores and raw retrieval payload fields out of LLM-visible claim
  summaries.
- Added tests for `ok`, `insufficient_candidates`, `no_candidate`, and `error`
  package behavior.

## Changed Files

```text
src/lovv_agent/agents/candidate_evidence.py
tests/test_candidate_evidence.py
docs/tasks/results/TASK06_SUBTASK04_RESULT.md
```

## Spec Alignment Checklist

- Package validates for `ok`, `insufficient_candidates`, `no_candidate`, and
  `error`: done.
- `needs_clarification` is reserved for user-input-required failures: covered.
- Retrieval, coverage, fallback, and candidate count audit fields are present:
  done.
- `candidate_reason_claims` include `claim_id`, `scope`, `text_ko`,
  `evidence_refs`, `required_place_ids`, and `public_eligible`: done.
- Claim generation cannot change selected city, ranking, quota, status, or
  fallback decisions: done.
- Schema failure is retried and recorded as a warning: done.
- Raw score fields are not copied into claim text or LLM-visible summaries:
  done.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_candidate_evidence.py -k "package or status or audit"
```

Result:

```text
9 passed, 16 deselected
```

Candidate Evidence test suite:

```powershell
uv run pytest tests/test_candidate_evidence.py
```

Result:

```text
25 passed
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
129 passed
```

## Notes and Constraints

- Candidate reason claims are still internal Planner inputs, not final public
  recommendation copy.
- The LLM receives a safe summary without raw score audits or raw retrieval
  payloads.
- Task 7 Festival Verifier is intentionally not started in this commit.
