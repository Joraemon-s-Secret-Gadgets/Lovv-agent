# data_collect ELT Vector 적재 작업 지시서 (TDD + BDD)

> 대상: `data_collect` 프로젝트를 담당하는 Claude
> 방법론: **TDD + BDD (pytest-bdd + .feature)**
> 작성 근거: 소비자 프로젝트 `Lovv-agent`의 S3 Vector 소비 계약 (이 문서에 전량 내장)
> 작성일: 2026-06-17

---

## 0. 한 줄 목적

관광지(attraction) 원천 데이터를 **S3 Vector 인덱스에 적재**하는 ELT 파이프라인을, 아래에 명시된
**소비자 계약을 인수 기준으로 삼아 TDD+BDD 방식으로** 구현한다.

핵심 원칙: **ELT의 "완료 정의"는 임의로 정하지 않는다.** 산출 레코드 형태는 이미 소비자(Lovv-agent의
`DestinationSearchTool`)가 기대하는 스키마로 고정돼 있다. 이 지시서의 §2 계약이 곧 인수 기준(acceptance
criteria)이며 `.feature` 시나리오의 근거다.

---

## 1. 작업 범위

### In scope
- 관광지 원천 → 임베딩 → S3 Vector 레코드 변환/검증/적재 (Extract → Transform → Load).
- `place_id` 정규화, 메타데이터 매핑, 적재 제외 테마 필터.
- pytest-bdd `.feature` 인수 시나리오 + 순수 함수 단위 TDD.

### Out of scope (현재 단계에서 하지 말 것)
- **도시(city) 벡터화** — 현재 인덱스는 attraction 단일 엔티티만 사용. (별도 합의 전까지 제외)
- **축제(festival) 벡터화** — 축제는 벡터가 아니라 DynamoDB 시드로 다룬다.
- **맛집(restaurant) 벡터화** — 현재 런타임 경로에서 의도적으로 제외.
- **월별 기상 정보를 벡터 메타데이터에 포함** — 기상은 정적 임베딩 대상이 아니라 DynamoDB로 분리하고
  런타임 신호로 결합한다. (벡터 메타에 넣지 말 것)

---

## 2. 산출물 계약 (★ 인수 기준 — 변경 금지)

각 attraction 벡터 레코드는 다음을 만족해야 한다. (소비자 `normalize_attraction_candidate` 기준)

### 2.1 레코드 최상위
| 필드 | 규칙 |
| --- | --- |
| `key` | chunk 식별자 (벡터 단위 고유 키) |
| 벡터값 | 임베딩 벡터. 차원 **1024**, **normalize=True** (L2 정규화) 가정. `float32`로 저장 |
| `distance` | 적재 시 산출 대상 아님(쿼리 시 반환값). 적재 책임 아님 |

### 2.2 metadata (필수)
| 필드 | 규칙 / 용도 |
| --- | --- |
| `metadata.entity_type` | **반드시 `"attraction"`**. 다른 값이면 소비자가 예외로 거부 |
| `metadata.place_id` | chunk suffix 제거된 **안정 place 식별자** (§3 규칙). 없으면 소비자가 key에서 유도하므로 가급적 채울 것 |
| `metadata.city_id` | 그룹핑·앵커 필터 키. 비어 있으면 안 됨 |
| `metadata.city_name_ko` | 표시/그룹 보조 (선택, 그러나 권장) |
| `metadata.title` | 표시 + 제목 기반 중복제거. **비어 있으면 적재 거부** |
| `metadata.theme_tags` | 문자열 배열. 테마 필터·게이트·쿼터의 근거 |
| `metadata.latitude`, `metadata.longitude` | 숫자(부동소수). 점수·경로 힌트 |
| `metadata.ddb_pk`, `metadata.ddb_sk` | DynamoDB 상세 enrichment 포인터 (선택, 그러나 권장) |

