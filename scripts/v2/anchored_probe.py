#!/usr/bin/env python3
"""anchored(도시 고정) · 테마 필터 없는 검색 — intent mock → 일정 풀(Planner In-city Itinerary)을 본다.

retrieval_smoke.py와 **같은 케이스**(v2_retrieval_inputs의 raw/soft/themes)를 그대로 흘려보낸다.
궁극 목표: 그 intent mock에서 도시가 선택된 뒤, 그 도시 안에서 일정을 채울 풀이 실제로 나오는가.

흐름: intent mock → retrieval input(raw/soft) → city_select가 도시 선택 → **여기서** 그 도시 고정 +
      테마 OFF로 raw/soft 검색 → Planner가 일정을 짤 후보 풀.

anchor 도시 소스(우선순위): --selected JSON(case_id→ddb_pk, 오프라인 재채점 산출) > 케이스의 destination_id.
필터: {entity_type=attraction AND city_id=<resolved>} (theme_tags 조건 없음).
도시 고정: v2 metadata dump로 selected CITY#...를 city_id로 바꾼 뒤 직접 필터한다.

⚠ AWS(Bedrock·S3 Vectors) 필요 → repo 환경에서 실행. 임베딩 캐시는 retrieval_smoke와 공유.

사용:
  LOVV_ENABLE_AWS_SMOKE=1 python scripts/v2/anchored_probe.py --live \
      --selected docs/tasks/results/v2_retrieval_smoke/<ts>/selected_cities.json --top-k 100
옵션: --cases-dir · --selected · --metadata-dump · --top-k(기본 100) · --limit · --out-dir · --live
환경변수: retrieval_smoke.py와 동일.
"""
from __future__ import annotations
import argparse, datetime as _dt, glob, hashlib, json, os, sys
from typing import Any

VECTOR_BUCKET = os.environ.get("LOVV_VECTOR_BUCKET", "lovv-vector-dev")
VECTOR_INDEX = os.environ.get("LOVV_VECTOR_INDEX", "kr-tour-domain-v2")
EMBED_MODEL = os.environ.get("LOVV_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBED_DIM = 1024
ATTRACTION = "attraction"
DEFAULT_CASES = "docs/tasks/results/v2_retrieval_inputs"
DEFAULT_OUT = "docs/tasks/results/v2_anchored_probe"
DEFAULT_METADATA_DUMP = os.environ.get(
    "LOVV_V2_METADATA_DUMP",
    "metadata_audit/kr-tour-domain-v2-all-metadata-20260630T001340Z.json",
)
EXCLUDED_THEMES = frozenset({
    "food_local", "미식", "미식·노포", "미식/노포",
    "festival", "festival_event", "event", "축제", "축제·이벤트", "축제/이벤트"})


# ------------------------------------------------- 케이스 로딩 (retrieval_smoke와 동일 규약)
def load_cases(cases_dir: str, limit: int | None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(cases_dir, "**", "*.json"), recursive=True)):
        obj = json.load(open(path, encoding="utf-8"))
        if "intent_output" in obj:
            io = obj["intent_output"]
            raw = (io.get("cleaned_raw_query") or "").strip()
            soft = (io.get("soft_preference_query") or "").strip()
            themes = io.get("active_required_themes", [])
            dest = io.get("destination_id")
        else:
            raw = (obj.get("raw_query") or "").strip()
            soft = (obj.get("soft_query") or "").strip()
            themes = obj.get("themes", [])
            dest = obj.get("destination_id")
        themes = [t for t in themes if t not in EXCLUDED_THEMES]
        if not raw and not themes:
            continue
        cases.append({"case_id": obj.get("id") or os.path.basename(path),
                      "raw_query": raw or (soft or " ".join(themes)),
                      "soft_query": soft, "themes": themes, "destination_id": dest})
    return cases[:limit] if limit else cases


# ------------------------------------------------- 검색 (anchored, theme OFF)
def embed(bedrock, text, cache):
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if cache is not None and key in cache:
        return cache[key]
    resp = bedrock.invoke_model(
        modelId=EMBED_MODEL,
        body=json.dumps({"inputText": text, "dimensions": EMBED_DIM, "normalize": True}))
    vec = json.loads(resp["body"].read())["embedding"]
    if cache is not None:
        cache[key] = vec
    return vec


def _metadata_of(vector: Any) -> dict[str, Any]:
    if not isinstance(vector, dict):
        return {}
    metadata = vector.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def load_city_id_by_pk(metadata_dump: str) -> dict[str, str]:
    with open(metadata_dump, encoding="utf-8") as fh:
        payload = json.load(fh)
    city_id_by_pk: dict[str, str] = {}
    for record in payload.get("records", []):
        metadata = _metadata_of(record)
        ddb_pk = metadata.get("ddb_pk")
        city_id = metadata.get("city_id")
        if isinstance(ddb_pk, str) and isinstance(city_id, str):
            city_id_by_pk.setdefault(ddb_pk, city_id)
    return city_id_by_pk


def city_id_of_anchor(anchor: str | None, city_id_by_pk: dict[str, str]) -> str | None:
    if anchor is None:
        return None
    normalized = anchor.strip()
    if not normalized:
        return None
    if normalized.startswith("KR-"):
        return normalized
    return city_id_by_pk.get(normalized)


