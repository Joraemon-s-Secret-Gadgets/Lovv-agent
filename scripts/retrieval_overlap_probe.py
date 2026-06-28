# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "boto3>=1.34,<2",
#   "langgraph>=0.6,<2",
#   "opentelemetry-api>=1.24.0",
#   "python-dotenv>=1.0,<2",
# ]
# ///
# ─── 목적 ───
# 같은 케이스의 cleaned_raw_query(raw)와 soft_preference_query(soft)로 각각
# 테마별 top-K 벡터 검색을 돌려, raw∩soft / raw-only / soft-only 를 센다.
# 현재 파이프라인은 후보 풀을 raw로만 잡고 soft-only를 버리므로, soft-only가
# 얼마나 큰지 = 그 설계가 버리는 분위기-매칭 장소의 규모를 직접 본다.
# ─── 실행 ───
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/retrieval_overlap_probe.py --case 1 --profile skn26_final
# (또는 직접 지정) ... --raw "..." --soft "..." --themes "바다·해안,자연·트레킹"

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (ROOT, SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env.local", override=False)

from lovv_agent.adapters.aws_runtime import build_aws_runtime_adapters, require_embedding_adapter
from lovv_agent.adapters.boto3_clients import create_boto3_client_factory
from lovv_agent.config import RuntimeConfig

RESULTS_DIR = ROOT / "docs" / "tasks" / "results" / "test_cases" / "results"


def _latest_dump(nn: str) -> Path:
    matches = sorted(RESULTS_DIR.glob(f"e2e_state_dump_{nn}_*.json"))
    if not matches:
        raise SystemExit(f"[ERR] {nn} 덤프를 {RESULTS_DIR} 에서 못 찾음 (먼저 capture 실행)")
    return matches[-1]  # 파일명 타임스탬프 정렬 → 최신


def _from_dump(nn: str) -> tuple[str, str, list[str]]:
    dump = _latest_dump(nn)
    state = json.loads(dump.read_text(encoding="utf-8"))
    intent = state.get("intent", {})
    raw = (intent.get("cleaned_raw_query") or "").strip()
    soft = (intent.get("soft_preference_query") or "").strip()
    themes = list(intent.get("searchable_place_themes") or [])
    print(f"[dump] {dump.name}")
    return raw, soft, themes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default=None, help="테스트 케이스 번호 (덤프에서 raw/soft/themes 읽음)")
    parser.add_argument("--raw", default=None, help="raw 쿼리 직접 지정")
    parser.add_argument("--soft", default=None, help="soft 쿼리 직접 지정")
    parser.add_argument("--themes", default=None, help="테마 쉼표구분 (직접 지정 시)")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--show", type=int, default=15, help="soft-only 샘플 출력 개수")
    args = parser.parse_args()

    if args.profile:
        os.environ["LOVV_AWS_PROFILE"] = args.profile

    if args.case is not None:
        raw, soft, themes = _from_dump(args.case.strip().zfill(2))
    else:
        raw = (args.raw or "").strip()
        soft = (args.soft or "").strip()
        themes = [t.strip() for t in (args.themes or "").split(",") if t.strip()]

    if not raw or not soft:
        raise SystemExit("[ERR] raw/soft 쿼리가 둘 다 있어야 비교 가능 (soft 비어있으면 분리 검색 무의미)")
    if not themes:
        raise SystemExit("[ERR] themes 가 비어 있음")
    if raw == soft:
        print("[경고] raw == soft (deterministic intent?) → 겹침 100% 예상, 비교 의미 약함")

    config = RuntimeConfig.from_env()
    factory = create_boto3_client_factory(profile_name=config.aws.profile_name)
    adapters = build_aws_runtime_adapters(client_factory=factory, config=config)
    embedding = require_embedding_adapter(adapters)
    search = adapters.tools.destination_search

    raw_vec = embedding.embed_query(raw)
    soft_vec = embedding.embed_query(soft)

    print(f"\n=== retrieval overlap (top-{args.top_k}) ===")
    print(f"raw  = {raw!r}")
    print(f"soft = {soft!r}\n")

    tot_raw_only = tot_soft_only = tot_both = 0
    for theme in themes:
        raw_hits = search.search_candidates(raw_vec, theme=theme, top_k=args.top_k)
        soft_hits = search.search_candidates(soft_vec, theme=theme, top_k=args.top_k)
        raw_ids = {c.place_id for c in raw_hits}
        soft_ids = {c.place_id for c in soft_hits}
        title = {c.place_id: (c.title or c.place_id) for c in list(raw_hits) + list(soft_hits)}
        both = raw_ids & soft_ids
        raw_only = raw_ids - soft_ids
        soft_only = soft_ids - raw_ids
        union = raw_ids | soft_ids
        overlap = (len(both) / len(union) * 100) if union else 0.0
        tot_both += len(both)
        tot_raw_only += len(raw_only)
        tot_soft_only += len(soft_only)
        print(f"[theme: {theme}]  raw={len(raw_ids)} soft={len(soft_ids)} "
              f"| both={len(both)} raw_only={len(raw_only)} soft_only={len(soft_only)} "
              f"| Jaccard overlap={overlap:.0f}%")
        if soft_only:
            sample = [title[pid] for pid in list(soft_only)[: args.show]]
            print(f"   soft_only (현재 후보에서 누락되는 분위기-매칭 장소): {', '.join(sample)}"
                  + (" …" if len(soft_only) > args.show else ""))
        print()

    tot_union = tot_both + tot_raw_only + tot_soft_only
    print("=== 합계 ===")
    print(f"both={tot_both}  raw_only={tot_raw_only}  soft_only={tot_soft_only}  "
          f"| soft_only 비중 = {(tot_soft_only / tot_union * 100) if tot_union else 0:.0f}% of union")
    print("→ soft_only 가 클수록, 'soft는 raw 후보에 가산만' 하는 현재 설계가 버리는 분위기-매칭 장소가 많다는 뜻.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