### 2.3 검증 규칙
- 필수 텍스트 필드(`entity_type`, `city_id`, `title`)는 공백만 있는 문자열을 허용하지 않는다.
- `latitude/longitude`는 숫자여야 하며 bool 금지.
- `theme_tags`는 문자열의 리스트/튜플이어야 한다.
- 위반 시 적재를 중단하고 스키마 오류를 발생시킨다. (소비자와 동일하게 `SchemaValidationError` 류 권장)

---

## 3. place_id 정규화 규칙 (소비자와 1:1 일치 필수)

`metadata.place_id`가 있으면 그대로 사용. 없으면 `key`에서 아래 순서로 유도한다.

1. `key`를 `#`로 분리했을 때 조각이 **3개 이상이고 마지막 조각이 숫자**면 → 마지막 조각을 떼고 `#`로
   재결합. 예: `"명소A#서울#3"` → `"명소A#서울"`.
2. 그 외에는 다음 정규식으로 chunk suffix 제거:
   `(?i)(?:::|#|/|_|-)?chunk(?:[-_:#/])?\d+$`
   예: `"명소A::chunk-2"` → `"명소A"`.
3. 결과가 빈 문자열이면 오류.

> ELT가 적재 시점에 `place_id`를 직접 채워 넣으면 소비자가 유도할 필요가 없어 가장 안전하다. **권장: ELT에서
> place_id를 명시적으로 산출해 메타에 저장.**

---

## 4. 적재 제외 테마 필터 (★ 중요)

다음 테마 라벨을 가진 원천은 **attraction 벡터로 적재하지 않는다.** (소비자가 place 검색에서 배제하는 라벨과
동일하게 맞춘다.)

- 미식 계열: `food_local`, `미식`, `미식·노포`, `미식/노포`
- 축제 계열: `festival`, `festival_event`, `event`, `축제`, `축제·이벤트`, `축제/이벤트`

`theme_tags`가 이 라벨을 포함하면 해당 레코드를 적재 대상에서 제외한다. (미식은 선택 도시 외부 foodSearch
링크로, 축제는 DynamoDB 시드로 별도 처리되기 때문이다.)

---

## 5. BDD 방법: `.feature` 인수 시나리오

아래 시나리오를 그대로 출발점으로 삼는다. (red 상태로 시작)

```gherkin
Feature: 관광지 S3 Vector 적재 (ELT)

  Scenario: 관광지 원천을 attraction 벡터 레코드로 변환한다
    Given 유효한 관광지 원천 레코드가 주어지고
    When ELT 변환을 실행하면
    Then metadata.entity_type 은 "attraction" 이고
    And place_id, city_id, title, theme_tags, latitude, longitude 가 채워진다
    And ddb_pk, ddb_sk 포인터가 채워진다

  Scenario Outline: chunk 키에서 안정 place_id 를 유도한다
    Given 키가 "<key>" 인 청크가 주어지고
    When place_id 를 정규화하면
    Then place_id 는 "<place_id>" 가 된다

    Examples:
      | key            | place_id   |
      | 명소A#서울#3    | 명소A#서울 |
      | 명소A::chunk-2  | 명소A      |

  Scenario: 미식 테마는 attraction 인덱스에 적재하지 않는다
    Given theme_tags 에 "미식·노포" 가 포함된 원천이 주어지고
    When 적재 필터를 적용하면
    Then 해당 레코드는 적재 대상에서 제외된다

  Scenario: 축제 테마는 attraction 인덱스에 적재하지 않는다
    Given theme_tags 에 "축제·이벤트" 가 포함된 원천이 주어지고
    When 적재 필터를 적용하면
    Then 해당 레코드는 적재 대상에서 제외된다

  Scenario: 필수 메타가 비면 적재를 거부한다
    Given title 이 비어 있는 원천이 주어지고
    When 검증을 실행하면
    Then 스키마 오류로 적재가 중단된다

  Scenario: 임베딩 차원이 다르면 적재를 거부한다
    Given 임베딩 차원이 1024 가 아닌 벡터가 주어지고
    When 적재 전 검증을 실행하면
    Then 차원 불일치 오류로 적재가 중단된다
```

