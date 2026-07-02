# Lovv AgentV2 Intent Local Test Code SPEC

## 1. 목적

Intent playground에서 조정한 prompt/schema를 AgentV2 Intent Agent에 반영하기 전에, 로컬에서 반복 실행 가능한 테스트 코드로 회귀 기준을 고정한다.

이 SPEC의 1차 테스트 goal은 다음 네 가지다.

- 사용자가 선호하는 테마를 자연어에서 추출한다.
- 사용자가 비선호하는 테마를 자연어에서 추출한다.
- 사용자가 선호하는 지역, 도시, 권역을 자연어에서 추출한다.
- 사용자가 비선호하는 지역, 도시, 권역을 자연어에서 추출한다.

부가 goal은 추출된 선호/비선호 신호가 AgentV2 `state.intent.city_select_input` 및 후속 state 계약으로 안전하게 전달되는지 검증하는 것이다.

## 2. 적용 범위

### 대상 런타임

AgentV2 Intent 경로를 대상으로 한다.

- Node: `src/lovv_agent_v2/agents/intent/node.py`
- Initial parser: `src/lovv_agent_v2/agents/intent/parser.py`
- Modify parser: `src/lovv_agent_v2/agents/intent/modify_parser.py`
- Validator: `src/lovv_agent_v2/agents/intent/validator.py`
- State contract: `src/lovv_agent_v2/core/state.py`
- Handoff schema: `src/lovv_agent_v2/models/schemas.py`
- Existing V2 test file: `tests/v2/test_intent.py`
- Related state tests: `tests/v2/test_state_contract.py`
- Playground: `intent_playground/prompt.md`, `intent_playground/schema.json`, `intent_playground/cases.jsonl`

V1 `lovv_agent.agents.intent`는 이 SPEC의 대상이 아니다.

### 제외 범위

- AgentV1 prompt/schema 변경
- 추천 후보 검색, scoring, planner 일정 생성의 품질 평가
- live DynamoDB/S3 Vector 검증
- AgentCore Runtime 배포 검증
- congestion, transport, vibe 같은 부가 soft signal을 1차 goal보다 먼저 확장하는 작업

## 3. AgentV2 Intent 계약

AgentV2 Intent는 원시 입력을 검색·계획 가능한 typed state로 바꾸는 경계에서 멈춘다.

### 입력

- `state.request`
- `state.intent.intent_output`
- `state.intent.city_select_input`
- resume/수정 턴에서는 기존 itinerary와 사용자 수정 명령

### 출력

최소 출력은 다음 top-level patch다.

```python
{"intent": next_intent}
```

`next_intent`에는 최소한 다음 필드가 있어야 한다.

- `city_select_input`
- `cleaned_raw_query`
- `soft_preference_query`
- `unsupported_conditions`

선호/비선호 테마·지역 parser가 구현되면 `next_intent`에 다음 semantic field를 추가한다.

- `preferred_theme_ids`
- `disliked_theme_ids`
- `preferred_region_ids`
- `disliked_region_ids`

`city_select_input`은 `CitySelectInput.from_mapping(...).to_dict()`를 통과해야 한다.

### CitySelectInput 필수 필드

- `country`
- `travel_month`
- `travel_year`
- `trip_type`
- `active_required_themes`
- `include_festivals`
- `cleaned_raw_query`
- `soft_preference_query`
- `unsupported_conditions`
- `destination_id`
- `user_location`
- `execution_mode`
- `congestion_pref`
- `transport_pref`

## 4. Theme/Region Extraction 원칙

### 선호 테마

- 자연어에 명시된 선호 테마만 `preferred_theme_ids`로 추출한다.
- `preferred_theme_ids`는 deterministic resolver를 거쳐 `city_select_input.active_required_themes`로 반영된다.
- 분위기 표현만으로 테마를 단정하지 않는다. 예: "조용한 곳"만으로 `healing_rest`를 추가하지 않는다.

허용 theme id:

- `sea_coast`
- `nature_trekking`
- `food_local`
- `history_tradition`
- `art_sense`
- `healing_rest`

