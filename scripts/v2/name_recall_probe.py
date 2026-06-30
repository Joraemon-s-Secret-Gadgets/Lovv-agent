#!/usr/bin/env python3
"""이름 recall 검증 — 특정 관광지 이름을 포함해 검색하면 그 장소가 top-N에 실제로 뜨는가.

retrieval이 named entity를 존중하는지 확인(예: "경복궁 가고 싶어" → 경복궁이 상위에 와야 함).
전국(theme 무관) 검색으로 7073개 벡터 중 그 장소의 랭크를 본다.

타깃 지정 2가지:
  --names "첨성대,경복궁"                     # 직접 지정(쿼리=이름, --template로 문장화 가능)
  --sample-from-smoke <smoke_dir> --n 20      # 인덱스에 존재 확실한 제목을 무작위 샘플(ground-truth recall)

매칭: 결과 title이 타깃 이름을 포함(공백 무시, 대소문자 무시). --city로 동명 장소 구분.

⚠ AWS(Bedrock·S3 Vectors) 필요 → repo 실행. 임베딩 캐시는 retrieval_smoke와 공유.

사용:
  LOVV_ENABLE_AWS_SMOKE=1 python scripts/v2/name_recall_probe.py --live \
      --sample-from-smoke docs/tasks/results/v2_retrieval_smoke/20260629T171742 --n 20 --top-k 50
  LOVV_ENABLE_AWS_SMOKE=1 python scripts/v2/name_recall_probe.py --live \
      --names "첨성대,불국사" --template "{name} 둘러보는 여행" --top-k 50
"""
from __future__ import annotations
import argparse, glob, hashlib, json, os, random, sys
from typing import Any