def _query_one_city(s3v, vec, city_id, top_k):
    resp = s3v.query_vectors(
        vectorBucketName=VECTOR_BUCKET, indexName=VECTOR_INDEX,
        queryVector={"float32": vec}, topK=top_k, returnMetadata=True, returnDistance=True,
        filter={"$and": [{"entity_type": {"$eq": ATTRACTION}}, {"city_id": {"$eq": city_id}}]})
    out = []
    for v in resp.get("vectors", []):
        m = _metadata_of(v)
        if m.get("city_id") != city_id:
            continue
        out.append({"place_id": m.get("place_id") or v.get("key"), "distance": v.get("distance"),
                    "title": m.get("title"), "theme_tags": list(m.get("theme_tags") or []),
                    "subtype": m.get("attraction_subtype_code"),
                    "lat": m.get("latitude"), "lon": m.get("longitude")})
    return out


def query_anchored(s3v, vec, city_id, top_k):
    by_id: dict[str, dict] = {}
    for c in _query_one_city(s3v, vec, city_id, top_k):
        prev = by_id.get(c["place_id"])
        if prev is None or (c["distance"] is not None and c["distance"] < prev["distance"]):
            by_id[c["place_id"]] = c
    return sorted(by_id.values(), key=lambda c: (c["distance"] is None, c["distance"]))[:top_k]


def summarize(cands: list[dict]) -> dict:
    theme_hist: dict[str, int] = {}
    subtype_hist: dict[str, int] = {}
    for c in cands:
        for t in c["theme_tags"]:
            theme_hist[t] = theme_hist.get(t, 0) + 1
        st = c.get("subtype") or "unknown"
        subtype_hist[st] = subtype_hist.get(st, 0) + 1
    dists = [c["distance"] for c in cands if c["distance"] is not None]
    ordered = sorted(cands, key=lambda c: (c["distance"] is None, c["distance"]))
    return {"candidate_count": len(cands),
            "best_distance": min(dists) if dists else None,
            "worst_distance": max(dists) if dists else None,
            "theme_hist": dict(sorted(theme_hist.items(), key=lambda kv: -kv[1])),
            "subtype_hist": dict(sorted(subtype_hist.items(), key=lambda kv: -kv[1])),
            "ranked": [{"rank": i + 1, **{k: c[k] for k in
                        ("place_id", "distance", "title", "theme_tags", "subtype", "lat", "lon")}}
                       for i, c in enumerate(ordered)]}


# ------------------------------------------------- 실행
def main() -> int:
    ap = argparse.ArgumentParser(description="anchored theme-off retrieval probe (case-driven)")
    ap.add_argument("--cases-dir", default=DEFAULT_CASES)
    ap.add_argument("--selected", default=None, help="case_id→ddb_pk JSON(오프라인 재채점 산출)")
    ap.add_argument("--top-k", type=int, default=100)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    ap.add_argument("--metadata-dump", default=DEFAULT_METADATA_DUMP)
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()

    cases = load_cases(args.cases_dir, args.limit)
    selected = json.load(open(args.selected, encoding="utf-8")) if args.selected else {}
    city_id_by_pk = load_city_id_by_pk(args.metadata_dump)

    def anchor_of(case):
        return selected.get(case["case_id"]) or case.get("destination_id")

    planned = [(c["case_id"], anchor_of(c)) for c in cases]
    have = [p for p in planned if p[1]]
    print(f"케이스 {len(cases)}개 · anchor 있음 {len(have)}개 (selected={bool(selected)}) top_k={args.top_k}")
    for cid, pk in planned:
        print(f"  - {cid}: anchor={pk or '(없음 - skip)'}")
    if not args.live:
        print("\n[dry-run] --live 없이 계획만. anchor 없는 케이스는 재채점 selected_cities.json 필요.")
        return 0
    if os.environ.get("LOVV_ENABLE_AWS_SMOKE") != "1":
        print("\n[중단] live 실행엔 LOVV_ENABLE_AWS_SMOKE=1 필요.", file=sys.stderr)
        return 2

    import boto3
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    s3v = boto3.client("s3vectors", region_name=REGION)
    cache_path = os.environ.get(
        "LOVV_EMBED_CACHE", "docs/tasks/results/v2_retrieval_smoke/.embed_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}

    run_dir = os.path.join(args.out_dir, _dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    summary = []
    for case in cases:
        pk = anchor_of(case)
        city_id = city_id_of_anchor(pk, city_id_by_pk)
        if not city_id:
            if pk:
                print(f"[skip] {case['case_id']} @ {pk}: city_id 해석 실패")
            continue
        raw_vec = embed(bedrock, case["raw_query"], cache)
        out: dict[str, Any] = {
            "case_id": case["case_id"], "anchor_city": pk, "anchor_city_id": city_id, "top_k": args.top_k,
            "query": {k: case[k] for k in ("raw_query", "soft_query", "themes")},
            "raw": summarize(query_anchored(s3v, raw_vec, city_id, args.top_k))}
        if case["soft_query"] and case["soft_query"] != case["raw_query"]:
            soft_vec = embed(bedrock, case["soft_query"], cache)
            out["soft"] = summarize(query_anchored(s3v, soft_vec, city_id, args.top_k))
        json.dump(out, open(os.path.join(run_dir, case["case_id"] + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        n = out["raw"]["candidate_count"]
        summary.append({"case_id": case["case_id"], "anchor_city": pk, "anchor_city_id": city_id, "raw_pool": n})
        print(f"[ok] {case['case_id']} @ {pk}/{city_id}: theme-off raw 풀 {n}개 · best={out['raw']['best_distance']}")
    json.dump({"top_k": args.top_k, "cases": summary},
              open(os.path.join(run_dir, "_summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(cache, open(cache_path, "w", encoding="utf-8"))
    print(f"\n저장: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
