#!/usr/bin/env python3
"""DynamoDB 단건/도시별 조회 — V2 retrieval 결과를 직접 확인용.

벡터 hit의 ddb_pk/ddb_sk(또는 도시 PK)로 TourKoreaDomainDataV2를 조회해 description·세부정보를 본다.

사용:
  # 단건 (PK + SK)
  python scripts/v2/ddb_inspect.py CITY#YEOSU ATTRACTION#2647864
  # 도시의 관광지 전체
  python scripts/v2/ddb_inspect.py --city CITY#GANGNEUNG
  # 도시의 특정 엔티티(접두어)
  python scripts/v2/ddb_inspect.py --city CITY#GANGNEUNG --sk-prefix FESTIVAL#
  # 결과 파일 저장
  python scripts/v2/ddb_inspect.py CITY#YEOSU ATTRACTION#2647864 --out item.json

환경변수: LOVV_DDB_TABLE(기본 TourKoreaDomainDataV2) · AWS_REGION(기본 us-east-1)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from typing import Any

TABLE = os.environ.get("LOVV_DDB_TABLE", "TourKoreaDomainDataV2")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def _default(o: Any) -> Any:
    return float(o) if isinstance(o, Decimal) else str(o)


def _table() -> Any:
    import boto3
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def get_item(table: Any, pk: str, sk: str) -> dict[str, Any] | None:
    return table.get_item(Key={"PK": pk, "SK": sk}).get("Item")


def query_city(table: Any, pk: str, sk_prefix: str | None) -> list[dict[str, Any]]:
    from boto3.dynamodb.conditions import Key
    cond = Key("PK").eq(pk)
    if sk_prefix:
        cond = cond & Key("SK").begins_with(sk_prefix)
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"KeyConditionExpression": cond}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description="DynamoDB V2 inspect")
    ap.add_argument("pk", nargs="?", help="PK (예: CITY#YEOSU)")
    ap.add_argument("sk", nargs="?", help="SK (예: ATTRACTION#2647864)")
    ap.add_argument("--city", help="도시 PK 전체/접두 조회 (예: CITY#GANGNEUNG)")
    ap.add_argument("--sk-prefix", help="--city와 함께 SK 접두 (예: ATTRACTION# / FESTIVAL# / STAT#)")
    ap.add_argument("--out", help="결과 JSON 저장 경로")
    args = ap.parse_args()

    table = _table()
    if args.city:
        result: Any = query_city(table, args.city, args.sk_prefix)
        print(f"{args.city} ({args.sk_prefix or '전체'}): {len(result)}건", file=sys.stderr)
    elif args.pk and args.sk:
        result = get_item(table, args.pk, args.sk)
        if result is None:
            print(f"[not found] PK={args.pk} SK={args.sk}", file=sys.stderr)
            return 1
    else:
        ap.error("PK+SK 또는 --city 필요")
        return 2

    text = json.dumps(result, ensure_ascii=False, indent=2, default=_default)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"저장: {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