VECTOR_BUCKET = os.environ.get("LOVV_VECTOR_BUCKET", "lovv-vector-dev")
VECTOR_INDEX = os.environ.get("LOVV_VECTOR_INDEX", "kr-tour-domain-v2")
EMBED_MODEL = os.environ.get("LOVV_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBED_DIM = 1024
ATTRACTION = "attraction"


def norm(s: str | None) -> str:
    return (s or "").replace(" ", "").lower()


# 부분명 테스트용 흔한 접미(가장 긴 것부터 제거)
_SUFFIXES = ["해수욕장", "관광단지", "관광지", "유원지", "전망대", "기념관", "기념비", "박물관",
             "미술관", "생태숲", "수목원", "휴양림", "유적지", "해안길", "출렁다리",
             "공원", "해변", "해안", "폭포", "계곡", "서원", "향교", "고분", "온천",
             "사찰", "항", "산", "사", "호", "교", "역", "탑", "성"]


def make_variants(name: str) -> dict[str, str]:
    """오타/부분명/띄어쓰기 변형 — vector가 정확 일치 없이도 그 장소를 찾는지 본다."""
    v = {"exact": name}
    ch = list(name)
    if len(ch) >= 3:
        v["drop_mid"] = "".join(ch[:-2] + ch[-1:])          # 가운데 음절 탈락(오타)
        v["swap_last2"] = "".join(ch[:-2] + ch[-1:] + ch[-2:-1])  # 끝 두 음절 자리바꿈
    for suf in _SUFFIXES:                                     # 접미 제거 → 핵심 부분명
        if name.endswith(suf) and len(name) - len(suf) >= 2:
            v["strip_suffix"] = name[: -len(suf)]
            break
    if len(ch) >= 4:
        v["spaced"] = " ".join(["".join(ch[: len(ch) // 2]), "".join(ch[len(ch) // 2:])])
    return v


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


def query(s3v, vec, top_k):
    resp = s3v.query_vectors(
        vectorBucketName=VECTOR_BUCKET, indexName=VECTOR_INDEX,
        queryVector={"float32": vec}, topK=top_k, returnMetadata=True, returnDistance=True,
        filter={"entity_type": {"$eq": ATTRACTION}})
    out = []
    for v in resp.get("vectors", []):
        m = v.get("metadata", {}) or {}
        out.append({"title": m.get("title"), "city_name_ko": m.get("city_name_ko"),
                    "distance": v.get("distance"), "place_id": m.get("place_id"),
                    "ddb_pk": m.get("ddb_pk")})
    return out


def sample_targets(smoke_dir: str, n: int) -> list[dict]:
    """스모크 결과에서 (title, city) 무작위 샘플 — 인덱스에 존재 확실."""
    seen = {}
    for f in glob.glob(os.path.join(smoke_dir, "*.json")):
        if os.path.basename(f).startswith(("_summary", "rescore_", "selected_", "city_stats")):
            continue
        o = json.load(open(f, encoding="utf-8"))
        for ch in o.get("channels", {}).values():
            for blk in (ch.get("no_theme"), *(ch.get("per_theme", {}) or {}).values()):
                for r in (blk or {}).get("ranked", []):
                    if r.get("title"):
                        seen[(r["title"], r.get("city_name_ko"))] = True
    keys = list(seen)
    random.seed(42)
    random.shuffle(keys)
    return [{"name": t, "city": c} for t, c in keys[:n]]


def main() -> int:
    ap = argparse.ArgumentParser(description="attraction name recall probe")
    ap.add_argument("--names", default=None, help="쉼표구분 타깃 이름")
    ap.add_argument("--sample-from-smoke", default=None)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--template", default="{name}", help="쿼리 템플릿, {name} 치환")
    ap.add_argument("--variants", action="store_true",
                    help="오타/부분명/띄어쓰기 변형도 각각 검색해 변형별 랭크 비교")
    ap.add_argument("--city", default=None, help="동명 구분용 city_name_ko 필터(직접 지정 시)")
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--out-dir", default="docs/tasks/results/v2_name_recall")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()

    if args.names:
        targets = [{"name": x.strip(), "city": args.city} for x in args.names.split(",") if x.strip()]
    elif args.sample_from_smoke:
        targets = sample_targets(args.sample_from_smoke, args.n)
    else:
        print("--names 또는 --sample-from-smoke 필요", file=sys.stderr); return 2

    print(f"타깃 {len(targets)}개 · template='{args.template}' · top_k={args.top_k}")
    if not args.live:
        for t in targets[:10]:
            print(f"  - {t['name']} ({t.get('city')}) → query='{args.template.format(name=t['name'])}'")
        print("\n[dry-run] --live 없이 계획만.")
        return 0
    if os.environ.get("LOVV_ENABLE_AWS_SMOKE") != "1":
        print("\n[중단] LOVV_ENABLE_AWS_SMOKE=1 필요.", file=sys.stderr); return 2

    import boto3, datetime as _dt
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    s3v = boto3.client("s3vectors", region_name=REGION)
    cache_path = os.environ.get(
        "LOVV_EMBED_CACHE", "docs/tasks/results/v2_retrieval_smoke/.embed_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}

    def rank_of(target, q):
        ranked = query(s3v, embed(bedrock, q, cache), args.top_k)
        for i, r in enumerate(ranked, 1):
            if norm(target["name"]) in norm(r.get("title")) and (
                    not target.get("city") or target["city"] == r.get("city_name_ko")):
                return i, ranked
        return None, ranked

    results = []
    per_variant = {}   # variant_label -> {rank1, rank2_5, rank_tail, miss}
    for t in targets:
        variants = make_variants(t["name"]) if args.variants else {"exact": args.template.format(name=t["name"])}
        row = {"name": t["name"], "city": t.get("city"), "variants": {}}
        for label, q in variants.items():
            rank, ranked = rank_of(t, q)
            row["variants"][label] = {"query": q, "rank": rank,
                                      "top1": (f"{ranked[0]['title']}({ranked[0]['city_name_ko']})"
                                               if ranked else None)}
            b = per_variant.setdefault(label, {"rank1": 0, "rank2_5": 0, "rank_tail": 0, "miss": 0})
            if rank == 1: b["rank1"] += 1
            elif rank and rank <= 5: b["rank2_5"] += 1
            elif rank: b["rank_tail"] += 1
            else: b["miss"] += 1
        results.append(row)
        summary = " · ".join(f"{l}:{('r'+str(d['rank'])) if d['rank'] else 'MISS'}"
                             for l, d in row["variants"].items())
        print(f"  '{t['name']}' → {summary}")

    run_dir = os.path.join(args.out_dir, _dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    json.dump({"top_k": args.top_k, "template": args.template, "variants_on": args.variants,
               "per_variant": per_variant, "results": results},
              open(os.path.join(run_dir, "recall.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(cache, open(cache_path, "w", encoding="utf-8"))
    print(f"\n변형별 요약 (n={len(targets)}, top_k={args.top_k}):")
    for label, b in per_variant.items():
        print(f"  {label:<12} rank1={b['rank1']} rank2-5={b['rank2_5']} "
              f"rank6-{args.top_k}={b['rank_tail']} MISS={b['miss']}")
    print(f"저장: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