### 비선호 테마

- 자연어에 명시된 비선호 테마만 `disliked_theme_ids`로 추출한다.
- `disliked_theme_ids`는 `active_required_themes`에 섞지 않는다.
- 단순 활동 제외를 테마 전체 제외로 과도하게 확대하지 않는다. 예: "가파른 등산 코스는 빼줘"는 `nature_trekking` 전체 비선호가 아니라 활동 조건 exclusion이다.

### 선호 지역

- 자연어에 명시된 지역, 도시, 권역 선호를 `preferred_region_ids`로 추출한다.
- 지역 신호는 theme 신호와 분리한다. 예: "강원도 바다"는 preferred region 강원, preferred theme `sea_coast`다.
- 확정 destination이 아니면 `destination_id`를 임의로 덮어쓰지 않는다.

### 비선호 지역

- 자연어에 명시된 지역, 도시, 권역 비선호를 `disliked_region_ids`로 추출한다.
- 비선호 지역은 `destination_id`를 덮어쓰지 않는다.
- downstream이 제외 필터, rerun route, clarification route 중 하나로 소비한다.

### 충돌

- 같은 theme이 선호와 비선호에 동시에 있으면 contradiction flag 또는 clarification route로 보낸다.
- 같은 region이 선호와 비선호에 동시에 있으면 contradiction flag 또는 clarification route로 보낸다.
- 충돌한 값은 downstream 검색 입력에 확정 필터로 넣지 않는다.

## 5. Playground Field Mapping

Intent playground 확장 필드는 AgentV2에서 다음 필드로 수렴시킨다.

| Playground field | AgentV2 target | 비고 |
| --- | --- | --- |
| `mentioned_theme_ids` | `intent.preferred_theme_ids` 및 `city_select_input.active_required_themes` resolver 입력 | 선호 테마 추출의 정본 |
| `excluded_theme_ids` | `intent.disliked_theme_ids` 또는 downstream exclusion input | 비선호 테마 추출의 정본 |
| `preferred_region_ids` 또는 region text | `intent.preferred_region_ids` 또는 destination resolver 입력 | 선호 지역 추출의 정본 |
| `excluded_region_ids` 또는 region text | `intent.disliked_region_ids` 또는 downstream exclusion input | 비선호 지역 추출의 정본 |
| `crowd_preference` | `city_select_input.congestion_pref` | 부가 soft signal. theme/region goal 이후 확장 |
| `desired_vibe_tags` | soft rerank metadata input | 부가 soft signal |
| `desired_experience_tags` | soft rerank metadata input | 부가 soft signal |
| `companion_fit` | profile/planner soft constraint | 부가 soft signal |
| `place_properties.walking_load` | Planner input 또는 schedule hint | `transport_pref`와 혼동 금지 |
| `core_change_requests` | modify parser 또는 clarification route | API core overwrite 금지 |

## 6. 테스트 계층

### Layer A. V2 pure local unit tests

파일: `tests/v2/test_intent.py`

목적: AWS 호출 없이 AgentV2 Intent node/parser/validator 계약을 고정한다.

필수 조건:

- `uv run pytest tests/v2/test_intent.py -q`로 실행된다.
- 모든 테스트는 순수 함수, fake state, fake parser output만 사용한다.
- network, AWS credential, `.env.local`에 의존하지 않는다.

주요 검증 대상:

- `intent_node`
- `_city_select_input_from_request`
- `CitySelectInput.from_mapping`
- 향후 구현될 `parser.py`의 initial query parser
- 향후 구현될 `modify_parser.py`의 resume command parser
- 향후 구현될 `validator.py`의 contradiction/unsupported flag helper

### Layer B. V2 state contract tests

파일: `tests/v2/test_state_contract.py`

목적: Intent 출력이 Profile, Festival Gate, City Select, Planner에서 소비 가능한 state shape인지 검증한다.

실행:

```powershell
uv run pytest tests/v2/test_state_contract.py -q
```

### Layer C. Playground contract tests

파일: `intent_playground/test_run.py`

목적: playground runner, schema, assertion helper, theme resolver가 로컬에서 깨지지 않는지 검증한다.

