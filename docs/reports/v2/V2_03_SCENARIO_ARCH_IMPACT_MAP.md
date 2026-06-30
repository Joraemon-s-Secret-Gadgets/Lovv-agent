# V2 시나리오 → 아키텍처 영향 매핑 (Step 3)

> 작성일 2026-06-28 · 입력: `V2_SCENARIO_INSCOPE.md`(스코프 내 시나리오) + 기존 아키텍처 결정.
> 방법: in-scope 시나리오를 **아키텍처 영향이 같은 묶음**으로 클러스터링 → 각 묶음이 건드리는 [노드 / 데이터계약 / 출력 / 새 결정]을 적는다. **충돌·파급은 이 표의 산출물**(§2).
> 노드: Intent · Supervisor(S) · Profile · city_select(retrieval+scoring&selection) · FestivalVerifier · Planner(+In-city Itinerary) · Packager · Memory(checkpoint/resume).
> 영향 강도: ○ 기존으로 충분 · ◐ 일부 변경 · ● 신규/구조 변경 · ⚠️ 충돌.

---

## 1. 매핑표

### 생성 (초회)
| 시나리오 묶음 | 영향 노드 | 데이터계약 | 출력 영향 | 필요한 새 결정 |
|---|---|---|---|---|
| **G1 감정·의도 발견형** (번아웃·이별·즉흥·숨은발견·노스탤지어·선택피로·연인) | Profile read → Intent → city_select → Planner ◐ | 기존 ○ | 기존 ○ | **선호 프로필(theme_weights) 점수 가중**(cold start=균등). "즉흥/정보부족"은 되묻기 경계(D-10) |
| **G2 완벽주의·동선** (분단위 타임라인) | Planner ● | PlannerInput ○ | `move`(moveMinutes) **값 채움** ◐ | **동선/이동시간 모델**: haversine 1차 vs 실거리(백로그) · moveMinutes 출력 채택 |
| **G3 이동수단 거친구분** (자동차/뚜벅이) | Intent(신호) ◐ · Planner(배치) ◐ | **Intent 출력에 `transport_pref` 추가** ◐ | 기존 ○ | 신호 정의 + 반영 강도(soft) |
| **G4 입력형태** (모호·정보없음·긴서사·모순) | Profile read · Intent(clarification) ◐ | 기존 ○ | END_WAIT 질문 ○ | **모호 입력 시 profile fallback**(선호 있으면 그걸로 생성 vs 되묻기) · 되묻기 경계(D-10) · soft optional |
| **G5 입력 변환·교정** (이모지·부정확 지명) | Intent(LLM 보강) ◐ | 기존 ○ | 기존 ○ | 지명 교정 범위 |

### 수정 (resume)
| 시나리오 묶음 | 영향 노드 | 데이터계약 | 출력 영향 | 필요한 새 결정 |
|---|---|---|---|---|
| **M1 장소 1개 교체(+조건)** | resume → Intent(modify) → Planner 재인출 ◐ | PlacePool · **재인출=S3 Vector(확정)** ○ | 갱신 itinerary + interrupt ◐ | 없음 (1차 확정) |
| **M2 무드/테마/길이/날짜/도시 변경** | 거슬러: city_select·골격 재실행 ● | CitySelectionResult 재생성 · trip_type 변경 ◐ | 재생성 ◐ | **수정 처리 범위**(1차 vs 확장) · 길이변경 시 **4d3n 미검증** 노출 |
| **M3 맥락 변화 후 재요청** (감정·동행·예산·체력) | Intent(modify) + 재배치 ◐ | **세션 누적 컨텍스트** ◐ | 기존 ○ | soft/기피 **조건 적용 범위**(슬롯 일시 vs 세션 누적, D-9) |
| **M4 날씨 악화→실내** | Planner ◐ | 기존 ○ | 실내 위주 재배치 ○ | (=Plan B의 수정판) |

### 날씨 Plan B (초회 동반)
| 시나리오 | 영향 노드 | 데이터계약 | 출력 영향 | 필요한 새 결정 |
|---|---|---|---|---|
| **W 기후 경향 대비 대체 일정** | Planner ● | PlannerOutput ● | ⚠️ **단일 itinerary → primary + Plan B 2벌** (공개 스키마 변경!) | ⚠️ **출력에 Plan B 노출 방식**(2일정 vs 수정루프 한정) · 발동 임계(D-4) |

### 엣지 (기본 결과 — V1 5종)
| 시나리오 묶음 | 영향 노드 | 데이터계약 | 출력 영향 | 필요한 새 결정 |
|---|---|---|---|---|
| **E 불가능 동선·범위밖·이상값·축제시즌·no_candidate·필수누락** | Intent/S/Packager ○ | 기존 5종 ○ | END_WAIT 안내·거부 ○ | 없음 (V1 유지). 단 응답상태에 "수정대기" 추가(아래) |

