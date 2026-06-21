# Lovv Intent Prompt Playground

운영 `src/lovv_agent` 코드를 수정하지 않고 Intent Agent의 자연어 의미 추출
prompt와 structured output schema를 반복 실험하는 CLI playground다.

API structured input은 LLM 출력 대상이 아니다. Playground는 API 값을
충돌 감지용 참고 자료로만 전달하고, 출력에는 자연어에서 추출한 의미 신호만
포함한다.

## 구성

```text
intent_playground/
├── run.py
├── prompt.md
├── schema.json
├── cases.jsonl
├── .gitignore
└── results/             # 실행 시 생성, Git 제외
```

- `prompt.md`: 실험할 system prompt
- `schema.json`: Bedrock Structured Outputs에 전달할 JSON Schema
- `cases.jsonl`: 입력과 기대값을 한 줄에 하나씩 정의
- `results/`: 실행 결과 JSONL과 요약 JSON

Playground 파일을 바꿔도 운영 Agent에는 반영되지 않는다.

## 최적화된 출력 계약

LLM 출력은 의미별로 다음 필드에 분리된다.

| 필드 | 의미 |
|---|---|
| `cleaned_raw_query` | 검색 가능한 장소·활동·체험 의도 |
| `soft_preference_query` | ranking에 부드럽게 반영할 분위기·취향 |
| `crowd_preference` | 방문객 수 기반 혼잡도 점수의 선호 방향 |
| `mentioned_theme_ids` | 자연어가 현재 여행에서 명시적으로 요구한 테마 |
| `excluded_theme_ids` | 자연어가 명시적으로 제외한 전체 테마 |
| `desired_vibe_tags` | 장소 metadata의 vibe tag와 매칭할 canonical 선호 |
| `desired_experience_tags` | 사진·피크닉·드라이브 경험 선호 |
| `companion_fit` | 가족·아이·커플·혼자·반려동물 적합성 |
| `place_properties` | 실내외·보행 강도·체류시간 범주 |
| `excluded_preferences` | 사용자가 명시적으로 원하지 않는 특성·활동 |
| `unsupported_conditions` | 현재 도구로 안전하게 보장할 수 없는 조건 |
| `core_change_requests` | API core field의 명시적 변경 요청 |

다음 값은 결정적 코드가 API 입력에서 그대로 유지하거나 계산하므로 LLM이
출력하지 않는다.

```text
entryType, country, travelMonth, travelYear, tripType, destinationId,
themes, includeFestivals, userLocation, active_required_themes,
execution_mode, fulfilled_matrix, needs_clarification,
clarifying_question, candidate_evidence_input
```

`soft_preferences` 배열은 `soft_preference_query`와 의미가 중복되어 제거했다.
범용 문자열 배열이던 `handoff_notes`도 제거하고, core field 변경 요청만
구조화한 `core_change_requests`로 대체했다.

### Active/backup theme 해석

LLM은 API `themes`를 다시 출력하지 않고 자연어에서 언급한 테마만
`mentioned_theme_ids`로 추출한다. Playground의 결정적 resolver가 다음
정책으로 병합한다.

```text
자연어 테마 없음
→ API 선택 themes를 active로 유지

자연어 테마 있음
→ 자연어 mentioned themes를 active로 승격
→ 기존 API 선택 themes는 backup으로 이동

명시적 테마 제외
→ active와 backup 모두에서 제거

active 3개 초과
→ 자연어 순서 기준 상위 3개 active
→ 나머지는 backup
```

예:

```json
{
  "api_themes": ["sea_coast", "healing_rest"],
  "mentioned_theme_ids": ["art_sense"],
  "resolved_theme_state": {
    "active_theme_ids": ["art_sense"],
    "backup_theme_ids": ["sea_coast", "healing_rest"],
    "excluded_theme_ids": []
  }
}
```

`resolved_theme_state`는 모델 출력이 아니라 Playground가 계산한 평가용
결과다. API 입력 배열 자체는 변경되지 않는다.

### MVP vibe tag 후보

브레인스토밍 taxonomy에서 현재 단계에 적용하기 쉽고 기존 분류와 겹치지
않는 항목만 남겼다.

```text
Vibe — 정서
romantic, nostalgic, cozy, meditative, refreshing, inspiring

Vibe — 구체적 경관
open_view, panoramic_view, sunrise_view, sunset_view, night_view,
flower_view, autumn_leaves

별도 experience property
photo_spot, picnic, drive_course

별도 companion property
family, kids, couple, solo, pet, parents, seniors

별도 place property
indoor_outdoor: indoor | outdoor | mixed | any
walking_load: low | medium | high | any
visit_duration: short | medium | long | any
```

제외한 범위:

- 6대 테마와 중복: `healing`, `artistic`, `historic`, `traditional`, `local`
- `lclsSystm3` subtype과 중복: `museum`, `gallery`, `temple`, `beach` 등
- 혼잡도와 중복: `quiet`, `lively`, `hidden_gem`
- 별도 장소 metadata와 중복: `indoor`, `outdoor`, walking/activity level,
  체류시간, 주차

Intent의 `desired_vibe_tags`와 Attraction metadata의 `vibe_tags`는 같은
canonical enum을 사용해야 직접 교집합 점수를 계산할 수 있다.

경험·동행·이용 특성은 vibe 교집합과 별도로 점수화한다. 특히
`walking_load`와 `visit_duration`은 Planner의 일정 배치에도 사용한다.

현재 Bedrock GPT Structured Outputs는 `uniqueItems`를 지원하지 않으므로,
중복 금지는 프롬프트와 후단 validator에서 처리한다. `maxItems=5`와 enum
제약은 schema에 유지한다.