pytest-bdd 바인딩: step 파일에서 `scenarios("attraction_ingest.feature")`로 연결하고, `@given/@when/@then`
step이 §6의 순수 함수를 호출하도록 작성한다.

---

## 6. TDD 단위 레이어 (먼저 빨강 → 최소 구현 → 리팩터)

ELT를 3계층으로 분리하고, AWS 없이 테스트 가능한 순수 함수부터 TDD를 돌린다.

1. **Transform (순수 함수, 1순위)**
   - `to_place_id(key, metadata) -> str` (§3 규칙)
   - `to_record_metadata(source) -> dict` (§2.2 매핑)
   - `is_loadable(theme_tags) -> bool` (§4 제외 필터)
   - AWS·네트워크 의존 없음 → red/green 가장 빠름.

2. **Validate**
   - `validate_record(record)` : 필수 필드/타입/차원 검증, 위반 시 예외.

3. **Load (어댑터, 마지막)**
   - S3 Vector `put_vectors` 호출은 **주입식 fake/stub 클라이언트**로 단위 테스트.
     (소비자가 `S3VectorClient` Protocol을 주입식으로 쓰는 패턴과 동일하게.)
   - 실제 AWS 호출은 별도 smoke 테스트로 분리하고 **환경변수 게이트**로 기본 skip
     (예: `DATA_COLLECT_ENABLE_AWS_SMOKE=1`일 때만 실행).

---

## 7. 권장 디렉터리 구조

```
data_collect/
  features/
    attraction_ingest.feature
    steps/
      test_attraction_ingest_steps.py    # @given/@when/@then
  tests/
    test_transform.py                    # 순수 단위 TDD
    test_validate.py
    test_load.py                         # stub 클라이언트 주입
  src/data_collect/elt/
    extract.py
    transform.py
    load.py
  pyproject.toml                         # dev deps: pytest, pytest-bdd
```

---

## 8. 진행 순서 (red-green-refactor)

1. `attraction_ingest.feature` 작성 → 실패.
2. `test_transform.py`에 `to_place_id` / `is_loadable` 단위 테스트 작성 → 실패.
3. 최소 구현으로 green.
4. `to_record_metadata` + `validate_record` 확장 (필수 필드/차원 검증).
5. Load 어댑터를 stub 주입으로 green.
6. 마지막에 실제 S3 Vector 어댑터 + env 게이트 smoke 추가.
7. 전체 `.feature` 시나리오 green 확인 → 리팩터.

---

## 9. 완료 정의 (Definition of Done)

- §5의 모든 `.feature` 시나리오가 green.
- §6의 Transform/Validate 단위 테스트가 green (커버리지 핵심 경로 100%).
- 제외 테마(§4)·필수 검증(§2.3)·place_id 정규화(§3)가 소비자 규칙과 **동일**하게 동작.
- 실제 AWS 적재 smoke는 env 게이트로 분리되어 기본 CI에서 skip.

---

## 10. 제약 및 주의

- **생산자-소비자 drift 방지**: ELT가 산출하는 메타 스키마와 제외 테마·place_id 규칙은 Lovv-agent의
  `destination_search.py` 계약과 **단일 소스**로 묶는 것을 강력 권장(공유 상수/스키마 모듈). 그래야 한쪽만
  바뀌어도 테스트가 즉시 깨진다.
- 이 지시서는 **소비자 계약 기반의 일반 가이드**다(신뢰도 중상). `data_collect`의 실제 원천 데이터 스키마를
  확인하면 §2 매핑과 §5 Examples를 더 정밀하게 확정할 수 있다. 원천 필드명이 계약과 다르면 Transform 계층에서
  매핑으로 흡수하고, 매핑 규칙 자체를 테스트로 고정할 것.
- 도시 벡터화·월별 기상은 **이번 범위 밖**이다. 필요해지면 별도 지시서로 분리한다.
```
