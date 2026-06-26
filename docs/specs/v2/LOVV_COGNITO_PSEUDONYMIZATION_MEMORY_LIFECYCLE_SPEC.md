# Lovv — Cognito 가명화 & 메모리 수명주기 SPEC

---
title: Lovv — Cognito Identity 경계 가명화 + 단기/장기 메모리 수명주기 (SPEC)
project: Lovv (로브)
status: 설계 (코드 미수정 · 구현 전 · 일부 확인 필요)
date: 2026-06-23
relates:
  - docs/specs/v2/LOVV_AGENTCORE_MEMORY_CHECKPOINTER_SPEC.md (Assumptions 1·Requirement 2·§8.1을 구체화)
  - docs/specs/v2/LOVV_INTERACTIVE_ITINERARY_BUILDER_DESIGN_V1.md (§8 상태·메모리 / §8.1 TTL 라인)
  - ADR — Lovv 개인화·에이전트 상태 아키텍처 결정 기록 (ephemeral 통합 / persistent 분리)
amends:
  - LOVV_AGENTCORE_MEMORY_CHECKPOINTER_SPEC.md Assumption 1
    ("actorId는 이미 가명 ID라고 가정 · 가명화는 Identity 경계 책임")
    → 본 SPEC이 그 Identity 경계를 **AWS Cognito + HMAC 가명화**로 구체화한다.
note: 본 문서는 설계 캡처용이며 구현 코드를 포함하지 않는다.
---

## 0. 한 줄 요약

AWS Cognito를 **가명화 Identity 경계**로 삼아, 진입 시 검증된 `sub`에서 결정론적
가명(`actorId`)을 만들어 전 계층에 흘린다. **단기**는 AgentCore Memory(통합), **장기**는
DynamoDB(TTL)→S3 콜드(분리)로 두되, 콜드는 **삭제가 아니라 가명 유지 적재**로 개인화·평균
분석에 쓰고 **사용자 요청 시에만 삭제**한다.

> 핵심 정정: 이 처리는 **가명화(pseudonymization)** 다. Cognito가 `sub↔실신원`을 보유하므로
> 재식별이 가능하며, 따라서 콜드 데이터도 개인정보로서 **삭제권 대상**이다. "익명화"가 아니다.

## 1. 결정 사항 (이 SPEC의 전제)

| # | 결정 | 근거 |
|---|------|------|
| D1 | `actorId = HMAC-SHA256(cognito_sub, PSEUDONYM_SECRET)` | 스토어에 Cognito 직키 미저장 → 유출 내성. 결정론적이라 개인화 연결 유지 |
| D2 | 시크릿은 Secrets Manager(KMS 암호화)에서 **컨테이너당 1회 로드·캐시**, HMAC은 **로컬 계산** | 요청당 KMS 호출 제거 → 비용·지연 0에 수렴 |
| D3 | **단일 결정론 가명**을 핫(DynamoDB)·콜드(S3) 공통 사용 (핫/콜드 키 분리는 옵션·기본 off) | 개인화·평균 분석·재하이드레이션·삭제를 단순화. 분리의 보안 이득은 현 위협모델 대비 과함 |
| D4 | 콜드 S3 = **가명 유지 적재**(비익명) · 개인화/분석 보관 · **사용자 요청 시 삭제** | 복귀 사용자 재하이드레이션·평균 분석에는 연결성이 필요 → 가명화가 정답 |
| D5 | 진입에서 **Cognito JWT 검증**(서명·iss·aud·exp) 후에만 `sub` 신뢰 | 미검증 시 위조 actorId로 타인 메모리 접근 가능 |
| D6 | raw `sub`·이메일·실신원은 DynamoDB/S3/AgentCore Memory **어디에도 미저장**. `sub↔실신원` 매핑은 **Cognito에만** 존재 | spec "매핑 테이블 코드경로 미접근" 충족 |
| D7 | 삭제권 처리는 **Cognito 사용자 삭제 이전**에 실행 | 계정 선삭제 시 `sub` 소실 → 가명 재계산 불가 → 콜드 데이터 미삭제 위험 |

## 2. 용어 (혼동 방지)

- **가명화(pseudonymization)**: 식별자를 가명으로 치환하되 **매핑이 존재**(재식별 가능). 개인정보로
  취급 → 접근·삭제권 적용. ← **본 설계가 채택**.
- **익명화(anonymization)**: 비가역 처리로 재식별 불가. 자유 보관 가능하나 **재하이드레이션 불가**.
  본 설계의 콜드 용도(복귀 사용자·개인화)와 양립 불가 → 미채택.

## 3. Identity 경계 (Cognito → actorId)

