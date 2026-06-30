# Tasks: V2 Profile Agent + Intent 확장 + Tool 구조화

## Issue / Branch 생성 가이드

```
GitHub Issue #1: "feat: Profile Agent 순수 계산 로직 구현"
GitHub Issue #2: "feat: State/Schema V2 확장 (ProfileState + IntentState + CandidateEvidenceInput)"
GitHub Issue #3: "feat: Tool I/O contract 구조화 (Gateway 분리 준비)"
GitHub Issue #4: "feat: Profile DDB repository + harness 병렬 배선"

Branch: feature/v2-profile-intent-tool
Base: main
```

---

## Task 1: Profile Agent 순수 계산 로직 [x] {issue: #1}

### 1.1 `src/lovv_agent/agents/profile.py` 생성 [ ]

- [ ] Profile 상수 정의
  ```python
  PROFILE_ACTIVATION_SAVED_TRIP_COUNT = 3
  PROFILE_ALPHA = 1.5
  PROFILE_MIN_WEIGHT = 0.8
  PROFILE_MAX_WEIGHT = 1.3
  PROFILE_SCORE_CAP = 0.05
  SUPPORTED_THEME_COUNT = 5
  ```
- [ ] `THEME_ID_TO_LABEL` 매핑 정의
  ```python
  THEME_ID_TO_LABEL: dict[str, str] = {
      "sea_coast": "바다·해안",
      "nature_trekking": "자연·트레킹",
      "history_tradition": "역사·전통",
      "art_sense": "예술·감성",
      "healing_rest": "온천·휴양",
  }
  ```
- [ ] `ProfileRecord` dataclass 정의 (frozen, slots)
  - `saved_trip_count: int`
  - `saved_theme_counts: dict[str, int]`
- [ ] `ProfileResult` dataclass 정의 (frozen, slots)
  - `profile_active: bool`
  - `effective_theme_weights: dict[str, float] | None`
  - `audit: dict[str, Any]`
- [ ] `compute_theme_weights(profile: ProfileRecord, active_required_themes: tuple[str, ...]) -> ProfileResult` 구현
  - V2_24 §4.4 수식 그대로 구현
  - `saved_trip_count < 3` → 비활성 (weights=None)
  - 균등 기준 = `1 / SUPPORTED_THEME_COUNT` (하드코딩 0.2 아님)
  - `active_required_themes`에 포함된 label만 결과에 포함
  - `round(..., 6)` 정밀도

### 1.2 `tests/test_profile_weights.py` 생성 [ ]

- [ ] 비활성 케이스: `saved_trip_count=0` → `profile_active=False`, `effective_theme_weights=None`
- [ ] 비활성 경계: `saved_trip_count=2` → 비활성
- [ ] 활성 최소: `saved_trip_count=3`, confidence=1.0
- [ ] 단일 theme 편중: `sea_coast=5, 나머지=0` → `바다·해안` weight = 1.3 (max clamp)
- [ ] 균등 분포: 모든 theme_count=2 → weight ≈ 1.0
- [ ] active에 없는 theme 미포함 확인
- [ ] `total_theme_count=0` → observed_ratio = 0.2 (균등 기본)
- [ ] confidence ramp: `saved_trip_count=4` → confidence=1.0 (cap)

---

## Task 2: State/Schema V2 확장 [x] {issue: #2}

### 2.1 `src/lovv_agent/state.py` 수정 [ ]

- [ ] `ProfileState` dataclass 추가
  ```python
  @dataclass(slots=True)
  class ProfileState:
      saved_trip_count: int = 0
      profile_theme_weights: dict[str, float] = field(default_factory=dict)
      effective_theme_weights: dict[str, float] | None = None
      applied_persona_id: str | None = None
      audit: dict[str, Any] = field(default_factory=dict)
  ```
- [ ] `UnifiedAgentState`에 `profile: ProfileState = field(default_factory=ProfileState)` 추가
- [ ] `STATE_GROUPS`에 `"profile"` 추가
- [ ] `IntentState`에 V2 필드 추가 (모두 기본값)
  - `transport_pref: str = "unknown"`
  - `congestion_pref: str = "neutral"`
  - `contradictions: tuple[str, ...] = ()`
  - `ambiguity_signals: tuple[str, ...] = ()`
- [ ] `__all__`에 `ProfileState` 추가

### 2.2 `src/lovv_agent/models/schemas.py` 수정 [ ]

- [ ] `CandidateEvidenceInput`에 필드 추가
  - `theme_weights: dict[str, float] | None = None`
  - `transport_pref: str = "unknown"`
  - `congestion_pref: str = "neutral"`
- [ ] `__post_init__`에 validation 추가 (optional mapping / choice)
- [ ] `from_mapping()`에서 새 필드 읽기 (default 있으므로 하위 호환)
- [ ] `TRANSPORT_PREFS` / `CONGESTION_PREFS` enum tuple 정의

### 2.3 기존 테스트 통과 확인 [ ]

- [ ] `pytest tests/` 전체 실행 → 212 tests pass

---

## Task 3: Tool I/O Contract 구조화 [x] {issue: #3}

### 3.1 `src/lovv_agent/tools/contracts.py` 생성 [ ]

- [ ] `SearchAttractionsInput` dataclass
  - `query_vector: list[float]`
  - `city_id: str | None`
  - `theme: str | None`
  - `top_k: int = 50`
  - `filters: dict[str, Any] | None = None`
- [ ] `SearchAttractionsOutput` dataclass
  - `candidates: tuple[dict[str, Any], ...]`
  - `retrieval_count: int`
  - `truncated: bool = False`
