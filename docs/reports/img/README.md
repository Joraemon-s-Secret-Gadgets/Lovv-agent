# 테스트 보고서 화면 캡처

`LOVV_V1_TEST_REPORT.md` §3.2의 `[화면 N]` 블록에 들어가는 콘솔 캡처. 3장 모두 **같은 한 요청**(POST /invocations, 총 11.11s)의 화면이다. 화면 1은 호출 경로 구조(trace map), **화면 2·3은 같은 트레이스 타임라인의 상단·하단**이다.

| 파일 | 화면 | 내용 |
|------|------|------|
| `observability_1.png` | 화면 1 | Trace map — LangGraph 노드 그래프 + 서비스 서브콜(S3Vectors/DynamoDB/BedrockConverse) |
| `observability_2.png` | 화면 2 | Trace 상세 타임라인 상단 — intent(2.45s) → candidate_evidence(4.17s) |
| `observability_3.png` | 화면 3 | Trace 상세 타임라인 하단 — planner(4.28s) + supervisor·packager |

> ⚠️ 이미지 파일(`observability_1~3.png`)을 이 폴더(`docs/reports/img/`)로 옮겨 주세요. 현재는 `docs/tasks/results/img/`에 있습니다. (보고서의 `./img/` 경로가 이 폴더를 가리킵니다.)
