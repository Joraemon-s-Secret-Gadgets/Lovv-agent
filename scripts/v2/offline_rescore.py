#!/usr/bin/env python3
"""오프라인 city_select 재채점/비교 하네스 — 기존 스모크 결과(top_k=100)만으로 가중치를 빠르게 비교.

AWS 불필요. **selection 오라클이 아니라 비교 도구** — pen_coef 등을 바꿔 랭킹이 얼마나 흔들리는지 본다.
city 그룹핑은 대문자 ddb_pk로 정규화(casing split 통합).

확정된 수식 구조(sem 제거):
  city_score = Σ_{covered t} w[t]·best_sim[t]   −   pen_coef · Σ_{missing t} w[t]
             (+ soft_bonus ≤0.10 / − distance / − congestion : 좌표·STAT 확보 후 다음 단계)
  best_sim[t] = 그 도시에서 테마 t의 best 장소 sim(=1−distance). w[t]=균등(1/n) 기본.

분기:
  - ANCHORED  : 케이스에 destination 있으면 그 도시 고정(선택 스킵). inputs-dir로 판별.
  - NO_CANDIDATE: 최고 점수 < floor → 억지 선택 대신 '적합 도시 없음' 플래그.
  - DISCOVERY : 그 외, top-1 선택.

사용:
  python scripts/v2/offline_rescore.py <smoke_dir> --inputs-dir docs/tasks/results/v2_retrieval_inputs \
      --pen-coef 1.0 --floor 0.0
산출: <smoke_dir>/rescore_<tag>.json (케이스별 랭킹+breakdown+branch)
"""
from __future__ import annotations
import argparse, glob, json, os
from collections import defaultdict
from typing import Any

# 파일명 stem 추출용: 앞쪽 일련번호/소스 토큰을 떼고 서술 꼬리만 남겨 input↔mock 매칭.
_SRC_TOKENS = {"v2", "gen", "v2mock", "v1dump", "mod", "short", "v1", "dump", "wrapped"}


def stem(name: str) -> str:
    """'031_v2mock_09_anchored_gyeongju_history' / 'v2_gen_09_anchored_gyeongju_history' → 'anchored_gyeongju_history'."""
    base = os.path.splitext(os.path.basename(name))[0].lower()
    toks = base.split("_")
    i = 0
    while i < len(toks) and (toks[i].isdigit() or toks[i] in _SRC_TOKENS):
        i += 1
    return "_".join(toks[i:])