```text
[Client] Cognito Hosted UI/SDK 로그인
  └─ ID/Access Token(JWT, sub 포함) 발급
        │
        ▼
[Entry] AgentCore / HTTP entrypoint
  1) JWT 검증: 서명(JWKS) · iss(=user pool) · aud(=app client) · exp
  2) claims.sub 추출  (sub = Cognito 안정 식별자 · UUID)
  3) actorId = HMAC_SHA256(sub, PSEUDONYM_SECRET)   # 로컬 계산
  4) graph_config = {configurable: {thread_id: session_id, actor_id: actorId}}
        │
        ▼
[Graph/Memory] 전 계층 actorId(가명)만 사용. sub·이메일·실신원 미전달.
```

- `PSEUDONYM_SECRET`: 32바이트+ 랜덤. **Secrets Manager**(KMS-CMK 암호화) 보관, 컨테이너 부팅
  시 1회 로드 후 프로세스 메모리 캐시. 로테이션 시 §9 참조.
- `session_id`(thread)와 `actorId`(actor)는 기존 checkpointer SPEC Requirement 2와 동일 키 의미.

## 4. 메모리 계층 정책

### 4-1. 단기 — AgentCore Memory (Ephemeral · 통합)

- 대상: checkpoint blob(interrupt/resume) + 세션 컨텍스트. **수명 공유**(`event_expiry_days`).
- 키: `actorId`(가명)·`session_id`로 격리. 장기 추출 대상 제외.
- 활성화: **env-gated · 기본 off**(checkpointer SPEC R3). serde round-trip 게이트(R4) 선행.

### 4-2. 장기 ① — 파생 개인화 프로필 (DynamoDB 핫)

- PK = `actorId`(가명). **TTL 없음**(개인화 유지). Profile Agent의 읽기 소스(빌더 spec §7).
- 저장: 선호 요약(테마·동행·픽 신호 등 파생값). 원시 후보·PII 미포함.

### 4-3. 장기 ② — raw 이벤트 로그 (DynamoDB TTL → S3 콜드)

- DynamoDB 이벤트 아이템에 `ttl`(epoch) = `now + N일`. 핫 윈도우 동안 빠른 읽기.
- 만료 시 **삭제가 아니라 콜드 이행**(§5). 콜드는 개인화 재계산·평균 분석·복귀 재하이드레이션용.

## 5. 콜드 이행 파이프라인 (DynamoDB TTL → S3, 가명 유지)

```text
DynamoDB(이벤트, ttl) ──TTL 만료(best-effort)──▶ Streams(NEW_AND_OLD_IMAGES)
        │                                              │
        │                                              ▼
        │                                   Lambda: TTL 삭제만 필터
        │                                   eventName == REMOVE
        │                                   AND userIdentity.principalId
        │                                       == "dynamodb.amazonaws.com"
        │                                              │ (사용자/앱 삭제와 구분)
        │                                              ▼
        └──────────────────────────────▶ S3 콜드 적재(OLD_IMAGE, 가명 유지)
                                          - 경로: s3://.../actorHash=<HMAC>/dt=YYYY-MM-DD/
                                          - 암호화: SSE-KMS
                                          - (선택) Lifecycle → Glacier
```

- **TTL은 best-effort**(만료 후 최대 ~48h 지연, SLA 없음). "N일 후 반드시"가 요건이면
  `expires_at` 필드 + **읽기 시 앱레벨 필터**로 보강(빌더 spec §8.1-1과 동일).
- 콜드 객체는 이미 `actorId`(가명)로 키링되므로 **추가 치환 불필요**. raw sub/PII가 OLD_IMAGE에
  섞이지 않도록 **이벤트 아이템 스키마에서 처음부터 가명만** 쓴다(D6).
- (옵션·기본 off) 핫↔콜드 비연결성이 필요하면 콜드 키를 `HMAC(sub, secret, "cold")`로 도메인
  분리. 단 재하이드레이션 시 `sub`에서 재계산 가능해야 하므로 **결정론 유지**.

## 6. 삭제권 (Right-to-erasure)

```text
[삭제 요청] 사용자 (앱/계정 설정)
  1) 현재 Cognito sub 확보  ← 반드시 Cognito 사용자 삭제 "이전" (D7)
  2) actorId = HMAC(sub, secret) 재계산
  3) 삭제 실행:
       - AgentCore Memory: actorId/session 범위 만료·삭제
       - DynamoDB 핫: PK=actorId 프로필·이벤트 삭제
       - S3 콜드: prefix actorHash=<actorId>/ 객체 일괄 삭제
  4) 삭제 로그(가명·타임스탬프만) 기록 → 감사 추적
  5) 이후 Cognito 사용자 삭제 진행
```

- 가명화는 **삭제 의무 면제가 아니다**: 콜드 S3도 개인정보 → 요청 시 삭제 가능해야 한다.
- 파티션을 `actorHash` prefix로 두는 이유가 이 일괄 삭제를 가능케 하기 위함.
- 고볼륨 시 `DynamoDB → Kinesis → Firehose → S3` 확장 가능(부트캠프 규모엔 Streams+Lambda가
  단순·저렴).