- [ ] `LookupFestivalSeedsInput` dataclass
  - `city_id: str`
  - `travel_month: int`
  - `travel_year: int`
  - `max_candidates: int = 30`
- [ ] `LookupFestivalSeedsOutput` dataclass
  - `festivals: tuple[dict[str, Any], ...]`
  - `retrieval_count: int`
- [ ] `EnrichPlaceDetailsInput` dataclass
  - `place_keys: tuple[dict[str, str], ...]`  (PK/SK pairs)
- [ ] `EnrichPlaceDetailsOutput` dataclass
  - `details: tuple[dict[str, Any], ...]`
  - `missing_keys: tuple[dict[str, str], ...]`
- [ ] `EmbedQueryInput` dataclass
  - `text: str`
  - `model_id: str | None = None`
- [ ] `EmbedQueryOutput` dataclass
  - `vector: list[float]`
  - `dimension: int`

### 3.2 `tests/test_tool_contracts.py` 생성 [ ]

- [ ] 각 contract의 생성 + to_dict() round-trip 검증
- [ ] 필수 필드 누락 시 에러 확인
- [ ] 기본값 정상 적용 확인

### 3.3 기존 tool 내부에서 contract 사용 (선택적 리팩토링) [ ]

- [ ] `DestinationSearchTool.search_candidates()`가 내부적으로 `SearchAttractionsInput` 사용
- [ ] 외부 시그니처는 유지 (하위 호환) — contract는 내부 구현 세부사항

---

## Task 4: Profile DDB Repository + Harness 배선 [x] {issue: #4}

### 4.1 `src/lovv_agent/repositories/profile_dynamodb.py` 생성 [ ]

- [ ] `ProfileRepository` class 정의
  - `__init__(self, client, table_name: str)`
  - `get_profile(self, actor_id: str) -> ProfileRecord | None`
  - PK: `ACTOR#{actor_id}`, SK: `PROFILE#v1`
  - 존재하지 않으면 `None` 반환
  - `saved_trip_count`, `saved_theme_counts` 추출

### 4.2 `src/lovv_agent/config.py` 수정 [ ]

- [ ] `ProfileSettings` dataclass 추가
  ```python
  @dataclass(frozen=True, slots=True)
  class ProfileSettings:
      table_name: str = "LovvUserProfile"
      enabled: bool = False
  ```
- [ ] `RuntimeConfig`에 `profile: ProfileSettings` 추가
- [ ] `ENV_KEYS`에 `LOVV_PROFILE_TABLE`, `LOVV_PROFILE_ENABLED` 추가
- [ ] `from_env()`에서 profile settings 읽기

### 4.3 `src/lovv_agent/harness.py` 수정 — Profile 주입 [ ]

- [ ] `_run_profile(state: UnifiedAgentState, repository: ProfileRepository | None) -> ProfileResult` 함수 추가
  - `user_id`가 없거나 repository가 None이면 비활성 결과 반환
  - `ProfileRecord` 조회 → `compute_theme_weights()` 호출
- [ ] `intent_node` 내부 또는 직후에 Profile 결과를 `state.profile`에 기록
- [ ] `effective_theme_weights`가 있으면 `CandidateEvidenceInput`의 `theme_weights`에 주입

### 4.4 `src/lovv_agent/harness.py` 수정 — ThreadPool 병렬 [ ]

- [ ] `ThreadPoolExecutor(max_workers=2)`로 Intent + Profile 동시 실행
- [ ] Intent가 `CandidateEvidenceInput`을 만든 후 Profile weights를 `replace()`로 주입
- [ ] timeout 설정 (Intent: 15s, Profile: 5s)
- [ ] Profile 실패 시 graceful degradation (weight 미주입, 기존 동작 유지)

### 4.5 테스트 [ ]

- [ ] Profile DDB repository mock 단위 테스트
- [ ] harness 병렬 배선 통합 테스트 (Profile 비활성 시 기존 동작 확인)
- [ ] `pytest tests/` 전체 → 기존 212 + 신규 테스트 모두 pass

---

## 실행 순서 요약

```
Week 1:
  Task 1 (Profile 순수 계산 + 테스트)     ← 독립, 즉시 시작
  Task 2 (State/Schema 확장)              ← 독립, 즉시 시작
  Task 3 (Tool contract 정의)             ← 독립, 즉시 시작

Week 2:
  Task 4 (DDB repository + harness 배선)  ← Task 1, 2 완료 후
  전체 테스트 + PR 제출
```

---

## GitHub Issue 생성 명령 (참고)

```bash
gh issue create --title "feat: Profile Agent 순수 계산 로직 구현" \
  --body "V2_24 §4.4 수식 기반 compute_theme_weights() 구현 + 단위 테스트" \
  --label "feature,v2,profile"

gh issue create --title "feat: State/Schema V2 확장 (ProfileState + IntentState + CandidateEvidenceInput)" \
  --body "ProfileState 추가, IntentState V2 필드, CandidateEvidenceInput에 theme_weights/transport/congestion 추가" \
  --label "feature,v2,schema"

gh issue create --title "feat: Tool I/O contract 구조화 (Gateway 분리 준비)" \
  --body "SearchAttractionsInput/Output 등 tool contract dataclass 정의. Lambda 미배포, 인터페이스만." \
  --label "feature,v2,tool"

gh issue create --title "feat: Profile DDB repository + harness 병렬 배선" \
  --body "ProfileRepository DDB read + harness에서 Intent∥Profile ThreadPool 병렬 실행" \
  --label "feature,v2,profile,harness"
```

## Branch 생성

```bash
git checkout main
git checkout -b feature/v2-profile-intent-tool
```