### 횡단 (시나리오 전반에서 떨어지는 구조 영향)
| 항목 | 영향 노드 | 데이터계약 | 출력 영향 | 필요한 새 결정 |
|---|---|---|---|---|
| **X1 수정 루프 전반** | Memory(checkpoint/interrupt/resume) · S(resume 분기) ● | UnifiedAgentState 직렬화 ● | **응답상태 5종 → +"수정 대기(interrupt)"** ◐ | 응답 상태 모델 확장 |
| **X2 점수 신뢰성** | scoring(관측) ◐ | — | — | **점수 항별 기여 로깅 + ablation**(V1 함정 재발 방지) |
| **X3 선호 프로필(theme_weights)** | Profile **read**(초회 1회)→city_select 점수+Planner · **write**(완성 후 비동기) ◐ | DynamoDB `LovvUserProfile`(가명 PK) · UnifiedAgentState ◐ | 기존 ○ | **write 범위**(theme_weights만 vs +soft선호·이동수단·기피) · **write 트리거**(완성 후만 vs 수정 확정 후도) · 모호입력 fallback(G4) · cold start=균등(확정) |

---

## 2. 충돌·파급 (위 표에서 자동으로 떨어진 것)

1. ⚠️ **출력 스키마 — 가장 큰 충돌**: 우리가 "현 output 유지"로 정했는데, **Plan B(2벌)**(W)와 **moveMinutes 값 채움**(G2)이 공개 스키마를 바꿉니다. → "output 유지"는 **수정 불가피**. 먼저 결정해야 다른 게 안 흔들림.
2. **응답 상태 모델 확장**(X1): 5종 → +수정대기. resume를 넣은 순간 따라옴.
3. **수정 처리 범위 = 우선순위 그 자체**(M2/M3): 1차(교체)만 출하 vs 무드/길이/도시/맥락변화까지 — 이게 "1차 vs 백로그" 경계.
4. **동선/이동시간 모델**(G2): haversine 1차 + moveMinutes 채움 / 실거리는 백로그.
5. **Intent 정밀화**(G3·G4·M3): transport_pref · 되묻기 경계 · soft optional · 조건 적용범위.
6. **trip_type 길이변경 → 4d3n 미검증**(M2): 지원 범위 정책.
7. **Observability 보강**(X2): "V1 게이트 유지"로는 부족.
8. **선호 프로필 횡단**(X3): theme_weights가 G1 점수 가중 · G4 모호입력 fallback · 수정 후 write까지 가로지름 → **profile write 범위/트리거**가 새 결정. (특히 수정에서 추출한 soft·기피·이동수단을 profile에 누적할지)

---

## 3. 이 표가 만든 "아키텍처 결정 목록" (= Step 4 우선순위 후보)

> "필요한 새 결정" 열을 모은 것. 이게 곧 설계 동결에서 정할 항목.

**선결(다른 것에 영향)**
- D-A ⚠️ **출력 스키마 확정** — Plan B 노출 방식 + moveMinutes. (1번 충돌)
- D-B **수정 처리 범위 / 1차 vs 백로그** — M1만 1차? 어디까지 확장? (제품·일정의 척추)

**품질 핵심 (V1 한계 직결)**
- D-C 동선/이동시간 모델(haversine 1차) + moveMinutes
- D-D 점수 항 기여 로깅·ablation (X2)
- (이미 확정) 테마 게이트 soft · capacity 제거 · 재인출 S3 Vector

**Intent 정밀**
- D-E transport_pref(이동수단) · D-F 되묻기 경계(D-10) · soft optional · D-G 조건 적용범위(D-9)

**개인화 (선호 프로필)**
- D-K **profile write 범위·트리거** — theme_weights만 vs +soft·이동수단·기피 / 완성 후만 vs 수정 후도 · 모호입력 profile fallback · (확정: cold start=균등)

**보완**
- D-H 응답 상태 모델 확장(수정대기) · D-I 4d3n 정책 · D-J 날씨 Plan B 임계(D-4)

---

## 4. 다음 (Step 4·5)
- 위 §3 목록을 **선결 → 품질 → 정밀 → 보완** 순으로 정해 나가면 Step 4(우선순위)·Step 5(아키텍처 확정)가 닫힌다.
- **가장 먼저 D-A(출력 스키마)**: 이게 정해져야 Plan B·moveMinutes·응답상태가 한 번에 정렬된다.
