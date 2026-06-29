#!/usr/bin/env python3
"""스모크 결과의 city 합집합에 대해 DynamoDB에서 visitor stats(congestion)를 가져온다.

오프라인 재채점에 congestion_penalty를 넣기 위한 보조 데이터.
- congestion: PK=CITY#NAME, SK begins_with STAT# → 월별 total_visitors → 연 합계.
- 좌표는 여기서 안 가져옴(centroid 없음). distance_penalty용 좌표는 벡터 메타데이터의 place lat/lon.
- found=false = 좌표 부재가 아니라 **PK key 불일치로 조회 실패**(casing/이름 변경). 대문자 정규화로 대부분 해소.

⚠ AWS(DynamoDB) 필요 → repo 환경에서 실행. (조회만, PAY_PER_REQUEST라 비용 미미)

사용:
  python scripts/v2/fetch_city_stats.py docs/tasks/results/v2_retrieval_smoke/<ts>
  → 같은 폴더에 city_stats.json 저장
환경변수: LOVV_DDB_TABLE(기본 TourKoreaDomainDataV2) · AWS_REGION(기본 us-east-1)
"""
from __future__ import annotations
import glob, json, os, sys
from decimal import Decimal

TABLE = os.environ.get("LOVV_DDB_TABLE", "TourKoreaDomainDataV2")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# 스모크 PK ↔ DynamoDB 실제 PK 불일치 수동 매핑(동명 도시 등). 필요 시 추가.
PK_ALIASES: dict[str, list[str]] = {
    "CITY#GOSEONG": ["CITY#GOSEONG-GANGWON"],  # 강원 고성(경남 고성과 구분). DynamoDB는 -GANGWON 접미.
}


def _num(x):
    return float(x) if isinstance(x, Decimal) else x


def pk_variants(pk: str) -> list[str]:
    """현재 인덱스가 대문자(CITY#ANDONG)/타이틀케이스(CITY#Andong) 두 적재로 쪼개져 있어
    canonical은 대문자지만, 데이터가 둘 다 존재할 수 있어 두 형태를 모두 조회 대상으로 둔다."""
    body = pk.split("#", 1)[1] if "#" in pk else pk
    cands = {f"CITY#{body.upper()}", f"CITY#{body.capitalize()}"}
    return sorted(cands)


def collect_city_pks(smoke_dir: str) -> dict[str, dict]:
    """스모크 ranked에서 도시 합집합. **대문자 PK로 병합**(casing split 통합).
    반환: {CANONICAL_UPPER_PK: {"name": …, "variants": [원본 casing들]}}."""
    pks: dict[str, dict] = {}
    for f in glob.glob(os.path.join(smoke_dir, "*.json")):
        if f.endswith("_summary.json"):
            continue
        obj = json.load(open(f, encoding="utf-8"))
        for ch in obj.get("channels", {}).values():
            for block in (ch.get("no_theme"), *(ch.get("per_theme", {}) or {}).values(),
                          ch.get("per_theme_union")):
                for r in (block or {}).get("ranked", []):
                    pk = r.get("ddb_pk")
                    if not pk:
                        continue
                    canon = pk.upper()
                    e = pks.setdefault(canon, {"name": r.get("city_name_ko"), "variants": set()})
                    e["variants"].add(pk)
                    e["name"] = e["name"] or r.get("city_name_ko")
    return {k: {"name": v["name"], "variants": sorted(v["variants"])} for k, v in pks.items()}


def fetch(table, canon_pk: str, variants: list[str]) -> dict:
    """congestion(STAT#)만 조회. 좌표는 여기서 안 가져옴(벡터 메타 place lat/lon에서 별도 취득).
    'found:false'는 좌표 부재가 아니라 **PK key 불일치로 조회 실패**(casing/이름 변경)를 의미."""
    from boto3.dynamodb.conditions import Key
    out = {"found": False, "annual_visitors": None, "by_month": {}, "stat_pk_used": None}
    query_pks = [canon_pk] + [v for v in variants if v != canon_pk] + PK_ALIASES.get(canon_pk, [])
    # STAT# (월별 방문자) — variant 중 데이터 있는 첫 PK 사용(중복 합산 방지)
    for pk in query_pks:
        items = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("STAT#")).get("Items", [])
        if items:
            total = 0.0
            for it in items:
                month = (it.get("SK", "") or "").replace("STAT#", "")
                tv = _num((it.get("statistics", {}) or {}).get("total_visitors"))
                if tv is not None:
                    out["by_month"][month] = tv
                    total += tv
            out["annual_visitors"] = total if out["by_month"] else None
            out["stat_pk_used"] = pk
            out["found"] = True
            break
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: fetch_city_stats.py <smoke_result_dir> [--only CITY#A,CITY#B]", file=sys.stderr)
        return 2
    smoke_dir = sys.argv[1]
    only = None
    if "--only" in sys.argv:
        only = [p.strip().upper() for p in sys.argv[sys.argv.index("--only") + 1].split(",") if p.strip()]
    import boto3
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)

    out_path = os.path.join(smoke_dir, "city_stats.json")
    # --only: 특정 도시만 다시 받아 기존 city_stats.json에 병합(전체 재실행 안 함).
    if only:
        result = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
        for pk in only:
            data = fetch(table, pk, pk_variants(pk))
            data["city_name_ko"] = result.get(pk, {}).get("city_name_ko")
            data["variants"] = pk_variants(pk)
            result[pk] = data
            print(f"{pk}: found={data['found']} stat_pk_used={data.get('stat_pk_used')} "
                  f"annual={data.get('annual_visitors')}")
        json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"병합 저장: {out_path}")
        return 0

    pks = collect_city_pks(smoke_dir)
    n_variants = sum(len(v["variants"]) for v in pks.values())
    print(f"city 합집합: {len(pks)}개 canonical(대문자) / 원본 {n_variants}개 casing (table={TABLE})")
    result = {}
    missing = []
    for i, (pk, meta) in enumerate(sorted(pks.items()), 1):
        try:
            data = fetch(table, pk, meta["variants"])
        except Exception as e:  # noqa: BLE001
            data = {"found": False, "error": str(e)}
        data["city_name_ko"] = meta["name"]
        data["variants"] = meta["variants"]
        result[pk] = data
        if not data.get("found"):
            missing.append(pk)
        if i % 25 == 0:
            print(f"  {i}/{len(pks)} ...")
    out_path = os.path.join(smoke_dir, "city_stats.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    found = sum(1 for v in result.values() if v.get("found"))
    print(f"\n완료: {found}/{len(pks)} found, 누락 {len(missing)}개 (예: {missing[:8]})")
    print(f"저장: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