def sim(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return max(0.0, 1.0 - float(distance))


def load_dest_map(mocks_dir: str | None) -> dict[str, str]:
    """원본 intent mocks에서 stem → destination(CITY#UPPER). retrieval inputs엔 dest가 없어 mocks에서 읽음.
    destination_id는 'gyeongju' 슬러그형 → 'CITY#GYEONGJU'로 변환."""
    m: dict[str, str] = {}
    if not mocks_dir:
        return m
    for path in glob.glob(os.path.join(mocks_dir, "**", "*.json"), recursive=True):
        obj = json.load(open(path, encoding="utf-8"))
        dest = (obj.get("intent_output", {}) or obj).get("destination_id")
        if isinstance(dest, str) and dest and dest != "null":
            m[stem(path)] = dest if dest.startswith("CITY#") else f"CITY#{dest.upper()}"
    return m


def score_cities(obj: dict, pen_coef: float) -> list[dict]:
    themes: list[str] = obj.get("query", {}).get("themes", []) or []
    w = {t: 1.0 / len(themes) for t in themes} if themes else {}
    raw = obj.get("channels", {}).get("raw", {})
    per_theme = raw.get("per_theme", {}) or {}
    no_theme = raw.get("no_theme", {}) or {}

    city_theme_best: dict[str, dict[str, float]] = defaultdict(dict)
    city_name: dict[str, str] = {}

    def ingest(block: dict, theme: str | None):
        for r in block.get("ranked", []):
            pk = (r.get("ddb_pk") or "").upper()
            if not pk:
                continue
            city_name.setdefault(pk, r.get("city_name_ko"))
            if theme is not None:
                s = sim(r.get("distance"))
                if s > city_theme_best[pk].get(theme, 0.0):
                    city_theme_best[pk][theme] = s

    if themes:
        for t in themes:
            ingest(per_theme.get(t, {}), t)
    else:                       # 테마 없는 케이스(이론상 없음): no_theme를 단일 의사테마로
        for r in no_theme.get("ranked", []):
            pk = (r.get("ddb_pk") or "").upper()
            if pk:
                city_name.setdefault(pk, r.get("city_name_ko"))
                s = sim(r.get("distance"))
                if s > city_theme_best[pk].get("_any", 0.0):
                    city_theme_best[pk]["_any"] = s
        themes = ["_any"]; w = {"_any": 1.0}

    rows = []
    for pk, best in city_theme_best.items():
        covered = [t for t in themes if t in best]
        missing = [t for t in themes if t not in best]
        coverage = sum(w[t] * best[t] for t in covered)
        penalty = pen_coef * sum(w[t] for t in missing)
        rows.append({"ddb_pk": pk, "city_name_ko": city_name.get(pk),
                     "score": round(coverage - penalty, 5),
                     "breakdown": {"weighted_coverage": round(coverage, 5),
                                   "missing_penalty": round(penalty, 5),
                                   "covered_themes": covered, "missing_themes": missing}})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def rescore_case(obj: dict, pen_coef: float, floor: float, dest_map: dict[str, str]) -> dict:
    cid = obj.get("case_id")
    rows = score_cities(obj, pen_coef)
    dest = dest_map.get(stem(cid))
    if dest:
        sel = next((r for r in rows if r["ddb_pk"] == dest), None)
        if sel is None:   # 고정 도시가 테마 후보풀에 없음 → no_candidate(다른 도시로 바꿔치기 금지)
            return {"case_id": cid, "branch": "no_candidate_anchored", "anchor": dest,
                    "selected": None, "note": "고정 도시에 해당 테마 후보 0", "ranking": rows[:10]}
        return {"case_id": cid, "branch": "anchored", "anchor": dest,
                "selected": sel, "ranking": rows[:10]}
    if not rows or rows[0]["score"] < floor:
        return {"case_id": cid, "branch": "no_candidate", "selected": None, "ranking": rows[:10]}
    return {"case_id": cid, "branch": "discovery", "selected": rows[0], "ranking": rows[:10]}


def selected_city_map(cases: list[dict]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for case in cases:
        case_id = case.get("case_id")
        row = case.get("selected")
        if not isinstance(case_id, str) or not isinstance(row, dict):
            continue
        ddb_pk = row.get("ddb_pk")
        if isinstance(ddb_pk, str):
            selected[case_id] = ddb_pk
    return selected


def main() -> int:
    ap = argparse.ArgumentParser(description="offline city_select rescore/compare")
    ap.add_argument("smoke_dir")
    ap.add_argument("--mocks-dir", default="docs/tasks/results/v2_intent_mocks",
                    help="anchored destination을 읽을 원본 intent mocks 디렉터리")
    ap.add_argument("--pen-coef", type=float, default=1.0)
    ap.add_argument("--floor", type=float, default=0.0)
    args = ap.parse_args()

    dest_map = load_dest_map(args.mocks_dir)
    files = [f for f in sorted(glob.glob(os.path.join(args.smoke_dir, "*.json")))
             if not os.path.basename(f).startswith(("_summary", "rescore_", "selected_", "city_stats"))]
    cases = [rescore_case(json.load(open(f, encoding="utf-8")), args.pen_coef, args.floor, dest_map)
             for f in files]
    tag = f"p{args.pen_coef}_f{args.floor}"
    with open(os.path.join(args.smoke_dir, f"rescore_{tag}.json"), "w", encoding="utf-8") as fh:
        json.dump({"params": vars(args), "anchored_n": sum(c["branch"] == "anchored" for c in cases),
                   "cases": cases},
                  fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.smoke_dir, "selected_cities.json"), "w", encoding="utf-8") as fh:
        json.dump(selected_city_map(cases), fh, ensure_ascii=False, indent=2)
    print(f"재채점 {len(cases)}케이스 (pen={args.pen_coef} floor={args.floor}) · "
          f"anchored {sum(c['branch']=='anchored' for c in cases)} · "
          f"no_candidate {sum(c['branch']=='no_candidate' for c in cases)}")
    for c in cases:
        s = c["selected"]
        tag_b = {"anchored": "[A]", "no_candidate": "[X]", "no_candidate_anchored": "[XA]",
                 "discovery": "   "}[c["branch"]]
        if s:
            bd = s.get("breakdown", {})
            print(f"  {tag_b} {c['case_id']}: {s.get('city_name_ko')}({s['ddb_pk']}) "
                  f"score={s.get('score')} miss={bd.get('missing_themes', '-')}")
        else:
            print(f"  {tag_b} {c['case_id']}: (선택 없음)")
    print(f"\nrescore_{tag}.json 저장 → {args.smoke_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