## 7. 보안 경계 (Hard line)

- `sub↔실신원` 매핑은 **Cognito에만** 존재. 코드 경로·DynamoDB·S3·Memory에서 접근/저장 금지.
- `PSEUDONYM_SECRET`은 Secrets Manager(KMS-CMK), 최소권한 IAM(read-only, 특정 역할만). 코드·리포·
  로그·env 평문 노출 금지.
- 전 저장소 **SSE-KMS** 암호화. S3 버킷 Public access block, 버킷 정책 최소권한.
- 로그·메트릭에 raw sub·이메일·PII 미기록(가명·집계만). `build_memory_safe_summary` 원칙 준수.
- JWT 검증 실패·`sub` 부재 시 **안전 폴백**(임시 세션키)으로 처리하고 영속 저장하지 않는다.

## 8. 비용 노트

| 항목 | 선택 | 비용 영향 |
|------|------|-----------|
| 가명 계산 | 로컬 HMAC(캐시 시크릿) | CPU 거의 0 · KMS 요청당 호출 없음 |
| 시크릿 로드 | 컨테이너당 1회 | Secrets Manager 호출 미미(웜 재사용) |
| 콜드 보관 | S3 Standard→(선택)Glacier Lifecycle | 장기 보관 단가↓ |
| TTL 이행 | Streams + Lambda | 이벤트량 비례 · 소규모 저렴 |

> 요청당 KMS `GenerateMac`을 호출하는 대안은 API 비용·지연이 붙어 **미채택**(D2).

## 9. 키 로테이션 (PSEUDONYM_SECRET)

- 시크릿을 바꾸면 같은 `sub`라도 가명이 달라져 **기존 데이터와 연결이 끊긴다**(개인화·삭제 영향).
- 권장: **버전드 시크릿** + 데이터에 `pseudonym_key_version` 태그. 신규는 새 버전, 조회·삭제는
  버전별로 가명을 재계산해 매칭. 무중단 마이그레이션 필요 시 듀얼-라이트 기간 운영.
- 로테이션 트리거·주기는 보안 정책에 따라 별도 확정(§11).

## 10. 검증 전략 (Testing)

1. **JWT 검증 단위**: 위조 서명·만료·잘못된 aud/iss 거부, 정상 토큰만 `sub` 추출.
2. **가명 결정론**: 동일 `sub`→동일 `actorId`, 다른 `sub`→다른 값, 시크릿 변경 시 변경.
3. **PII 비유출**: 이벤트/프로필/콜드 스키마에 raw sub·이메일·실신원 부재(스키마 가드 테스트).
4. **TTL 이행 필터**: REMOVE+`dynamodb.amazonaws.com`만 콜드行, 사용자/앱 삭제는 제외.
5. **삭제권 E2E**: 요청→가명 재계산→Memory/DynamoDB/S3 prefix 삭제→잔존 0 확인.
6. **순서 가드(D7)**: Cognito 선삭제 시나리오에서 사전 삭제 훅이 콜드까지 정리하는지.
7. **무상태 회귀**: Memory off(기본)에서 기존 동작 불변(checkpointer SPEC R1).

## 11. 미해결 / 확인 필요

- [ ] `event_expiry_days`(단기)·콜드 TTL `N일`(장기) 최종값.
- [ ] JWT 검증을 entrypoint 코드에서 직접 vs AgentCore Identity/게이트웨이 위임 — 책임 경계.
- [ ] `PSEUDONYM_SECRET` 로테이션 주기·버전드 스키마 적용 범위.
- [ ] 콜드 도메인 분리(옵션) 채택 여부 — 분석 조인 편의 vs 핫/콜드 비연결성.
- [ ] S3 Lifecycle(Glacier 이행) 임계 일수.
- [ ] 삭제권 처리 진입점(앱 설정 vs Cognito pre-deletion Lambda 훅) 확정.
- [ ] 평균 분석 파이프라인(콜드 → 집계)이 추가로 진짜 익명화 산출물을 필요로 하는지(이중 트랙 여부).

## 12. 기존 SPEC과의 관계

- checkpointer SPEC **Assumption 1**("actorId는 이미 가명")의 **그 가명을 누가 만드는가**를 본
  SPEC이 Cognito+HMAC로 채운다. Requirement 2(actorId 플러밍)·R3(Memory 설정)·§8.1(TTL 라인)은
  그대로 유효하며 본 SPEC이 콜드 가명 유지·삭제권 순서를 구체화한다.
- 빌더 spec §8(단기 통합/장기 분리)·§8.1과 충돌 없음(확장).

> 본 문서는 1차 설계(초안)다. §11 "확인 필요" 항목은 구현 착수 전 확정한다.