### 혼잡도 선호와 vibe 분리

`crowd_preference`는 `vibe_tags`와 별도 신호다.

```text
low_crowd  → 조용함, 한적함, 사람이 적음, 덜 붐빔
high_crowd → 활기, 핫플, 인기 장소, 사람 많은 분위기
neutral    → 방문객 규모 선호 없음 또는 방향 불명
```

`rag_test`의 기존 scoring 방향은 후단 결정적 코드에서 다음처럼 연결한다.

```python
CROWD_PREFERENCE_WEIGHTS = {
    "low_crowd": 4.0,
    "high_crowd": -1.5,
    "neutral": 2.5,
}
```

LLM은 `crowd_preference` enum만 추출하며 가중치 수치를 생성하지 않는다.
방문객 통계가 없는 도시는 `rag_test` 정책과 동일하게 혼잡도 index `0.5`로
처리하는 것이 권장된다.

`실시간 혼잡도를 알려줘`는 방문객 규모 선호가 아니므로
`crowd_preference="neutral"`이고, `실시간 혼잡도`를
`unsupported_conditions`에 추가한다.

## 사전 조건

- Python 3.12
- 프로젝트 의존성 설치
- Bedrock 모델 접근 권한
- `bedrock:InvokeModel` 권한

PowerShell 환경변수 예시:

```powershell
$env:LOVV_AWS_REGION = "us-east-1"
$env:LOVV_AWS_PROFILE = "lovv-dev"
$env:LOVV_LLM_MODEL_ID = "your-bedrock-model-or-inference-profile-id"
```

기본 AWS credential chain이나 IAM role을 사용하면 profile은 생략할 수 있다.

## 요청 미리보기

AWS 호출 없이 최종 Converse 요청을 확인한다.

```powershell
uv run python intent_playground/run.py --dry-run
```

## Bedrock 실행

```powershell
uv run python intent_playground/run.py
```

한 케이스를 세 번씩 반복:

```powershell
uv run python intent_playground/run.py --repeat 3
```

특정 케이스만 실행:

```powershell
uv run python intent_playground/run.py --case-id IN-N02
```

다른 파일 조합으로 실행:

```powershell
uv run python intent_playground/run.py `
  --prompt intent_playground/experiments/prompt.v2.md `
  --schema intent_playground/experiments/schema.v2.json `
  --cases intent_playground/experiments/cases.v2.jsonl
```

모델과 AWS 설정을 CLI에서 지정할 수도 있다.

```powershell
uv run python intent_playground/run.py `
  --model-id "your-model-id" `
  --region "us-east-1" `
  --profile "lovv-dev"
```

## 케이스 형식

`cases.jsonl`의 각 행은 독립 JSON 객체다.

```json
{
  "id": "IN-N02",
  "description": "soft preference 분리",
  "input": {
    "api_structured_input": {},
    "conversation_summary": null,
    "messages": []
  },
  "assertions": [
    {
      "path": "cleaned_raw_query",
      "op": "contains",
      "value": "바다"
    },
    {
      "path": "soft_preference_query",
      "op": "contains",
      "value": "조용"
    },
    {
      "path": "crowd_preference",
      "op": "equals",
      "value": "low_crowd"
    }
  ]
}
```

지원 assertion 연산자:

- `equals`
- `not_equals`
- `contains`
- `not_contains`
- `includes`
- `not_includes`
- `is_null`
- `not_null`
- `length_equals`

`path`는 `soft_preference_query` 또는
`core_change_requests.0.field` 같은 점 표기법을 사용한다.

## 출력

기본 출력 경로:

```text
intent_playground/results/<UTC timestamp>/
├── requests.jsonl
├── results.jsonl
└── summary.json
```

`results.jsonl`에는 다음이 기록된다.

- case ID와 반복 번호
- 모델 ID
- prompt/schema 파일 SHA-256
- latency
- parsed structured output
- raw Bedrock response
- assertion 결과
- 오류

AWS request metadata 전체를 그대로 저장하지는 않는다. 입력에 개인정보나
민감정보를 넣지 않아야 한다.

## 프롬프트 실험 절차

1. 현재 `prompt.md`, `schema.json`, `cases.jsonl`을 복사해 실험 버전을 만든다.
2. `--dry-run`으로 요청 구조와 schema serialization을 확인한다.
3. 동일 케이스를 `--repeat 3` 이상 실행한다.
4. `summary.json`에서 pass rate와 case별 실패를 확인한다.
5. 출력 구조를 변경했다면 assertion path도 함께 변경한다.
6. 채택할 프롬프트와 schema만 운영 prompt registry 및 Intent validator에 별도 반영한다.
7. 운영 반영 후 `tests/test_intent.py`, `tests/test_harness.py`를 다시 실행한다.

## 주의 사항

- Playground schema 통과는 운영 business validation 통과를 의미하지 않는다.
- core API field는 LLM 출력에 포함하지 않으며 자연어로 덮어쓰지 않는다.
- 운영 반영 시에는 의미별 추출 필드만 명시적으로 병합해야 한다.
- `crowd_preference`는 vibe tag 필터가 아니라 도시 방문객 통계 가중치 선택에
  사용한다.
- `core_change_requests`가 존재할 때 clarification 또는 UI structured input
  갱신을 요구할지는 Supervisor가 결정한다.
- 출력 구조를 운영에 반영하려면 Intent 전용 enrichment result와 validator,
  Supervisor merge 계약을 함께 변경해야 한다.
- 모델별 Structured Outputs 지원 여부와 schema 제한이 다를 수 있다.
- 반복 횟수와 케이스 수만큼 Bedrock 호출 비용이 발생한다.
