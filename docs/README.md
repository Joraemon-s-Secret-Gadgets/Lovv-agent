# Lovv Agent 문서 인덱스

이 폴더는 Lovv Agent의 설계, 구현 계획, 검증 결과, 의사결정 보고서를 보관하는
durable 문서 영역이다. 작업 중인 Kiro spec은 `.kiro/`에 둘 수 있지만, 팀이 계속
참조해야 하는 문서는 아래 분류에 맞춰 `docs/`로 옮긴다.

## 배치 규칙

| 위치 | 목적 | 작성 기준 |
| --- | --- | --- |
| [`reports/`](./reports/README.md) | 분석 보고서, 의사결정 기록, 구현 결과 요약, 외부 전달용 문서 | 코드나 spec을 해석한 결론과 근거를 기록한다. |
| [`specs/`](./specs/README.md) | 구현 전/중 계약이 되는 SPEC과 설계 초안 | V1/V2 하위 폴더로 나누고 요구사항, 경계, 인터페이스, 검증 기준을 명확히 둔다. |
| [`tasks/`](./tasks/README.md) | 구현 task와 실행 순서 | SPEC을 실행 가능한 작업 단위로 나눈다. |
| [`tasks/results/`](./tasks/results/) | 실제 구현 또는 검증을 수행한 결과 | 실행 증거가 있을 때만 작성한다. 문서 이관만으로 결과 보고서를 만들지 않는다. |

## 바로가기

- [AgentCore 전환 보고서 모음](./reports/README.md)
- [SPEC 인덱스](./specs/README.md)
- [V1 SPEC 인덱스](./specs/v1/README.md)
- [V2 SPEC 인덱스](./specs/v2/README.md)
- [Task 인덱스](./tasks/README.md)
- [Task 결과 디렉터리](./tasks/results/)

## 현재 구조

```text
docs/
  README.md
  reports/        분석, 의사결정, 전환 보고서
  specs/          구현 SPEC과 설계 계약
  specs/v1/       현재 LangGraph/AgentCore V1 계약
  specs/v2/       Memory/checkpointer/V2 전환 계약
  tasks/          구현 task 문서
  tasks/results/  실제 구현/검증 결과와 fixture
```
