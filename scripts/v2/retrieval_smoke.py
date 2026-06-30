#!/usr/bin/env python3
"""V2 retrieval characterization smoke script (direct boto3, 실측 메타데이터 기준).

목적: city_select/planner의 핵심 "raw/soft query로 검색해 TOP-N 가져오기"를 V2 실데이터로 특성 분석.
  - theme 필터 ON/OFF 차이
  - theme별 TOP-N 안에 도시 몇 개, 도시별 관광지 몇 개 (+ 세부타입 분포)
  - raw vs soft 채널 차이
  - AND 게이트(모든 theme 보유 도시만 생존) 생존/탈락 = C2a soft 게이트의 baseline 정량화
  - (옵션) --enrich-top N: 상위 N개를 ddb_pk/ddb_sk로 DynamoDB 조회해 description·address 첨부
결과는 JSON으로 저장.

★ 인덱스/메타데이터 (실측):
  vector: lovv-vector-dev / kr-tour-domain-v2 (Titan Embed Text v2, 1024-dim)
  metadata: city_id·city_name_ko·entity_type·place_id·title·theme_tags·attraction_subtype_code
          · ddb_pk(CITY#영문)·ddb_sk(ATTRACTION#content_id)·latitude·longitude ...
  dynamo: TourKoreaDomainDataV2, GetItem(PK=ddb_pk, SK=ddb_sk) → description·address·season_tags·visit_months

⚠ 실행에 AWS(Bedrock·S3 Vectors·DynamoDB) 필요. Cowork 샌드박스 불가 → repo 환경에서 실행.

사용:
  python scripts/v2/retrieval_smoke.py                       # dry-run(케이스·계획만)
  LOVV_ENABLE_AWS_SMOKE=1 python scripts/v2/retrieval_smoke.py --live --top-k 30 --enrich-top 5
옵션: --cases-dir / --out-dir / --top-k / --limit / --enrich-top
환경변수: LOVV_VECTOR_BUCKET · LOVV_VECTOR_INDEX · LOVV_EMBED_MODEL · LOVV_DDB_TABLE · AWS_REGION
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import hashlib
import json
import os
import sys
from decimal import Decimal
from typing import Any

VECTOR_BUCKET = os.environ.get("LOVV_VECTOR_BUCKET", "lovv-vector-dev")
VECTOR_INDEX = os.environ.get("LOVV_VECTOR_INDEX", "kr-tour-domain-v2")
EMBED_MODEL = os.environ.get("LOVV_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
DDB_TABLE = os.environ.get("LOVV_DDB_TABLE", "TourKoreaDomainDataV2")
REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBED_DIM = 1024
ATTRACTION = "attraction"

# 관광지 vector 검색 제외 theme(미식/축제) — per-theme 검색 대상 아님.
EXCLUDED_THEMES = frozenset({
    "food_local", "미식", "미식·노포", "미식/노포",
    "festival", "festival_event", "event", "축제", "축제·이벤트", "축제/이벤트",
})
# DynamoDB 조회 시 가져올 세부 필드(확인용).
DETAIL_FIELDS = ("title", "description", "address", "theme_tags", "season_tags",
                 "visit_months", "image_url", "quality_status", "latitude", "longitude")

DEFAULT_CASES = "docs/tasks/results/v2_retrieval_inputs"
DEFAULT_OUT = "docs/tasks/results/v2_retrieval_smoke"


def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


# ---------------------------------------------------------------- 케이스 로딩
def load_cases(cases_dir: str, limit: int | None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(cases_dir, "**", "*.json"), recursive=True)):
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        if "intent_output" in obj:                 # V2 mock(full contract)
            io = obj["intent_output"]
            raw = (io.get("cleaned_raw_query") or "").strip()
            soft = (io.get("soft_preference_query") or "").strip()
            themes = io.get("active_required_themes", [])
            dest = io.get("destination_id")
        else:                                      # 평면 검색 입력 {raw_query,soft_query,themes}
            raw = (obj.get("raw_query") or "").strip()
            soft = (obj.get("soft_query") or "").strip()
            themes = obj.get("themes", [])
            dest = obj.get("destination_id")
        themes = [t for t in themes if t not in EXCLUDED_THEMES]
        if not raw and not themes:
            continue
        cases.append({
            "case_id": obj.get("id") or os.path.basename(path),
            "raw_query": raw or (soft or " ".join(themes)),
            "soft_query": soft,
            "themes": themes,
            "destination_id": dest,
        })
    return cases[:limit] if limit else cases


# ---------------------------------------------------------------- AWS 호출
def _clients() -> tuple[Any, Any, Any]:
    import boto3
    table = boto3.resource("dynamodb", region_name=REGION).Table(DDB_TABLE)
    return (boto3.client("bedrock-runtime", region_name=REGION),
            boto3.client("s3vectors", region_name=REGION),
            table)


def embed(bedrock: Any, text: str, cache: dict[str, Any] | None = None) -> list[float]:
    """텍스트 임베딩. cache(dict)가 주어지면 sha256(text) 키로 재사용 → 반복 실행 시 재호출 0."""
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if cache is not None and key in cache:
        return cache[key]
    resp = bedrock.invoke_model(
        modelId=EMBED_MODEL,
        body=json.dumps({"inputText": text, "dimensions": EMBED_DIM, "normalize": True}),
    )
    vec = json.loads(resp["body"].read())["embedding"]
    if cache is not None:
        cache[key] = vec
    return vec


def _filter(theme: str | None) -> dict[str, Any]:
    conds: list[dict[str, Any]] = [{"entity_type": {"$eq": ATTRACTION}}]
    if theme is not None:
        conds.append({"theme_tags": {"$eq": theme}})
    return conds[0] if len(conds) == 1 else {"$and": conds}


def query(s3vectors: Any, vec: list[float], *, theme: str | None, top_k: int) -> list[dict[str, Any]]:
    resp = s3vectors.query_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=VECTOR_INDEX,
        queryVector={"float32": vec},
        topK=top_k,
        returnMetadata=True,
        returnDistance=True,
        filter=_filter(theme),
    )
    out: list[dict[str, Any]] = []
    for v in resp.get("vectors", []):
        m = v.get("metadata", {}) or {}
        out.append({
            "place_id": m.get("place_id") or m.get("source_id") or v.get("key") or v.get("id"),
            "distance": v.get("distance"),
            "city_id": m.get("city_id") or m.get("city_name_ko") or "unknown",
            "city_name_ko": m.get("city_name_ko"),
            "title": m.get("title"),
            "theme_tags": list(m.get("theme_tags") or []),
            "subtype": m.get("attraction_subtype_code"),
            "ddb_pk": m.get("ddb_pk"),
            "ddb_sk": m.get("ddb_sk"),
            "lat": m.get("latitude"),
            "lon": m.get("longitude"),
        })
    return out


def fetch_details(table: Any, pk: str | None, sk: str | None) -> dict[str, Any] | None:
    """ddb_pk/ddb_sk로 DynamoDB attraction 레코드의 description·세부정보 조회."""
    if not pk or not sk:
        return None
    item = table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
    if not item:
        return {"_not_found": True, "pk": pk, "sk": sk}
    return {k: item.get(k) for k in DETAIL_FIELDS if k in item}


# ---------------------------------------------------------------- 메트릭
def _merge(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for c in cands:
        prev = by_id.get(c["place_id"])
        if prev is None or (c["distance"] is not None and c["distance"] < prev["distance"]):
            by_id[c["place_id"]] = c
    return list(by_id.values())


def _city_breakdown(cands: list[dict[str, Any]]) -> dict[str, Any]:
    cities: dict[str, dict[str, Any]] = {}
    for c in cands:
        b = cities.setdefault(c["city_id"], {
            "city_name_ko": c["city_name_ko"], "count": 0, "titles": [], "subtypes": {}})
        b["count"] += 1
        if len(b["titles"]) < 5:
            b["titles"].append(c["title"])
        st = c.get("subtype") or "unknown"
        b["subtypes"][st] = b["subtypes"].get(st, 0) + 1
    return {"distinct_cities": len(cities),
            "cities": dict(sorted(cities.items(), key=lambda kv: kv[1]["count"], reverse=True))}


def _and_gate(union: list[dict[str, Any]], themes: list[str]) -> dict[str, Any]:
    """도시별 theme 보유 → 모든 theme 보유 도시만 생존(V1 prune AND 게이트 동등)."""
    by_city: dict[str, set[str]] = {}
    name: dict[str, str | None] = {}
    for c in union:
        by_city.setdefault(c["city_id"], set()).update(c["theme_tags"])
        name[c["city_id"]] = c["city_name_ko"]
    survived = [cid for cid, tags in by_city.items() if all(t in tags for t in themes)]
    eliminated = [cid for cid in by_city if cid not in survived]
    return {"survived_city_count": len(survived),
            "survived_cities": [{"city_id": c, "city_name_ko": name.get(c)} for c in survived],
            "eliminated_city_count": len(eliminated),
            "eliminated_cities": [{"city_id": c, "city_name_ko": name.get(c)} for c in eliminated],
            "note": "eliminated = AND가 죽이는 도시(soft면 살릴 후보) = C2a 효과"}


def _ranked(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """distance 오름차순 정렬된 후보 리스트(top_k 전부). top-N<top_k는 이걸 슬라이스."""
    ordered = sorted(cands, key=lambda c: (c["distance"] is None, c["distance"]))
    return [{"rank": i + 1, **{k: c[k] for k in (
        "place_id", "distance", "city_id", "city_name_ko", "title",
        "theme_tags", "subtype", "ddb_pk", "ddb_sk", "lat", "lon")}} for i, c in enumerate(ordered)]


def _pack(cands: list[dict[str, Any]]) -> dict[str, Any]:
    """집계(도시 breakdown) + ranked(정렬 후보 전체) — 한 번 100으로 돌려 N 슬라이스 가능."""
    return {"candidate_count": len(cands), "ranked": _ranked(cands), **_city_breakdown(cands)}


def characterize(s3v: Any, vec: list[float], themes: list[str], top_k: int) -> dict[str, Any]:
    no_theme = query(s3v, vec, theme=None, top_k=top_k)
    per_theme: dict[str, Any] = {}
    union: list[dict[str, Any]] = []
    for t in themes:
        hits = query(s3v, vec, theme=t, top_k=top_k)
        union.extend(hits)
        per_theme[t] = _pack(hits)
    union_m = _merge(union)
    res: dict[str, Any] = {
        "no_theme": _pack(no_theme),
        "per_theme": per_theme,
        "per_theme_union": _pack(union_m),
    }
    if themes:
        res["and_gate"] = _and_gate(union_m, themes)
    return res


def _overlap(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    ap, bp = {c["place_id"] for c in a}, {c["place_id"] for c in b}
    ac, bc = {c["city_id"] for c in a}, {c["city_id"] for c in b}
    u = len(ap | bp)
    return {"place_jaccard": round(len(ap & bp) / u, 4) if u else None,
            "city_overlap": sorted(ac & bc),
            "raw_only_cities": sorted(ac - bc), "soft_only_cities": sorted(bc - ac)}


def _enrich(table: Any, cands: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """distance 오름차순 상위 n개를 DynamoDB로 세부정보 조회."""
    top = sorted([c for c in cands if c.get("distance") is not None],
                 key=lambda c: c["distance"])[:n]
    out: list[dict[str, Any]] = []
    for c in top:
        row = {k: c[k] for k in ("place_id", "city_name_ko", "title", "distance", "ddb_pk", "ddb_sk")}
        row["details"] = fetch_details(table, c.get("ddb_pk"), c.get("ddb_sk"))
        out.append(row)
    return out


# ---------------------------------------------------------------- 실행
def run(cases: list[dict[str, Any]], top_k: int, out_dir: str, enrich_top: int) -> None:
    bedrock, s3v, ddb = _clients()
    run_dir = os.path.join(out_dir, _dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    # 임베딩 캐시(영속): 같은 텍스트는 재호출 안 함. out_dir 공유.
    cache_path = os.environ.get("LOVV_EMBED_CACHE", os.path.join(out_dir, ".embed_cache.json"))
    cache: dict[str, Any] = (
        json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {})
    cache_start = len(cache)
    summary: list[dict[str, Any]] = []
    for case in cases:
        raw_vec = embed(bedrock, case["raw_query"], cache)
        out: dict[str, Any] = {
            "case_id": case["case_id"], "top_k": top_k,
            "index": {"bucket": VECTOR_BUCKET, "index": VECTOR_INDEX, "model": EMBED_MODEL},
            "query": {k: case[k] for k in ("raw_query", "soft_query", "themes")},
            "channels": {"raw": characterize(s3v, raw_vec, case["themes"], top_k)},
        }
        if case["soft_query"] and case["soft_query"] != case["raw_query"]:
            soft_vec = embed(bedrock, case["soft_query"], cache)
            out["channels"]["soft"] = characterize(s3v, soft_vec, case["themes"], top_k)
            out["raw_vs_soft"] = _overlap(
                query(s3v, raw_vec, theme=None, top_k=top_k),
                query(s3v, soft_vec, theme=None, top_k=top_k))
        if enrich_top > 0:
            out["enriched_raw_top"] = _enrich(
                ddb, query(s3v, raw_vec, theme=None, top_k=max(top_k, enrich_top)), enrich_top)
        with open(os.path.join(run_dir, case["case_id"] + ".json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2, default=_json_default)
        raw_ch = out["channels"]["raw"]
        ag = raw_ch.get("and_gate", {})
        summary.append({"case_id": case["case_id"], "themes": case["themes"],
                        "no_theme_cities": raw_ch["no_theme"]["distinct_cities"],
                        "union_cities": raw_ch["per_theme_union"]["distinct_cities"],
                        "and_survived": ag.get("survived_city_count"),
                        "and_eliminated": ag.get("eliminated_city_count")})
        print(f"[ok] {case['case_id']}: no_theme={summary[-1]['no_theme_cities']} cities · "
              f"AND survived={ag.get('survived_city_count')} eliminated={ag.get('eliminated_city_count')}")
    with open(os.path.join(run_dir, "_summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"top_k": top_k, "index": VECTOR_INDEX, "case_count": len(cases), "cases": summary},
                  fh, ensure_ascii=False, indent=2, default=_json_default)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)
    print(f"임베딩 캐시: {len(cache)}개 (신규 {len(cache) - cache_start}) → {cache_path}")
    print(f"\n결과 저장: {run_dir}")


def main() -> int:
    ap = argparse.ArgumentParser(description="V2 retrieval characterization smoke")
    ap.add_argument("--cases-dir", default=DEFAULT_CASES)
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    ap.add_argument("--top-k", type=int, default=30)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--enrich-top", type=int, default=0,
                    help="상위 N개를 DynamoDB로 description·세부정보 조회(0=off)")
    ap.add_argument("--live", action="store_true", help="실제 AWS 호출")
    args = ap.parse_args()

    cases = load_cases(args.cases_dir, args.limit)
    print(f"케이스 {len(cases)}개 로드 · index={VECTOR_INDEX} bucket={VECTOR_BUCKET} ddb={DDB_TABLE}")
    for c in cases:
        print(f"  - {c['case_id']}: themes={c['themes']} dest={c['destination_id']}")
    if not args.live:
        print("\n[dry-run] --live 없이 계획만. 실제 검색은 LOVV_ENABLE_AWS_SMOKE=1 + --live.")
        return 0
    if os.environ.get("LOVV_ENABLE_AWS_SMOKE") != "1":
        print("\n[중단] live 실행엔 LOVV_ENABLE_AWS_SMOKE=1 필요(과금 방지 가드).", file=sys.stderr)
        return 2
    run(cases, args.top_k, args.out_dir, args.enrich_top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
