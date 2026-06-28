# test_cases/ — 정리된 입력 fixture 후보 세트 (22개)

> ⚠️ **후보 세트다. 실제 테스트 적용 여부 미정 → 공식 테스트 계획/handoff 문서엔 아직 미반영.**
> 기존 `agent_input_payloads/`는 그대로 두고 여기서 재정리만 했다.

## 정리 원칙

- tripType은 **daytrip / 2d1n / 3d2n 까지만** (4d3n·5d4n 제외).
- **미식(food_local) 테마 없음.**
- 적재 데이터가 **강원·경북뿐**이므로 타 지역 지명 없음(동해안·경주 등만).
- 중복 케이스 제거, 번호 01–20 정리.
- 기능 케이스는 **soft preference가 충분히 생성되도록 쿼리 보강**. 단 **intent 추출 자체를 보는 19(짧은 쿼리)·20(긴 복합 쿼리)** 은 의도적으로 보강하지 않음.

## 케이스 인덱스

| # | 파일 | 진입 | 테마 | trip | 축제 | userLoc | 목적 |
|---|------|------|------|------|------|---------|------|
| 01 | coast_quiet_2d1n | chat | sea_coast | 2d1n | F | - | congestion 조용 |
| 02 | coast_vibrant_2d1n | chat | sea_coast | 2d1n | F | - | congestion 활기 |
| 03 | nature_quiet_2d1n | chat | nature | 2d1n | F | - | congestion 조용 |
| 04 | nature_vibrant_2d1n | chat | nature | 2d1n | F | - | congestion 활기 |
| 05 | history_2d1n | chat | history | 2d1n | F | - | 단일 테마 |
| 06 | art_2d1n | chat | art | 2d1n | F | - | 단일 테마 |
| 07 | healing_2d1n | chat | healing | 2d1n | F | - | 단일 테마 |
| 08 | nature_coast_3d2n | chat | nature+coast | 3d2n | F | - | 다중 테마 |
| 09 | history_nature_2d1n_seoul | chat | history+nature | 2d1n | F | 서울 | 거리 |
| 10 | coast_healing_daytrip_daegu | chat | coast+healing | daytrip | F | 대구 | 거리 변형 |
| 11 | home_nature_healing_3d2n | home_recommendation | nature+healing | 3d2n | F | 서울 | 거리+다중 |
| 12 | history_festival_2d1n | chat | history | 2d1n | T | - | 축제 |
| 13 | sea_festival_2d1n | chat | sea_coast | 2d1n | T | - | 축제 |
| 14 | mapmarker_history_festival_daytrip | map_marker(경주) | history | daytrip | T | - | 앵커+축제 |
| 15 | wrapped_agentcore_history_art_2d1n | agentcore wrap | history+art | 2d1n | F | - | wrapper |
| 16 | wrapped_http_nature_festival_daytrip | http body | nature | daytrip | T | - | wrapper |
| 17 | rare_combo_art_healing_clarify | chat | art+healing | 2d1n | F | - | 희소→no_candidate/clarify |
| 18 | invalid_mapmarker_missing_destination | map_marker | sea_coast | daytrip | F | - | validation negative |
| 19 | intent_short_query | chat | sea_coast | daytrip | F | - | 짧은 쿼리 deterministic (보강 안 함) |
| 20 | intent_long_complex_query | chat | nature+coast+history | 3d2n | F | 서울 | 긴 복합 쿼리 intent LLM (보강 안 함) |
| 21 | mapmarker_history_2d1n | map_marker(경주) | history | 2d1n | F | - | 도시 고정+축제 미포함 — 앵커 city_id 불일치 회귀 검증(14와 축제만 차이) |
| 22 | no_candidate_inland_coast | map_marker(영양) | sea_coast | daytrip | F | - | no_candidate — 내륙 도시(해안 없음) 앵커 + 해안 테마(불가) → no_city_after_theme_gate |