실행:

```powershell
uv run pytest intent_playground/test_run.py -q
```

## 7. 추가할 테스트 코드 범위

### 7.1 선호 테마 추출

파일: `tests/v2/test_intent.py`

추가 테스트명:

```python
def test_initial_parser_extracts_preferred_themes_from_natural_language() -> None:
    ...
```

목적:

사용자가 자연어로 선호하는 여행 테마를 명시하면 AgentV2 Intent가 canonical theme id로 추출해야 한다.

기대:

- "바다랑 해안 산책이 좋아" -> `preferred_theme_ids`에 `sea_coast`
- "숲길 걷고 자연 위주" -> `preferred_theme_ids`에 `nature_trekking`
- "전시랑 미술관" -> `preferred_theme_ids`에 `art_sense`
- `city_select_input.active_required_themes`는 deterministic resolver를 거쳐 canonical label로 반영된다.

### 7.2 비선호 테마 추출

추가 테스트명:

```python
def test_initial_parser_extracts_disliked_themes_without_removing_unrelated_preferences() -> None:
    ...
```

목적:

사용자가 피하고 싶은 테마를 명시하면 선호 테마와 분리해서 추출해야 한다.

기대:

- "바다는 좋지만 등산은 빼줘" -> `preferred_theme_ids`에 `sea_coast`, `disliked_theme_ids`에 `nature_trekking`
- "미술관은 제외하고 역사 유적 위주" -> `disliked_theme_ids`에 `art_sense`, `preferred_theme_ids`에 `history_tradition`
- `disliked_theme_ids`는 `active_required_themes`에 섞이지 않는다.

### 7.3 선호 지역 추출

추가 테스트명:

```python
def test_initial_parser_extracts_preferred_regions_from_natural_language() -> None:
    ...
```

목적:

사용자가 선호하는 지역, 도시, 권역을 theme과 분리해서 추출해야 한다.

기대:

- "강원도 바다 쪽이 좋아" -> `preferred_region_ids`에 강원 권역
- "경주나 안동 같은 경북 역사 도시" -> preferred region/city 후보에 경주, 안동 또는 경북 권역
- region 신호는 `preferred_theme_ids`에 들어가지 않는다.
- 확정 destination이 아니면 `destination_id`를 임의로 덮어쓰지 않는다.

### 7.4 비선호 지역 추출

추가 테스트명:

```python
def test_initial_parser_extracts_disliked_regions_without_overwriting_destination() -> None:
    ...
```

목적:

사용자가 피하고 싶은 지역을 명시하면 지역 exclusion 신호로 분리하고, API core field를 덮어쓰지 않는다.

기대:

- "강원도는 빼고 경북 쪽으로" -> `disliked_region_ids`에 강원 권역, `preferred_region_ids`에 경북 권역
- "속초 말고 안동" -> disliked city에 속초, preferred city에 안동
- 기존 `state.request.destinationId`가 있으면 parser가 직접 변경하지 않는다.

### 7.5 선호/비선호 충돌

추가 테스트명:

```python
def test_initial_parser_flags_contradictory_theme_or_region_preferences() -> None:
    ...
```

목적:

같은 테마나 지역이 선호와 비선호에 동시에 걸리면 조용히 하나를 선택하지 않고 ambiguity를 노출해야 한다.

기대:

- "바다는 좋은데 바다는 빼줘" -> contradiction flag 또는 clarification route
- "강원도는 싫은데 강원도 바다 추천" -> contradiction flag 또는 clarification route
- downstream 검색 입력에는 충돌한 값이 확정 필터로 들어가지 않는다.

### 7.6 request fallback에서 CitySelectInput 생성

추가 테스트명:

```python
def test_intent_node_builds_city_select_input_from_request_when_intent_missing() -> None:
    ...
```

목적:

`state.intent.city_select_input`이 없는 초기 상태에서도 `state.request`만으로 City Select 입력을 만들 수 있어야 한다.

기대:

