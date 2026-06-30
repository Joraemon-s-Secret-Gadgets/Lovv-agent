from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent))
from profile_rescore_markdown import write_markdown

THEME_ID_TO_LABEL = {
    "sea_coast": "바다·해안",
    "nature_trekking": "자연·트레킹",
    "history_tradition": "역사·전통",
    "art_sense": "예술·감성",
    "healing_rest": "온천·휴양",
}
LABEL_TO_THEME_ID = {label: theme_id for theme_id, label in THEME_ID_TO_LABEL.items()}
SRC_TOKENS = {"v2", "gen", "v2mock", "v1dump", "mod", "short", "v1", "dump", "wrapped"}


def stem(name: str) -> str:
    base = os.path.splitext(os.path.basename(name))[0].lower()
    toks = base.split("_")
    index = 0
    while index < len(toks) and (toks[index].isdigit() or toks[index] in SRC_TOKENS):
        index += 1
    return "_".join(toks[index:])


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def sim(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return max(0.0, 1.0 - float(distance))


def load_dest_map(mocks_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in mocks_dir.glob("**/*.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        dest = (obj.get("intent_output", {}) or obj).get("destination_id")
        if isinstance(dest, str) and dest and dest != "null":
            result[stem(path.name)] = dest if dest.startswith("CITY#") else f"CITY#{dest.upper()}"
    return result


def persona_weights(
    persona: dict[str, Any],
    *,
    alpha: float,
    min_weight: float,
    max_weight: float,
    activation: float,
) -> dict[str, float]:
    counts = persona["saved_theme_counts"]
    total = sum(counts.values())
    if float(persona["saved_trip_count"]) < activation:
        return {theme_id: 1.0 for theme_id in THEME_ID_TO_LABEL}
    confidence = min(float(persona["saved_trip_count"]) / activation, 1.0)
    weights: dict[str, float] = {}
    for theme_id in THEME_ID_TO_LABEL:
        observed = counts.get(theme_id, 0) / total if total else 0.2
        learned = clamp(1.0 + alpha * (observed - 0.2), min_weight, max_weight)
        weights[theme_id] = round(1.0 + confidence * (learned - 1.0), 6)
    return weights


def active_weights(themes: list[str], theme_id_weights: dict[str, float] | None) -> dict[str, float]:
    if not themes:
        return {}
    if theme_id_weights is None:
        return {theme: 1.0 / len(themes) for theme in themes}
    raw = {
        theme: theme_id_weights.get(LABEL_TO_THEME_ID.get(theme, ""), 1.0)
        for theme in themes
    }
    total = sum(raw.values())
    if total <= 0:
        return {theme: 1.0 / len(themes) for theme in themes}
    return {theme: weight / total for theme, weight in raw.items()}


def score_rows(
    obj: dict[str, Any],
    *,
    pen_coef: float,
    theme_id_weights: dict[str, float] | None,
    profile_cap: float | None,
) -> list[dict[str, Any]]:
    themes = obj.get("query", {}).get("themes", []) or []
    raw = obj.get("channels", {}).get("raw", {})
    per_theme = raw.get("per_theme", {}) or {}
    no_theme = raw.get("no_theme", {}) or {}
    best_by_city: dict[str, dict[str, float]] = defaultdict(dict)
    city_name: dict[str, str | None] = {}

    def ingest(block: dict[str, Any], theme: str | None) -> None:
        for row in block.get("ranked", []):
            pk = (row.get("ddb_pk") or "").upper()
            if not pk:
                continue
            city_name.setdefault(pk, row.get("city_name_ko"))
            if theme is not None:
                score = sim(row.get("distance"))
                if score > best_by_city[pk].get(theme, 0.0):
                    best_by_city[pk][theme] = score

    if themes:
        for theme in themes:
            ingest(per_theme.get(theme, {}), theme)
    else:
        for row in no_theme.get("ranked", []):
            pk = (row.get("ddb_pk") or "").upper()
            if pk:
                city_name.setdefault(pk, row.get("city_name_ko"))
                score = sim(row.get("distance"))
                if score > best_by_city[pk].get("_any", 0.0):
                    best_by_city[pk]["_any"] = score
        themes = ["_any"]

    equal = active_weights(themes, None)
    weighted = active_weights(themes, theme_id_weights)
    rows: list[dict[str, Any]] = []
    for pk, best in best_by_city.items():
        covered = [theme for theme in themes if theme in best]
        missing = [theme for theme in themes if theme not in best]
        equal_score = sum(equal[t] * best[t] for t in covered) - pen_coef * sum(equal[t] for t in missing)
        weighted_score = sum(weighted[t] * best[t] for t in covered) - pen_coef * sum(weighted[t] for t in missing)
        final_score = (
            weighted_score
            if profile_cap is None
            else equal_score + clamp(weighted_score - equal_score, -profile_cap, profile_cap)
        )
        rows.append({
            "ddb_pk": pk,
            "city_name_ko": city_name.get(pk),
            "score": round(final_score, 5),
            "equal_score": round(equal_score, 5),
            "uncapped_profile_score": round(weighted_score, 5),
            "profile_delta": round(final_score - equal_score, 5),
            "breakdown": {
                "covered_themes": covered,
                "missing_themes": missing,
                "active_theme_weights": {theme: round(weight, 6) for theme, weight in weighted.items()},
            },
        })
    return sorted(rows, key=lambda row: row["score"], reverse=True)


def rescore_case(
    obj: dict[str, Any],
    *,
    dest_map: dict[str, str],
    pen_coef: float,
    floor: float,
    theme_id_weights: dict[str, float] | None,
    profile_cap: float | None,
) -> dict[str, Any]:
    case_id = obj.get("case_id")
    rows = score_rows(obj, pen_coef=pen_coef, theme_id_weights=theme_id_weights, profile_cap=profile_cap)
    dest = dest_map.get(stem(str(case_id)))
    if dest:
        selected = next((row for row in rows if row["ddb_pk"] == dest), None)
        if selected is None:
            return {"case_id": case_id, "branch": "no_candidate_anchored", "anchor": dest, "selected": None, "ranking": rows[:10]}
        return {"case_id": case_id, "branch": "anchored", "anchor": dest, "selected": selected, "ranking": rows[:10]}
    if not rows or rows[0]["score"] < floor:
        return {"case_id": case_id, "branch": "no_candidate", "selected": None, "ranking": rows[:10]}
    return {"case_id": case_id, "branch": "discovery", "selected": rows[0], "ranking": rows[:10]}


def compare(smoke_dir: Path, personas_path: Path, mocks_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    personas_doc = json.loads(personas_path.read_text(encoding="utf-8"))
    config = personas_doc["reference_tuning_config"]
    personas = personas_doc["personas"]
    files = [path for path in sorted(smoke_dir.glob("*.json")) if not path.name.startswith(("_summary", "rescore_", "selected_", "city_stats"))]
    objs = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    dest_map = load_dest_map(mocks_dir)
    baseline = [
        rescore_case(obj, dest_map=dest_map, pen_coef=1.0, floor=0.0, theme_id_weights=None, profile_cap=None)
        for obj in objs
    ]
    baseline_by_id = {case["case_id"]: case for case in baseline}
    multi_ids = {obj["case_id"] for obj in objs if len(obj.get("query", {}).get("themes", []) or []) >= 2}

    all_runs: list[dict[str, Any]] = []
    config_summaries: list[dict[str, Any]] = []
    representative: list[dict[str, Any]] = []
    activation = float(config["profile_activation_saved_trip_count"])
    for alpha in config["alpha_candidates"]:
        for weight_range in config["weight_range_candidates"]:
            for cap in config["profile_score_cap_candidates"]:
                config_id = f"alpha={alpha}|range={weight_range['id']}|cap={cap}"
                persona_rows: list[dict[str, Any]] = []
                for persona in personas:
                    weights = persona_weights(
                        persona,
                        alpha=float(alpha),
                        min_weight=float(weight_range["min"]),
                        max_weight=float(weight_range["max"]),
                        activation=activation,
                    )
                    cases = [
                        rescore_case(obj, dest_map=dest_map, pen_coef=1.0, floor=0.0, theme_id_weights=weights, profile_cap=float(cap))
                        for obj in objs
                    ]
                    changed = []
                    for case in cases:
                        base_selected = baseline_by_id[case["case_id"]].get("selected")
                        case_selected = case.get("selected")
                        before = base_selected.get("ddb_pk") if isinstance(base_selected, dict) else None
                        after = case_selected.get("ddb_pk") if isinstance(case_selected, dict) else None
                        if before != after:
                            changed.append({
                                "case_id": case["case_id"],
                                "before": before,
                                "after": after,
                                "branch": case["branch"],
                                "themes": next(obj.get("query", {}).get("themes", []) for obj in objs if obj["case_id"] == case["case_id"]),
                                "top3_after": [row["ddb_pk"] for row in case.get("ranking", [])[:3]],
                            })
                    row = {
                        "persona_id": persona["persona_id"],
                        "saved_trip_count": persona["saved_trip_count"],
                        "effective_theme_weights": weights,
                        "changed_count": len(changed),
                        "multi_theme_changed_count": sum(1 for item in changed if item["case_id"] in multi_ids),
                        "changed_cases": changed,
                    }
                    persona_rows.append(row)
                    if config_id == "alpha=1.5|range=medium|cap=0.05":
                        representative.append(row)
                counts = [row["changed_count"] for row in persona_rows]
                config_summaries.append({
                    "config_id": config_id,
                    "personas_with_any_change": sum(1 for count in counts if count > 0),
                    "persona_changed_min": min(counts),
                    "persona_changed_max": max(counts),
                    "persona_changed_avg": round(sum(counts) / len(counts), 3),
                })
                all_runs.append({"config_id": config_id, "personas": persona_rows})

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_json = out_dir / f"profile_rescore_comparison_{stamp}.json"
    out_md = out_dir / f"profile_rescore_comparison_{stamp}.md"
    payload = {
        "smoke_dir": str(smoke_dir),
        "persona_fixture": str(personas_path),
        "config_summaries": config_summaries,
        "representative_config": "alpha=1.5|range=medium|cap=0.05",
        "representative_personas": representative,
        "all_runs": all_runs,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(out_md, smoke_dir, config_summaries, representative)
    return out_json, out_md


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare profile persona theme-weight city rescore churn")
    parser.add_argument("--smoke-dir", default="docs/tasks/results/v2_retrieval_smoke/20260630T094517")
    parser.add_argument("--personas", default="docs/tasks/results/v2_profile_personas/profile_theme_personas.json")
    parser.add_argument("--mocks-dir", default="docs/tasks/results/v2_intent_mocks")
    parser.add_argument("--out-dir", default="docs/tasks/results/v2_profile_personas")
    args = parser.parse_args()
    out_json, out_md = compare(Path(args.smoke_dir), Path(args.personas), Path(args.mocks_dir), Path(args.out_dir))
    print(f"json: {out_json}")
    print(f"md: {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
