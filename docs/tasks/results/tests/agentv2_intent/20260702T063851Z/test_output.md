# AgentV2 Intent 테스트 출력 결과

## AgentV2 Intent 로컬 pytest

실행 명령:

```bash
python -m pytest tests/v2/test_intent.py tests/v2/test_state_contract.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider
```

출력:

```text
........................                                                 [100%]
24 passed in 0.91s
```

해석:

- 종료 코드: `0`
- 결과 요약: `24 passed in 0.91s`

## Intent Playground pytest

실행 명령:

```bash
python -m pytest intent_playground/test_run.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider
```

출력:

```text
.........................                                                [100%]
25 passed in 60.64s (0:01:00)
```

해석:

- 종료 코드: `0`
- 결과 요약: `25 passed in 60.64s (0:01:00)`

## V2 Intent runtime wiring pytest

실행 명령:

```bash
python -m pytest tests/v2/test_harness.py tests/v2/test_config.py tests/v2/test_runtime_dependency_injection.py -q --basetemp .cache/pytest-tmp -p no:cacheprovider
```

출력:

```text
...............                                                          [100%]
15 passed in 0.55s
```

해석:

- 종료 코드: `0`
- 결과 요약: `15 passed in 0.55s`

## 종합 결과

- 전체 실행 성공 여부: `True`
- 테스트 Input/Output 결과: `input_output.md`
