# AgentV2 Intent 로컬 테스트 결과

## 범위

- Branch: `main`
- Base commit: `29be949`
- 목표: 사용자 발화에서 선호/비선호 테마를 추출한다.
- 목표: 사용자 발화에서 선호/비선호 지역과 한글 지역명을 추출한다.
- 대상: AgentV2 intent parser, prompt runtime, preference validator, intent node handoff.

## 결과

- `python -m pytest tests/v2/test_intent.py tests/v2/test_state_contract.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider`
  - 결과: `24 passed in 0.91s`
  - 종료 코드: `0`
  - 원문 로그: `pytest_agentv2_intent.log`
  - 출력 결과: `test_output.md`
  - Input/Output 결과: `input_output.md`
- `python -m pytest intent_playground/test_run.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider`
  - 결과: `25 passed in 60.64s (0:01:00)`
  - 종료 코드: `0`
  - 원문 로그: `pytest_playground.log`
  - 출력 결과: `test_output.md`
  - Input/Output 결과: `input_output.md`
- `python -m pytest tests/v2/test_harness.py tests/v2/test_config.py tests/v2/test_runtime_dependency_injection.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider`
  - 결과: `15 passed in 0.55s`
  - 종료 코드: `0`
  - 원문 로그: `pytest_intent_runtime.log`
  - 출력 결과: `test_output.md`
  - Input/Output 결과: `input_output.md`

## 실패

- 없음.

## 검증 필드

- `preferred_theme_ids`
- `disliked_theme_ids`
- `preferred_region_ids`
- `preferred_region_names`
- `disliked_region_ids`
- `disliked_region_names`
- `needs_clarification`
- `clarifying_question`
- `contradiction_reasons`
- `city_select_input.active_required_themes`
- `intent_extraction_mode`
