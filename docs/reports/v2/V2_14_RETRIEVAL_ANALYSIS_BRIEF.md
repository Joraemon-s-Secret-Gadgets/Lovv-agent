# V2 검색 결과 분석 지시서 (retrieval_smoke 출력 분석)

> 대상: 분석 에이전트(Codex / Claude Code). 입력: `scripts/v2/retrieval_smoke.py` 실행 결과 JSON.
> 목적: city_select 검색(raw/soft × theme on/off)의 **실데이터 특성을 정량화**해 V2 결정의 근거를 만든다 — 특히 **C2a soft 게이트 효과 · top_k 예산 · soft 채널 가치**.
> 산출: 결과 디렉토리에 `ANALYSIS.md` 리포트 1장.

---

## 0. 실행 전제
```
LOVV_ENABLE_AWS_SMOKE=1 python scripts/v2/retrieval_smoke.py --live --top-k 100 --enrich-top 5
```
- top_k=100으로 한 번 실행 → 각 케이스 JSON의 `ranked[]`를 슬라이스해 top-10/30/50/100을 **재실행 없이** 분석.
- 결과 위치: `docs/tasks/results/v2_retrieval_smoke/<timestamp>/`
  - `_summary.json` — 케이스별 요약 집계.
  - `<case_id>.json` × 37 — 케이스별 상세.

## 1. 입력 JSON 구조 (읽을 위치)
**`<case_id>.json`**:
- `query.{raw_query, soft_query, themes}`
- `channels.raw.no_theme` / `.per_theme.<테마>` / `.per_theme_union` — 각: `{candidate_count, ranked[], distinct_cities, cities{city_id:{city_name_ko,count,titles,subtypes}}}`
  - `ranked[]` = distance 오름차순 전체: `{rank, place_id, distance, city_id, city_name_ko, title, theme_tags, subtype, ddb_pk, ddb_sk}` → **top-N은 `ranked[:N]`**
- `channels.raw.and_gate.{survived_city_count, eliminated_cities[], ...}`
- `channels.soft.*` (soft_query 있을 때만)
- `raw_vs_soft.{place_jaccard, city_overlap, raw_only_cities, soft_only_cities}`
- `enriched_raw_top[]` — 상위 5개 + `details.{description,address,season_tags,visit_months,...}`

**`_summary.json`**: `cases[].{case_id, themes, no_theme_cities, union_cities, and_survived, and_eliminated}`

> **케이스 분류**: `source`로 안 나뉘니 `themes` 길이로 **단일테마 vs 멀티테마**를 갈라 집계. (멀티테마가 soft 게이트의 핵심)

---

## 2. 분석 항목 (각: 계산 · 연결 결정)

**A. AND 게이트 정량화 — 최우선 (C2a soft 게이트)**
- 멀티테마 케이스에서 `and_gate.eliminated_city_count` 집계: 평균·최대, **≥1 도시 탈락 케이스 비율**.
- `eliminated_cities`를 일부 열어 — 그 도시가 일부 테마는 가진 "아까운 후보"인지 확인.
- → 결론: "AND는 멀티테마에서 평균 N개 도시를 죽인다(=soft 게이트가 살릴 후보). V1 최대 약점 정량."

**B. top-N 도시 수 곡선 (top_k 예산)**
- 각 케이스 `channels.raw.no_theme.ranked`를 N=10/30/50/100로 슬라이스 → 각 N의 distinct city 수.
- N↑에 따라 도시 수가 **언제 포화**되는지(곡선). → 권장 top_k 도출.

**C. 도시별 관광지 수 분포 (후보 충분성)**
- top-30(또는 권장 N) 기준 `cities[].count` 분포: 1~2개 도시가 독식하나, 고르게 퍼지나.
- 일정 슬롯(2d1n≈3, 3d2n≈?) 채우려면 도시당 충분한 관광지가 있는지 → Planner Pass2 부담·축소 위험 가늠.

**D. raw vs soft (soft 채널 가치)**
- `raw_vs_soft.place_jaccard`·`city_overlap` 집계. jaccard가 높고(≈1) 도시도 같으면 **soft 채널은 중복 → 2번째 임베딩 비용 대비 가치 낮음**. 낮으면 soft가 실제로 다른 후보를 데려오는 것.
- → 결론: soft 검색 채널 유지/제거 권고.

**E. theme on/off (테마 필터 필요성)**
- `no_theme`(필터 없음) vs `per_theme_union`의 도시·후보 집합 차이. raw 의미쿼리가 이미 테마를 잡으면 per-theme 필터 가치↓.
- → 결론: per-theme 필터 vs 단일 쿼리.

**F. 세부타입 분포 (균형)**
- `cities[].subtypes` 분포: 한 도시 후보가 특정 `attraction_subtype_code`로 쏠리나, 다양한가. → "세부타입 균형" 스코어링 인자 설계 참고.

**G. seed 후보 정성 점검 (C3)**
- 각 케이스 `ranked[:3]`(또는 도시별 top)의 `title`이 그 도시의 **대표 장소(day anchor)**로 적절한지 spot-check. 애매하면 `enriched_raw_top[].details.description` 또는 `ddb_inspect.py`로 확인.

**H. 엣지·데이터 품질**
- `no_candidate` 의도 케이스(`yeongyang`+해안 등) 결과가 비거나 엉뚱한지.
- 결측 필드(`subtype=null`, `ddb_pk=null`), 테마 라벨 불일치, 이상 도시명 → 플래그.

---

## 3. 산출물: `<결과 디렉토리>/ANALYSIS.md`
골격:
1. **핵심 요약** (수치 3~5개): AND 평균 탈락 도시 수 · 권장 top_k · soft jaccard 평균 · 도시 충분성 한 줄.
2. **항목별** (A~H) — 표/수치 중심.
3. **권장사항**: ① top_k 값 ② soft 채널 유지 여부 ③ soft 게이트 우선순위 근거(A) ④ 세부타입 균형 관찰.
4. **데이터 품질 이슈** 목록.

## 4. 분석 원칙
- **정량 먼저**(표·수치), 정성은 spot-check로 보완.
- **단일 vs 멀티테마 분리 집계** — 한 덩어리로 평균내지 말 것.
- 단일 케이스로 일반화 금지. 실데이터라 결측·이상치 가능 → 결론에 그 한계 명시.
- 분석은 **읽기 전용**: 결과 JSON·스크립트·소스 수정 금지(리포트만 작성).
