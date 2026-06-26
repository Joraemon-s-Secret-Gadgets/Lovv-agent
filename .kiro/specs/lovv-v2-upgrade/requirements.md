# Requirements Document — Lovv V2 Upgrade (Gateway 제외)

> Kiro spec · Phase 1 (Requirements) · date 2026-06-23
> Scope: `LOVV_V2_UPGRADE_SPEC.md`의 §3~§7·§9를 EARS 요구사항으로 정리.
> **Gateway는 본 스펙 범위에서 제외**(이후 별도 spec). V1(Observability·CI/CD)은 전제로 둔다.

## Introduction

Lovv V2는 임의 자동 일정 생성을 폐기하고, 사용자가 장소를 하나씩 고르는 **대화형 HITL 빌더
루프**로 구조를 진화시킨다. 동시에 노드 내부 I/O 병렬화, 단기/장기 메모리 계층, Cognito 기반
가명화 Identity 경계를 도입한다. 충분성은 별도 evaluator 노드 없이 **결정론 순회**로 처리하고,
출력과 검증(eval)은 **하나의 통합 노드**로 합친다. 본 문서는 구현 전 "무엇을 만드는가"를 EARS로
규정하며, AgentCore Gateway는 범위에서 제외한다.

## Requirements

### Requirement 1 — Cognito 기반 가명화 Identity 경계
**User Story:** Lovv 운영자로서, 진입 사용자를 재식별 불가능한 직키 없이 다루고 싶다. 그래야
개인화는 유지하되 저장소 유출 시 신원 노출을 막을 수 있다.

#### Acceptance Criteria
1. WHEN 요청이 진입하면 THE SYSTEM SHALL Cognito JWT의 서명·iss·aud·exp를 검증한 뒤에만 `sub`를 신뢰한다.
2. WHEN `sub`가 확보되면 THE SYSTEM SHALL `actorId = HMAC_SHA256(sub, PSEUDONYM_SECRET)`를 계산해 전 계층에 전달한다.
3. THE SYSTEM SHALL `PSEUDONYM_SECRET`을 Secrets Manager(KMS)에서 컨테이너당 1회 로드·캐시하고 HMAC을 로컬 계산한다(요청당 KMS 호출 금지).
4. THE SYSTEM SHALL raw `sub`·이메일·실신원을 DynamoDB·S3·AgentCore Memory 어디에도 저장하지 않는다.
5. IF JWT 검증 실패 또는 `sub` 부재이면 THEN THE SYSTEM SHALL 안전 폴백(임시 세션키)으로 처리하고 영속 저장하지 않는다.

### Requirement 2 — 단기 메모리 / Checkpointer (interrupt·resume)
**User Story:** Lovv 사용자로서, 같은 대화에서 빌더 루프를 이어가고 싶다. 그래야 멀티턴으로 일정을 쌓을 수 있다.

#### Acceptance Criteria
1. WHERE checkpointer가 비활성이면 THE SYSTEM SHALL 현재와 동일한 무상태 동작을 유지한다(기본값).
2. WHEN `LOVV_MEMORY_ENABLED=true`이면 THE SYSTEM SHALL AgentCore Memory에 checkpoint blob과 세션 컨텍스트를 공유 수명으로 저장한다.
3. THE SYSTEM SHALL `actorId`(가명)와 `session_id`(thread_id)로 checkpoint를 격리한다.
4. WHILE 후보 제시 지점에 있으면 THE SYSTEM SHALL `interrupt()`로 중단하고 동일 `thread_id`로 resume할 수 있어야 한다.
5. IF 상태 직렬화 round-trip(`unified_state_from_dict(s.to_dict()) == s`)이 통과하지 않으면 THEN THE SYSTEM SHALL 영속 saver를 활성화하지 않는다.

### Requirement 3 — 장기 메모리 수명주기 (DynamoDB TTL → S3 콜드)
**User Story:** Lovv 운영자로서, 개인화·분석 데이터를 가명 상태로 장기 보관하되 삭제권을 통제하고 싶다.

