# Task 10.3 Result: Prompt Registry and Structured LLM Contracts

> Completion Date: 2026-06-14
> Responsible Agent: Codex
> Source Task: `docs/tasks/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_TASKS.md`
> Source Spec: `docs/specs/v1/LOVV_LANGGRAPH_AGENT_IMPLEMENTATION_SPEC.md`

## Summary

Task 10.3 adds explicit, versioned prompt assets and a structured Planner copy
composer. Live LLM prompts are no longer hidden only inside call sites: prompt
text is loaded through a registry from Markdown assets under
`src/lovv_agent/prompts/`.

On 2026-06-15, the canonical Korean Intent prompt from `intent_agent.md` was
added as `intent_normalization.v1.md` and wired into the live LangGraph harness.
The harness preserves deterministic API core fields and merges only validated
natural-language enrichment from the model.

Planner now supports an optional prompt-backed copy/explanation runtime. When a
runtime is injected, Planner sends only final placed itinerary items,
detail-safe summaries, verified festival placement summaries, public
candidate reason claims, and public-safe validation signals. If model output is
malformed or contains internal terms, Planner keeps the deterministic fallback.

## Completed Scope

- Added versioned prompt registry.
- Added prompt assets:
  - `intent_normalization.v1.md`
  - `candidate_reason_claim.v1.md`
  - `planner_copy_explanation.v1.md`
- Updated Candidate Evidence reason claim request to load its system prompt from
  the registry.
- Added Planner copy/explanation composer with:
  - schema-enforced output request,
  - grounding-only prompt summary,
  - item copy validation,
  - internal-term rejection,
  - deterministic fallback on schema failure.
- Integrated optional Planner `explanation_runtime`.
- Added tests for:
  - prompt registry loading,
  - prompt-backed Planner item `title`/`body`/`reason`,
  - recommendation reason and itinerary flow generation,
  - schema failure fallback.
- Updated Hatch wheel config so Markdown prompt assets are included in package
  builds.

## Changed Files

```text
src/lovv_agent/prompts/__init__.py
src/lovv_agent/prompts/registry.py
src/lovv_agent/prompts/intent_normalization.v1.md
src/lovv_agent/prompts/candidate_reason_claim.v1.md
src/lovv_agent/prompts/planner_copy_explanation.v1.md
src/lovv_agent/tools/explanation_composer.py
src/lovv_agent/agents/candidate_evidence.py
src/lovv_agent/agents/planner.py
tests/test_harness.py
tests/test_planner.py
pyproject.toml
docs/tasks/results/TASK10_SUBTASK03_RESULT.md
```

## Verification

Focused verification:

```powershell
uv run pytest tests/test_planner.py -k "explanation or composer or fallback"
uv run pytest tests/test_harness.py -k "prompt or llm"
```

Result:

```text
6 passed
1 passed
```

Full verification:

```powershell
uv run pytest
uv run python -m compileall src tests
```

Result:

```text
188 passed, 1 skipped
compileall passed
```

## Notes and Constraints

- Planner still remains deterministic by default.
- LLM-generated copy is applied only when `explanation_runtime` is injected.
- The composer does not receive raw retrieval payloads, raw score audits, full
  Candidate Evidence Package internals, or unbounded DynamoDB details.
- The response packager remains deterministic and does not call an LLM.
