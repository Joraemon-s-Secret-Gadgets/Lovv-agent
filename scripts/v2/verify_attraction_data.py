#!/usr/bin/env python3
"""인출된 attraction의 DynamoDB 원본을 가져와 정성 검증 — 특히 `설명(description)` 채움률·정서성.

목적:
  (a) soft HyDE 게이트: description이 실제로 있고 분위기를 담는가(없으면 soft가 장소 레벨에서도 약함).
  (b) 일반 데이터 품질: title/theme/address/좌표 결측, casing/키 문제로 인한 조회 실패율.

키 사용: 스모크의 **원본 ddb_pk/ddb_sk**로 GetItem(개별 레코드는 적재된 그 키에 존재).
miss 시 정규화 variant(대문자 PK, GOSEONG→-GANGWON alias)로 1회 폴백 → 키 불일치율도 측정.

⚠ AWS(DynamoDB) 필요 → repo 실행. batch_get(100/콜)이라 비용·시간 적음.

사용:
  python scripts/v2/verify_attraction_data.py docs/tasks/results/v2_retrieval_smoke/<ts> --sample 400
"""
from __future__ import annotations
import argparse, glob, json, os, random, sys
from decimal import Decimal

TABLE = os.environ.get("LOVV_DDB_TABLE", "TourKoreaDomainDataV2")
REGION = os.environ.get("AWS_REGION", "us-east-1")
# 분위기/정서 어휘(설명이 정서적인지 거친 휴리스틱)
MOOD_WORDS = ["조용", "한적", "고요", "고즈넉", "평온", "아늑", "정취", "여유", "낭만", "감성",
              "분위기", "풍경", "절경", "탁 트", "걷기", "산책", "쉬", "힐링", "여유로", "운치"]


def _norm(pk: str) -> list[str]:
    body = pk.split("#", 1)[1] if "#" in pk else pk
    out = {pk, f"CITY#{body.upper()}", f"CITY#{body.capitalize()}"}
    if pk.upper() == "CITY#GOSEONG":
        out.add("CITY#GOSEONG-GANGWON")
    return list(out)


def collect_keys(smoke_dir: str) -> list[tuple[str, str]]:
    seen = set()
    for f in glob.glob(os.path.join(smoke_dir, "*.json")):
        if os.path.basename(f).startswith(("_summary", "rescore_", "selected_", "city_stats")):
            continue
        o = json.load(open(f, encoding="utf-8"))
        for ch in o.get("channels", {}).values():
            for blk in (ch.get("no_theme"), *(ch.get("per_theme", {}) or {}).values()):
                for r in (blk or {}).get("ranked", []):
                    pk, sk = r.get("ddb_pk"), r.get("ddb_sk")
                    if pk and sk:
                        seen.add((pk, sk))
    return sorted(seen)


def batch_get(client, keys: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    found = {}
    for i in range(0, len(keys), 100):
        chunk = keys[i:i + 100]
        req = {TABLE: {"Keys": [{"PK": pk, "SK": sk} for pk, sk in chunk]}}
        while req:
            resp = client.batch_get_item(RequestItems=req)
            for it in resp.get("Responses", {}).get(TABLE, []):
                found[(it["PK"], it["SK"])] = it
            req = resp.get("UnprocessedKeys") or None
    return found


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: verify_attraction_data.py <smoke_dir> [--sample N]", file=sys.stderr); return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("smoke_dir")
    ap.add_argument("--sample", type=int, default=400)
    args = ap.parse_args()

    import boto3
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE)

    keys = collect_keys(args.smoke_dir)
    print(f"distinct attraction 키: {len(keys)}개")
    if args.sample and len(keys) > args.sample:
        random.seed(42); keys = random.sample(keys, args.sample)
        print(f"  → {args.sample}개 무작위 샘플")

    # 원본 키로 batch_get (resource = native 타입 반환)
    found, miss = {}, []
    for i in range(0, len(keys), 100):
        chunk = keys[i:i + 100]
        req = {TABLE: {"Keys": [{"PK": pk, "SK": sk} for pk, sk in chunk]}}
        got = set()
        while req:
            resp = dynamodb.batch_get_item(RequestItems=req)
            for it in resp.get("Responses", {}).get(TABLE, []):
                found[(it["PK"], it["SK"])] = it; got.add((it["PK"], it["SK"]))
            req = resp.get("UnprocessedKeys") or None
        miss.extend(k for k in chunk if k not in got)

    # miss → 정규화 variant 폴백(개별 GetItem) = 키 불일치(casing/이름) 복구
    recovered = 0
    for pk, sk in list(miss):
        for vpk in _norm(pk):
            if vpk == pk:
                continue
            it = table.get_item(Key={"PK": vpk, "SK": sk}).get("Item")
            if it:
                found[(pk, sk)] = {"__recovered_pk": vpk, **it}; recovered += 1
                miss.remove((pk, sk)); break

    total = len(keys)
    desc_present = desc_mood = 0
    samples_mood, samples_dry, samples_nodesc = [], [], []
    lens = []
    for (pk, sk), it in found.items():
        d = it.get("description")
        d = str(d) if d not in (None, "") else ""
        title = str(it.get("title") or "")
        if d:
            desc_present += 1; lens.append(len(d))
            if any(w in d for w in MOOD_WORDS):
                desc_mood += 1
                if len(samples_mood) < 4: samples_mood.append((title, d[:120]))
            elif len(samples_dry) < 4:
                samples_dry.append((title, d[:120]))
        elif len(samples_nodesc) < 4:
            samples_nodesc.append(title)

    nf = len(found)
    print(f"\n조회 성공 {nf}/{total} (variant로 복구 {recovered}, 최종 miss {len(miss)})")
    if nf:
        print(f"description 있음: {desc_present}/{nf} ({100*desc_present/nf:.0f}%)")
        if desc_present:
            print(f"  그 중 분위기 어휘 포함: {desc_mood}/{desc_present} ({100*desc_mood/desc_present:.0f}%)")
            print(f"  설명 평균 길이: {sum(lens)//len(lens)}자")
    print("\n[분위기형 설명 샘플]")
    for t, d in samples_mood: print(f"  · {t}: {d}")
    print("\n[사실형 설명 샘플]")
    for t, d in samples_dry: print(f"  · {t}: {d}")
    print("\n[설명 없는 장소 샘플]")
    for t in samples_nodesc: print(f"  · {t}")

    out = os.path.join(args.smoke_dir, "attraction_data_audit.json")
    json.dump({"total": total, "found": nf, "final_miss": len(miss), "variant_recovered": recovered,
               "desc_present": desc_present, "desc_mood": desc_mood,
               "miss_keys": miss[:50]}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