#### Acceptance Criteria
1. THE SYSTEM SHALL 파생 개인화 프로필을 DynamoDB 핫(TTL 없음, PK=actorId)에 보관한다.
2. WHEN 이벤트 아이템의 `ttl`이 만료되면 THE SYSTEM SHALL DynamoDB Streams + Lambda로 TTL 삭제만 필터(`eventName=REMOVE` AND `principalId=dynamodb.amazonaws.com`)해 S3 콜드에 가명 유지로 적재한다.
3. THE SYSTEM SHALL S3 콜드 객체를 `actorHash` + 날짜로 파티셔닝하고 SSE-KMS로 암호화한다.
4. WHEN 사용자가 삭제를 요청하면 THE SYSTEM SHALL `sub`로 actorId를 재계산해 Memory·DynamoDB·S3 prefix를 일괄 삭제한다.
5. THE SYSTEM SHALL 삭제권 처리를 Cognito 사용자 삭제 이전에 실행한다(선삭제 시 가명 재계산 불가 방지).

### Requirement 4 — Candidate Evidence 3층 분해
**User Story:** Lovv 개발자로서, 검색·스코어 코어를 도시 선정과 반경 루프에서 재사용하고 싶다.

#### Acceptance Criteria
1. THE SYSTEM SHALL 공유 검색·스코어 코어를 stateless로 두고 `city | radius` 게이트를 추상화한다.
2. WHERE 도시 선정 컨텍스트이면 THE SYSTEM SHALL 테마 커버리지 중심 가중치를, WHERE 반경 스텝이면 거리 중심 가중치를 적용한다.
3. THE SYSTEM SHALL 루프 동안 `query_vector`를 재사용하고 매 턴 재임베딩하지 않는다.
4. WHEN 도시 선정이 끝나면 THE SYSTEM SHALL CandidateEvidencePackage를 루프 시드 `{도시, query_vector, anchor, budget}`로 산출한다.

### Requirement 5 — 대화형 HITL 빌더 루프
**User Story:** Lovv 사용자로서, 동선이 내 선택 순서대로 쌓이길 원한다. 그래야 임의 배치를 받아들이지 않아도 된다.

#### Acceptance Criteria
1. THE SYSTEM SHALL 방문 순서를 임의로 정하지 않고 사용자 선택 순서를 동선으로 사용한다.
2. WHILE 빌더 루프 중이면 THE SYSTEM SHALL Supervisor(결정론) → 반경 Provider → 후보 제시 → 사용자 픽 → next anchor를 반복한다.
3. WHEN 사용자 입력이 들어오면 THE SYSTEM SHALL Intent action(`PICK`/`REPLACE_PLACE`/`EXCLUDE`/`FILTER`/`DONE`)으로 구조화해 반경 Provider 필터를 재파라미터화한다.
4. WHEN action이 `DONE`이면 THE SYSTEM SHALL 루프를 종료하고 출력 단계로 진행한다.

### Requirement 6 — 충분성: 결정론 순회 (evaluator 노드 없음)
**User Story:** Lovv 메인테이너로서, 충분성 판단에 LLM 평가자를 추가하지 않고 결정론적으로 처리하고 싶다.

#### Acceptance Criteria
1. THE SYSTEM SHALL 별도 LLM evaluator/reflection 노드를 두지 않는다.
2. IF 표시 후보가 soft floor 미만이면 THEN THE SYSTEM SHALL 폴백 사다리(① 반경 확장 N→2N → ② 지도 API 보충 → ③ 솔직 안내)를 순서대로 순회한다.
3. THE SYSTEM SHALL 큐레이션 최소를 하드 게이트가 아닌 soft floor로 두고 극단적으로 1곳까지 허용한다.
4. THE SYSTEM SHALL 최대 반경·사다리 단 수·최대 턴 수의 결정론 종료 가드를 가지며 미달 시 솔직 안내로 종료하고 하드 실패로 되돌리지 않는다.

