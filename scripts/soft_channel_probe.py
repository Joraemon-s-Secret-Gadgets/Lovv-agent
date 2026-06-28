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
# soft 채널(soft_query_vector)의 한계효용 검증. 같은 candidate_input으로
# candidate_agent.run을 soft 켜고(raw+soft) / 끄고(raw only) 두 번 돌려
# 도시 선택·city 순위·선택도시 장소 순서가 얼마나 달라지는지 측정한다.
# raw 쿼리에 이미 분위기어가 있는데 별도 soft 넛지가 값을 하는가?
# ─── 실행 ───
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/soft_channel_probe.py --case 1 --profile skn26_final

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

from lovv_agent.adapters.aws_runtime import (
    build_aws_runtime_adapters,
    require_agent_converse_runtime,
    require_embedding_adapter,
)
from lovv_agent.adapters.boto3_clients import create_boto3_client_factory
from lovv_agent.agents.candidate_evidence import CandidateEvidenceAgent
from lovv_agent.config import RuntimeConfig

RESULTS_DIR = ROOT / "docs" / "tasks" / "results" / "test_cases" / "results"


def _latest_dump(nn: str) -> Path:
    matches = sorted(RESULTS_DIR.glob(f"e2e_state_dump_{nn}_*.json"))
    if not matches:
        raise SystemExit(f"[ERR] {nn} 덤프를 {RESULTS_DIR} 에서 못 찾음")
    return matches[-1]


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _selected_id(rankings: list) -> str | None:
    for r in rankings:
        if _get(r, "selected"):
            return str(_get(r, "city_id"))
    return str(_get(rankings[0], "city_id")) if rankings else None


def _place_order(package) -> list[tuple[str, str]]:
    out = []
    for pl in _get(package, "recommended_places", []) or []:
        out.append((str(_get(pl, "place_id")), str(_get(pl, "title"))))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, help="테스트 케이스 번호 (덤프에서 candidate_input 읽음)")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args()

    if args.profile:
        os.environ["LOVV_AWS_PROFILE"] = args.profile

    dump = _latest_dump(args.case.strip().zfill(2))
    state = json.loads(dump.read_text(encoding="utf-8"))
    ci = state["intent"]["candidate_evidence_input"]  # dict — agent.run이 Mapping 허용
    raw = (ci.get("cleaned_raw_query") or "").strip()
    soft = (ci.get("soft_preference_query") or "").strip()
    print(f"[dump] {dump.name}")
    print(f"raw  = {raw!r}\nsoft = {soft!r}")
    if not soft or soft == raw:
        print("[경고] soft 가 비었거나 raw와 동일 → soft 채널 효과 측정 무의미")

    config = RuntimeConfig.from_env()
    factory = create_boto3_client_factory(profile_name=config.aws.profile_name)
    adapters = build_aws_runtime_adapters(client_factory=factory, config=config)
    embedding = require_embedding_adapter(adapters)
    ce_runtime = require_agent_converse_runtime(adapters, "candidate_evidence")
    agent = CandidateEvidenceAgent(
        destination_search=adapters.tools.destination_search,
        dynamo_lookup=adapters.tools.dynamo_lookup,
        reason_claim_runtime=ce_runtime,
        schema_retry_limit=config.retries.schema_retry_limit,
    )

    query_vec = embedding.embed_query(raw or soft)
    soft_vec = embedding.embed_query(soft) if soft and soft != raw else None

    pkg_on = agent.run(ci, query_vector=query_vec, soft_query_vector=soft_vec)
    pkg_off = agent.run(ci, query_vector=query_vec, soft_query_vector=None)

    rank_on = list(_get(pkg_on, "city_rankings", []) or [])
    rank_off = list(_get(pkg_off, "city_rankings", []) or [])
    sel_on, sel_off = _selected_id(rank_on), _selected_id(rank_off)

    score_on = {str(_get(r, "city_id")): float(_get(r, "city_score", 0.0)) for r in rank_on}
    score_off = {str(_get(r, "city_id")): float(_get(r, "city_score", 0.0)) for r in rank_off}
    order_on = [str(_get(r, "city_id")) for r in rank_on]
    order_off = [str(_get(r, "city_id")) for r in rank_off]

    print("\n=== [도시 선택] ===")
    print(f"  soft ON : {sel_on}  (score {score_on.get(sel_on, 0):.3f})")
    print(f"  soft OFF: {sel_off}  (score {score_off.get(sel_off, 0):.3f})")
    print(f"  → 선택 변동: {'YES' if sel_on != sel_off else 'NO'}")

    print("\n=== [city ranking top-5] (ON | OFF) ===")
    for i in range(min(5, max(len(order_on), len(order_off)))):
        a = order_on[i] if i < len(order_on) else "—"
        b = order_off[i] if i < len(order_off) else "—"
        sa = f"{score_on.get(a, 0):.3f}" if a != "—" else ""
        sb = f"{score_off.get(b, 0):.3f}" if b != "—" else ""
        mark = "" if a == b else "  <-- 변동"
        print(f"  {i + 1}. ON {a:<12}{sa:>8}   OFF {b:<12}{sb:>8}{mark}")

    common = [c for c in order_on if c in order_off]
    reorder = sum(1 for c in common if order_on.index(c) != order_off.index(c))
    print(f"\n  공통 도시 {len(common)}개 중 순위 변동: {reorder}개")

    print("\n=== [선택 도시 장소 순서] ===")
    if sel_on != sel_off:
        print("  선택 도시가 달라 장소 순서 직접비교 생략 (위 '선택 변동'이 헤드라인).")
    else:
        po, pf = _place_order(pkg_on), _place_order(pkg_off)
        ids_o = [pid for pid, _t in po]
        ids_f = [pid for pid, _t in pf]
        moved = sum(1 for k, pid in enumerate(ids_o) if k >= len(ids_f) or ids_f[k] != pid)
        print("  ON : " + " > ".join(t for _p, t in po[:6]))
        print("  OFF: " + " > ".join(t for _p, t in pf[:6]))
        print(f"  → 장소 순서 변동(위치 불일치): {moved}/{len(ids_o)}")

    print("\n=== [요약] ===")
    verdict = (
        "유의미 (soft 넛지가 결과를 바꿈)"
        if sel_on != sel_off or reorder > 0
        else "미미 (soft 넛지가 순위를 거의 안 바꿈 → raw 분위기어와 중복 가능성)"
    )
    print(f"  soft 채널 효과: 도시선택 {'변동' if sel_on != sel_off else '동일'}, "
          f"city순위 {reorder}개 변동  →  {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
