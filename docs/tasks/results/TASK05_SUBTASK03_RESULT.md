# Task 5.3 Result: Scoring and Selection Edge Cases

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 5.3 adds regression coverage for the boundary cases around scoring and
candidate quota selection.

No production behavior needed to change. The existing ScoringTool and candidate
selection helper already kept festivals and gourmet-only external-link themes
out of scoring, preserved available candidates when supply is insufficient, and
reported quota relaxations as audit data rather than hard failures.

## Completed Scope

- Added scoring coverage for the gourmet-only external-link theme.
- Added scoring coverage for festival-like theme labels.
- Added candidate selection coverage for total candidate shortage.
- Added candidate selection coverage for soft max quota relaxation.
- Confirmed quota shortage remains an audit signal when usable candidates still
  exist.

## Changed Files

```text
tests/test_scoring.py
tests/test_candidate_selection.py
docs/tasks/results/TASK05_SUBTASK03_RESULT.md
```

## Spec Alignment Checklist

- Festival candidates are excluded from current scoring: covered.
- Gourmet-only external-link theme does not receive a place theme bonus:
  covered.
- Insufficient candidate count preserves available primary candidates: covered.
- Reserve can be empty without failing the selection helper: covered.
- Soft max relaxation is reported in coverage audit: covered.

## Verification

Executed from `Lovv-agent` using the project-standard `uv` runner.

```powershell
uv run pytest tests/test_scoring.py tests/test_candidate_selection.py
```

Result:

```text
17 passed
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
104 passed
```

## Notes and Constraints

- This subtask intentionally adds test coverage only.
- Any future decision to score festivals or restaurant records must update both
  the spec and these exclusion tests together.