### Requirement 7 — 정합성 게이트 + Output·Eval 통합
**User Story:** Lovv 메인테이너로서, 출력과 검증을 한 노드에서 처리해 그래프를 단순화하고 환각을 막고 싶다.

#### Acceptance Criteria
1. THE SYSTEM SHALL Output(패키징)과 Eval(정합성 게이트)을 하나의 통합 노드로 수행한다.
2. WHEN 출력을 패키징할 때 THE SYSTEM SHALL 장소명·날짜·좌표·핵심 Key가 `itinerary_builder` State와 일치하는지 코드로 검수한다.
3. IF 정합성 검수가 불일치이면 THEN THE SYSTEM SHALL 해당 항목 표시를 보류하고 사유를 기록하며, 필요 시에만 LLM 개입을 예외 승격한다.
4. THE SYSTEM SHALL 통합 노드의 출력을 `/recommendations` 계약 형태(타임라인·근거·링크)로 산출한다.

### Requirement 8 — Planner pure-code geo
**User Story:** Lovv 메인테이너로서, 동선 계산에서 LLM을 제거해 환각·지연을 없애고 싶다.

#### Acceptance Criteria
1. THE SYSTEM SHALL 구간 동선·이동시간을 Haversine/Shapely 등 pure-code geo로 계산한다.
2. THE SYSTEM SHALL Planner에서 텍스트 생성(LLM 호출)을 하지 않는다.
3. THE SYSTEM SHALL 반경 게이트를 좌표 기반 hard-filter로 처리한다.

### Requirement 9 — 노드 내부 I/O 병렬화
**User Story:** Lovv 운영자로서, 안전한 범위에서 검색·조회를 병렬화해 단일 요청 지연을 줄이고 싶다.

#### Acceptance Criteria
1. WHEN 활성 테마가 2개 이상이면 THE SYSTEM SHALL 테마별 벡터 검색을 ThreadPool로 병렬 실행하고 place_id 최소 distance로 병합한다.
2. THE SYSTEM SHALL 최종 장소 상세 보강을 ThreadPool 또는 `BatchGetItem`으로 처리한다.
3. THE SYSTEM SHALL 후보 제시의 세 소스(DB 큐레이션·지도 API·축제)를 병렬 fan-out한다.
4. THE SYSTEM SHALL boto3 클라이언트의 `max_pool_connections`를 병렬도에 맞게 상향하고, 부분 실패 시 future 예외를 수집해 부분 성공/실패 정책을 적용한다.
5. THE SYSTEM SHALL 그래프 노드 단위 병렬과 LangGraph 네이티브 fan-out은 사용하지 않는다(데이터 의존·단일 가변 state).

### Requirement 10 — 경계 / 불변 (Gateway 제외)
**User Story:** 프로젝트 오너로서, V2가 V1 계약과 안전망을 깨지 않고 진화하길 원한다.

#### Acceptance Criteria
1. THE SYSTEM SHALL `/recommendations` 요청·응답 스키마를 변경하지 않는다.
2. THE SYSTEM SHALL 무상태 기본 동작(checkpointer=None)을 모든 단계에서 보존한다.
3. THE SYSTEM SHALL 내부 score·raw retrieval payload·PII를 응답·로그에 노출하지 않는다(V1 Observability denylist 준수).
4. THE SYSTEM SHALL 본 스펙 범위에 AgentCore Gateway를 포함하지 않는다(도구는 인프로세스 유지).
5. THE SYSTEM SHALL 정본(`src/lovv_agent`)과 배포 사본(`app/LovvAgentV1/lovv_agent`) parity를 유지한다.

## Open Questions (Phase 2 전 확정 권장)
- 반경 N km·soft floor 표시 최소·최대 턴/사다리 상한 값.
- `event_expiry_days`(단기)·콜드 TTL `N일`(장기).
- 지도 API 선택(Kakao/Google/현지)·timeout·fallback.
- JWT 검증 책임 경계(entrypoint vs AgentCore Identity).
- `PSEUDONYM_SECRET` 로테이션 주기·버전드 스키마.
