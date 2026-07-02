# AgentV2 Intent 테스트 출력 결과

## AgentV2 Intent 로컬 pytest

실행 명령:

```bash
uv run pytest tests/v2/test_intent.py tests/v2/test_state_contract.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider
```

출력:

```text
...............                                                          [100%]
15 passed in 0.10s
```

해석:

- 총 15개 테스트가 통과했다.
- 실패한 테스트는 없다.
- 스킵된 테스트는 없다.

## Intent Playground pytest

실행 명령:

```bash
uv run pytest intent_playground/test_run.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider
```

출력:

```text
...........                                                              [100%]
11 passed in 0.05s
```

해석:

- 총 11개 테스트가 통과했다.
- 실패한 테스트는 없다.
- 스킵된 테스트는 없다.

## 종합 결과

- 전체 통과: 26
- 전체 실패: 0
- 전체 스킵: 0
- 원문 로그: `pytest_agentv2_intent.log`, `pytest_playground.log`
- 테스트 Input/Output 결과: `input_output.md`
