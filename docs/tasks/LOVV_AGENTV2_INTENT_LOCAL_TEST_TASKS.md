# Lovv AgentV2 Intent Local Test Tasks

Source spec: `docs/specs/v2/LOVV_AGENTV2_INTENT_LOCAL_TEST_SPEC.md`

GitHub issue tracker: `Joraemon-s-Secret-Gadgets/Lovv-agent`

Parent issue: [#18](https://github.com/Joraemon-s-Secret-Gadgets/Lovv-agent/issues/18)

## Scope

Implement AgentV2 Intent local tests and parser behavior for extracting user
preferred and disliked themes, regions, cities, and areas. The work must keep
Intent responsible for typed signal extraction only; City Select, scoring, and
Planner quality decisions remain downstream.

## Task Order

| Order | Issue | Task | Depends On |
| --- | --- | --- | --- |
| 1 | #19 | Preferred/disliked theme extraction parser and tests | None |
| 2 | #20 | Preferred/disliked region extraction parser and tests | #19 |
| 3 | #21 | Theme/region preference contradiction validator | #19, #20 |
| 4 | #22 | `city_select_input` handoff and `intent_output` alias tests | None |
| 5 | #23 | Modify-turn theme/region preference update parser | #19, #20, #21 |
| 6 | #24 | Test-result artifact storage and task/spec alignment | #19 through #23 |

## Task 1: Preferred/Disliked Theme Extraction

**GitHub issue:** #19

**Purpose:** Extract user-preferred and user-disliked travel themes from initial
natural language input without mixing disliked themes into active themes.

**Files likely touched:**

- `src/lovv_agent_v2/agents/intent/parser.py`
- `tests/v2/test_intent.py`

**Acceptance criteria:**

- [x] "바다랑 해안 산책이 좋아" produces `preferred_theme_ids=["sea_coast"]`.
- [x] "숲길 걷고 자연 위주" produces `preferred_theme_ids=["nature_trekking"]`.
- [x] "전시랑 미술관" produces `preferred_theme_ids=["art_sense"]`.
- [x] "바다는 좋지만 등산은 빼줘" separates preferred `sea_coast` and disliked `nature_trekking`.
- [x] `disliked_theme_ids` does not enter `active_required_themes`.

**Verification:**

- [x] `uv run pytest tests/v2/test_intent.py -q`

## Task 2: Preferred/Disliked Region Extraction

**GitHub issue:** #20

**Purpose:** Extract user-preferred and user-disliked regions, cities, or areas
separately from theme signals.

**Files likely touched:**

- `src/lovv_agent_v2/agents/intent/parser.py`
- `tests/v2/test_intent.py`

**Acceptance criteria:**

- [x] "강원도 바다 쪽이 좋아" separates preferred region and preferred theme.
- [x] "경주나 안동 같은 경북 역사 도시" extracts region/city preference separately from `history_tradition`.
- [x] "강원도는 빼고 경북 쪽으로" separates disliked and preferred regions.
- [x] "속초 말고 안동" separates disliked and preferred city signals.
- [x] Parser does not overwrite `destination_id` directly.

**Verification:**

- [x] `uv run pytest tests/v2/test_intent.py -q`

## Task 3: Theme/Region Contradiction Validator

**GitHub issue:** #21

**Purpose:** Flag contradictory theme or region preferences instead of choosing
one silently.

**Files likely touched:**

- `src/lovv_agent_v2/agents/intent/validator.py`
- `tests/v2/test_intent.py`

**Acceptance criteria:**

- [x] "바다는 좋은데 바다는 빼줘" yields contradiction or clarification signal.
- [x] "강원도는 싫은데 강원도 바다 추천" yields contradiction or clarification signal.
- [x] Conflicting values do not enter fixed downstream filters.

**Verification:**

- [x] `uv run pytest tests/v2/test_intent.py -q`

## Task 4: City Select Handoff Tests

**GitHub issue:** #22

**Purpose:** Prove AgentV2 `intent_node` produces a valid
`city_select_input`, preserves existing parser output, and accepts legacy
`intent_output` mocks.

**Files likely touched:**

- `src/lovv_agent_v2/agents/intent/node.py`
- `tests/v2/test_intent.py`
- `tests/v2/test_state_contract.py`

**Acceptance criteria:**

- [x] Request-only state builds `city_select_input`.
- [x] Existing `intent.city_select_input` wins over request fallback.
- [x] `intent.intent_output` is normalized to `city_select_input`.
- [x] Unrelated intent fields are preserved.
- [x] `CitySelectInput.from_mapping` validates the output.

**Verification:**

- [x] `uv run pytest tests/v2/test_intent.py tests/v2/test_state_contract.py -q`

## Task 5: Modify-Turn Preference Updates

**GitHub issue:** #23

**Purpose:** Parse resume-turn theme/region preference changes into structured
modify intent signals.

**Files likely touched:**

- `src/lovv_agent_v2/agents/intent/modify_parser.py`
- `tests/v2/test_intent.py`

**Acceptance criteria:**

- [x] "2일차 오후는 바다 말고 숲길로" separates disliked `sea_coast` and preferred `nature_trekking`.
- [x] "속초는 빼고 안동 쪽으로 바꿔줘" separates disliked and preferred city signals.
- [x] Seed-place change restrictions stay out of the local preference extractor unless a seed-place field is introduced.

**Verification:**

- [x] `uv run pytest tests/v2/test_intent.py -q`

## Task 6: Test Result Artifacts

**GitHub issue:** #24

**Purpose:** Store real test execution evidence under the report collection
folder and keep task/spec references aligned with the issue tree.

**Files likely touched:**

- `docs/tasks/results/tests/agentv2_intent/<timestamp>/summary.md`
- `docs/tasks/results/tests/agentv2_intent/<timestamp>/test_output.md`
- `docs/tasks/results/tests/agentv2_intent/<timestamp>/input_output.md`
- `docs/tasks/results/tests/agentv2_intent/<timestamp>/pytest_agentv2_intent.log`
- `docs/tasks/results/tests/agentv2_intent/<timestamp>/pytest_playground.log`
- `scripts/v2/run_agentv2_intent_tests.py`
- `docs/specs/v2/LOVV_AGENTV2_INTENT_LOCAL_TEST_SPEC.md`

**Acceptance criteria:**

- [x] Real test runs write summary and raw logs under `docs/tasks/results/tests/agentv2_intent/<timestamp>/`.
- [x] `summary.md` records branch, commit, commands, pass/fail/skip counts, failures, and follow-up.
- [x] `test_output.md` records readable command output and Korean interpretation.
- [x] `input_output.md` records representative test input and actual parser/node output.
- [x] `scripts/v2/run_agentv2_intent_tests.py` creates the result folder and artifacts automatically.
- [x] Task/spec docs keep issue numbers and result paths aligned.

**Verification:**

- [x] `rg "AgentV2 Intent|GitHub issue|agentv2_intent|#18|#19|#24" docs/tasks docs/specs/v2 -S`

## Checkpoint

- [x] Focused AgentV2 Intent tests pass.
- [x] Playground helper tests pass.
- [x] Result artifacts are written for real test runs.
- [x] Any unsupported live smoke behavior is recorded separately from local unit gates.
