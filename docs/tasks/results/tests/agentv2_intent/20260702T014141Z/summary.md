# AgentV2 Intent 로컬 테스트 결과

## 범위

- Branch: `main`
- Base commit: `21b25c6`
- 목표: 사용자 발화에서 선호/비선호 테마를 추출한다.
- 목표: 사용자 발화에서 선호/비선호 지역과 한글 지역명을 추출한다.
- 대상: AgentV2 deterministic intent parser, modify parser, preference validator, intent node handoff.
- GitHub main issue: #18
- GitHub sub issue: #19, #20, #21, #22, #23, #24

## 결과

- `.\.venv\Scripts\python.exe -m pytest tests/v2/test_intent.py tests/v2/test_state_contract.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider`
  - 결과: `15 passed in 0.10s`
  - 종료 코드: `0`
  - 원문 로그: `pytest_agentv2_intent.log`
  - 출력 결과: `test_output.md`
  - Input/Output 결과: `input_output.md`
- `.\.venv\Scripts\python.exe -m pytest intent_playground/test_run.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider`
  - 결과: `11 passed in 0.05s`
  - 종료 코드: `0`
  - 원문 로그: `pytest_playground.log`
  - 출력 결과: `test_output.md`
  - Input/Output 결과: `input_output.md`

## 실패

- 없음.

## 후속 작업

- Live smoke testing은 이 로컬 unit/playground gate와 별도로 수행한다.

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