- `result["intent"]["city_select_input"]`가 존재한다.
- `CitySelectInput.from_mapping(...)` 검증을 통과한다.
- `cleaned_raw_query`, `soft_preference_query`, `unsupported_conditions`가 `intent` top-level에도 mirror된다.

### 7.7 기존 city_select_input 보존 및 identity enrichment

추가 테스트명:

```python
def test_intent_node_preserves_existing_city_select_input_and_enriches_identity() -> None:
    ...
```

목적:

상류 parser가 이미 `city_select_input`을 만든 경우 Intent node가 이를 우선 사용하고, 도시 identity 보강만 수행해야 한다.

기대:

- `intent.city_select_input`이 `request` fallback보다 우선한다.
- `destination_id`, `city_key`, `ddb_pk`가 존재할 때 identity 보강 결과가 유지된다.
- 기존 `intent`의 unrelated field는 보존된다.

### 7.8 `intent_output` legacy/input alias 수용

추가 테스트명:

```python
def test_intent_node_accepts_intent_output_alias_for_city_select_input() -> None:
    ...
```

목적:

mock 결과나 이전 실험 산출물이 `intent_output`에 들어온 경우에도 AgentV2 node가 `city_select_input`으로 정규화해야 한다.

기대:

- `state.intent.intent_output`만 있어도 정상 처리된다.
- 출력에는 `city_select_input`이 생성된다.
- `intent_output`은 downstream 정본으로 사용하지 않는다.

### 7.9 modify parser 테마/지역 업데이트

추가 테스트명:

```python
def test_modify_parser_extracts_theme_and_region_preference_updates() -> None:
    ...
```

목적:

resume 턴에서 사용자가 선호/비선호 테마나 지역을 바꾸면 수정 intent로 구조화해야 한다.

기대:

- "2일차 오후는 바다 말고 숲길로" -> disliked theme `sea_coast`, preferred theme `nature_trekking`
- "속초는 빼고 안동 쪽으로 바꿔줘" -> disliked region/city 속초, preferred region/city 안동
- seed place 변경 금지 정책이 있으면 flag로 노출된다.

## 8. Playground Case 승격 기준

`intent_playground/cases.jsonl`의 모든 case를 즉시 운영 테스트로 옮기지 않는다. 다음 기준을 통과한 case만 `tests/v2/test_intent.py` 또는 별도 `tests/v2/test_intent_semantic_contract.py`로 승격한다.

승격 가능:

- `mentioned_theme_ids` -> `preferred_theme_ids`
- `excluded_theme_ids` -> `disliked_theme_ids`
- 선호 지역 text -> `preferred_region_ids`
- 비선호 지역 text -> `disliked_region_ids`
- 선호/비선호 theme 또는 region 충돌
- `intent_output` -> `city_select_input` 정규화

승격 보류:

- `crowd_preference` -> `congestion_pref` 매핑
- `transport_pref` 추출
- scoring weight 수치
- city ranking 변화
- planner 일정 배치 품질
- live provider별 prompt 품질

보류 이유:

이번 테스트 goal은 선호/비선호 테마와 지역 추출이다. AgentV2 Intent는 검색·점수·일정 품질을 판정하지 않는다.

## 9. 권장 파일 구조

최소 변경:

```text
tests/v2/test_intent.py
```

semantic 확장 필드가 많아질 경우:

```text
tests/v2/test_intent_semantic_contract.py
```

resume 수정 parser를 분리할 경우:

```text
tests/v2/test_intent_modify_parser.py
```

live smoke를 명시적으로 분리할 경우:

```text
tests/v2/test_intent_live_smoke.py
```

`test_intent_live_smoke.py`는 기본 pytest에서 자동 실행되지 않도록 marker 또는 env gate를 둔다.

예:

```python
pytestmark = pytest.mark.skipif(
    os.getenv("LOVV_RUN_LIVE_INTENT_SMOKE") != "1",
    reason="live Bedrock smoke is opt-in",
)
```

## 10. 로컬 실행 명령

빠른 AgentV2 Intent gate:

```powershell
uv run pytest tests/v2/test_intent.py tests/v2/test_state_contract.py -q
```

playground helper gate:

