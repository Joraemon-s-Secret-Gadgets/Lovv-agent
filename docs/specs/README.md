# Lovv Agent SPEC 인덱스

SPEC 문서는 구현 범위, 인터페이스, 검증 기준을 고정하는 계약 문서다. 단순 설명이나
회의 메모는 `docs/reports/`에 두고, 실행 가능한 구현 계약만 이 폴더에 둔다.

## 버전별 폴더

| 폴더 | 기준 | 용도 |
| --- | --- | --- |
| [v1](./v1/README.md) | 현재 LangGraph/AgentCore V1 운영 경계 | 현재 구현, 배포 준비, FM routing, observability, 테스트 계획 |
| [v2](./v2/README.md) | V2 전환 설계 경계 | Memory, checkpointer, Cognito 가명화, 대화형 일정 수정, V2 upgrade |

`DESIGN_V1`처럼 파일명에 들어간 설계 초안 버전은 제품 단계 V1/V2와 별개다. 해당 문서가
V2 전환 설계에 속하면 `v2/`에 둔다.

## 바로가기

- [V1 SPEC 인덱스](./v1/README.md)
- [V2 SPEC 인덱스](./v2/README.md)
