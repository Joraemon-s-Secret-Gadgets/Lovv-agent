# Design: V2 Profile Agent + Intent 확장 + Tool 구조화

## 개요

V2_24 계약 문서의 ✅ 항목을 기준으로, Profile Agent 구현 / Intent V2 계약 확장 / Tool 인터페이스 분리 준비를 수행한다.
기존 212 테스트를 깨지 않으면서 `src/lovv_agent/` 위에 증분하는 방식.

---

## 아키텍처 결정

### 1. Profile Agent — 단일 process 내 순수 함수 + DDB read adapter

```
[Request] ─┬─ Intent Agent (LLM parse) ──────┐
            │                                   │
            └─ Profile Agent (DDB GetItem) ────┘
                                                ▼
                                  [JOIN: theme_weights 주입]
                                                ▼
                                  [city_select_input 조립]
```

- Profile Agent는 LLM을 사용하지 않음 (pure-code)
- DynamoDB `LovvUserProfile` 테이블에서 `ACTOR#{actorId}` / `PROFILE#v1` 조회
- `compute_theme_weights()` 순수 함수로 weight 계산
- 결과를 `intent.city_select_input.theme_weights`에 주입
- Intent와 Profile은 ThreadPoolExecutor로 병렬 실행 (Phase 7)

### 2. Intent V2 — 기존 코드 위 하위 호환 확장

- `IntentState`에 V2 필드 추가 (모두 기본값 → 기존 테스트 불변)
- `CandidateEvidenceInput`에 `theme_weights`, `transport_pref`, `congestion_pref` 추가
- 🔶 제안 항목 (PreferenceConstraint, ModifyIntent 등)은 타입 stub만 예약

### 3. Tool 구조화 — Lambda 미배포, 인터페이스만 분리

```
src/lovv_agent/tools/
    contracts.py         ← Input/Output dataclass 정의 (신규)
    destination_search.py  ← 기존 tool, contract 기반으로 내부 리팩토링
    dynamo_lookup.py       ← 기존 tool, contract 기반으로 내부 리팩토링
```

- 각 I/O tool에 `SearchAttractionsInput` / `SearchAttractionsOutput` 등 명시적 계약
- 현재는 in-process adapter가 직접 호출
- 나중에 Gateway Lambda 전환 시 adapter만 교체 (harness/graph 코드 불변)

---

## State 변경 요약

### UnifiedAgentState 확장

```python
@dataclass(slots=True)
class ProfileState:
    """Profile Agent read-side output."""
    saved_trip_count: int = 0
    profile_theme_weights: dict[str, float] = field(default_factory=dict)
    effective_theme_weights: dict[str, float] | None = None
    applied_persona_id: str | None = None
    audit: dict[str, Any] = field(default_factory=dict)
```

- `UnifiedAgentState`에 `profile: ProfileState` 추가
- `STATE_GROUPS`에 `"profile"` 추가

### IntentState 확장

```python
# V2 추가 필드 (모두 기본값)
transport_pref: str = "unknown"
congestion_pref: str = "neutral"
contradictions: tuple[str, ...] = ()
ambiguity_signals: tuple[str, ...] = ()
```

### CandidateEvidenceInput 확장

```python
# V2 추가 필드
theme_weights: dict[str, float] | None = None
transport_pref: str = "unknown"
congestion_pref: str = "neutral"
```

---

## 파일 구조

```
src/lovv_agent/
    agents/
        profile.py              ← 신규: Profile Agent (상수 + 계산 + node)
    models/
        schemas.py              ← 수정: CandidateEvidenceInput 필드 추가
    state.py                    ← 수정: ProfileState + IntentState 확장
    config.py                   ← 수정: ProfileSettings 추가
    tools/
        contracts.py            ← 신규: Tool I/O contract dataclasses
        destination_search.py   ← 수정: contract 기반 내부 리팩토링
        dynamo_lookup.py        ← 수정: contract 기반 내부 리팩토링
    repositories/
        profile_dynamodb.py     ← 신규: Profile DDB read adapter
    harness.py                  ← 수정: Profile 주입 + 병렬 배선

tests/
    test_profile_weights.py     ← 신규: Profile 순수 계산 단위 테스트
    test_tool_contracts.py      ← 신규: Tool contract round-trip 테스트
```

---

## 의존 관계 (실행 순서 결정)

```
Task 1: Profile 순수 계산 ──────────────────┐
Task 2: Profile 단위 테스트                   │
Task 3: ProfileState + State 확장 ───────────┤── 의존 없음
Task 4: IntentState/Schema V2 필드 추가 ─────┤
Task 5: Tool contract 정의 ──────────────────┘
                                              │
Task 6: Profile DDB repository ──────────────┤── Task 1, 3 의존
Task 7: harness 병렬 배선 ───────────────────┘── Task 1, 3, 4, 6 의존
```

---

## 브랜치 전략

```
main (v1.0 태그)
  └── feature/v2-profile-intent-tool
        ├── commit: "feat(profile): add compute_theme_weights pure function"
        ├── commit: "test(profile): unit tests for weight calculation"
        ├── commit: "feat(state): add ProfileState + IntentState V2 fields"
        ├── commit: "feat(schema): add theme_weights/transport/congestion to CandidateEvidenceInput"
        ├── commit: "feat(tools): add tool I/O contract dataclasses"
        ├── commit: "feat(profile): add DynamoDB profile repository"
        └── commit: "feat(harness): wire Profile Agent + ThreadPool parallel"
```

---

## 성공 기준

1. `compute_theme_weights()` 단위 테스트 전부 통과
2. `saved_trip_count < 3` → `theme_weights = None` (비활성)
3. `saved_trip_count >= 3` → active theme에만 weight 주입
4. 기존 212 테스트 100% 통과 (하위 호환)
5. Tool contract dataclass가 정의되고 round-trip 테스트 통과
6. Profile DDB repository가 mock으로 단위 테스트 통과
7. harness에서 Intent ∥ Profile 병렬 실행 동작 확인