```powershell
uv run pytest intent_playground/test_run.py -q
```

전체 로컬 regression:

```powershell
uv run pytest -q
```

playground dry-run:

```powershell
uv run python intent_playground/run.py --dry-run
```

## 11. 테스트 결과 적재 규칙

AgentV2 Intent 테스트 실행 결과는 보고서/검증 결과 모음인 `docs/tasks/results/` 아래의 `tests/` 폴더에 적재한다.

기본 경로:

```text
docs/tasks/results/tests/agentv2_intent/<YYYYMMDDTHHMMSSZ>/
```

필수 산출물:

```text
summary.md
test_output.md
input_output.md
pytest_agentv2_intent.log
pytest_playground.log
```

선택 산출물:

```text
playground_dry_run.json
live_smoke.jsonl
```

작성 규칙:

- `summary.md`에는 실행 일시, git branch/commit, 실행 명령, pass/fail/skip 수, 실패 테스트명, 후속 조치를 기록한다.
- `test_output.md`에는 사용자가 바로 확인할 수 있는 테스트 출력 결과와 한국어 해석을 기록한다.
- `input_output.md`에는 대표 테스트 input과 실제 parser/node output을 기록한다.
- `pytest_agentv2_intent.log`에는 `uv run pytest tests/v2/test_intent.py tests/v2/test_state_contract.py -q` 출력 원문을 저장한다.
- `pytest_playground.log`에는 `uv run pytest intent_playground/test_run.py -q` 출력 원문을 저장한다.
- live smoke는 opt-in 실행일 때만 저장하며, 실패해도 local unit gate와 분리해서 기록한다.
- 문서만 수정한 경우에는 test result 폴더를 새로 만들지 않는다. 실제 테스트를 실행한 경우에만 적재한다.

권장 실행 예:

```powershell
uv run python scripts/v2/run_agentv2_intent_tests.py
```

고정된 결과 폴더명을 사용해야 할 때:

```powershell
uv run python scripts/v2/run_agentv2_intent_tests.py --timestamp 20260702T000000Z
```

## 12. 완료 기준

테스트 코드 작성은 다음 조건을 모두 만족해야 완료로 본다.

- `uv run pytest tests/v2/test_intent.py tests/v2/test_state_contract.py -q` 통과
- `uv run pytest intent_playground/test_run.py -q` 통과
- 실제 테스트를 실행한 경우 `docs/tasks/results/tests/agentv2_intent/<timestamp>/summary.md`, `test_output.md`, `input_output.md`, log 파일을 적재
- 새 테스트가 AWS credential 없이 통과
- 선호/비선호 테마와 지역 추출 계약이 테스트명과 assertion에서 명확함
- `disliked_theme_ids`와 `disliked_region_ids`가 선호 필드나 `active_required_themes`에 섞이지 않음
- 실패 시 어느 계약이 깨졌는지 assertion message 또는 테스트명만으로 추적 가능

## 13. 구현 순서

1. `tests/v2/test_intent.py`에 preferred/disliked theme extraction 테스트를 먼저 추가한다.
2. preferred/disliked region extraction 테스트를 추가한다.
3. theme/region 선호·비선호 충돌 테스트를 추가한다.
4. request fallback, `city_select_input` 우선순위, `intent_output` alias 수용 테스트를 보강한다.
5. `modify_parser.py`가 구현될 때 theme/region preference update 테스트를 추가한다.
6. congestion/transport/unsupported condition은 theme/region goal이 고정된 뒤 부가 테스트로 확장한다.
7. 테스트 실행 후 `docs/tasks/results/tests/agentv2_intent/<timestamp>/`에 summary와 log를 저장한다.

## 14. 비고

AgentV2 Intent parser/validator 파일은 현재 구현이 얇으므로, 첫 테스트 묶음은 선호/비선호 테마와 지역 추출 계약을 고정하는 데 집중한다. 그 다음 playground prompt/schema에서 검증한 semantic field를 AgentV2 parser로 가져오며, 각 필드가 downstream에 어떤 이름으로 전달되는지 테스트로 고정한다.
