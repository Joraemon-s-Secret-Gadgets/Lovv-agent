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
# congestion 점수화 방식(rank vs log)을 "동일 retrieval(base) 고정"한 채
# 선호(조용/중립/혼잡) w_cong만 바꿔 도시 순위가 어떻게 갈리는지 비교한다.
# candidate-only: intent(결정적) → candidate_agent.run → city base, 그리고
# 동일 query로 retrieval해 도시별 ddb_pk를 얻어 visitor_total을 직접 조회한다.
# ─── 실행 ───
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/congestion_probe.py --case 1 --profile skn26_final

from __future__ import annotations

import argparse
import json
import math
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
from lovv_agent.agentcore_entrypoint import extract_recommendation_payload
from lovv_agent.agents.candidate_evidence import CandidateEvidenceAgent, resolve_w_cong
from lovv_agent.agents.intent import normalize_recommendation_request
from lovv_agent.config import RuntimeConfig

TEST_CASES_DIR = ROOT / "docs" / "tasks" / "results" / "test_cases"

# 선호 → w_cong (resolve_w_cong와 동일 값)
PREFERENCES = {"조용(+0.35)": 0.35, "중립(+0.10)": 0.10, "혼잡(-0.25)": -0.25}


def _resolve_case(case: str) -> Path:
    nn = case.strip().zfill(2)
    matches = sorted(TEST_CASES_DIR.glob(f"{nn}_*.json"))
    if not matches:
        raise SystemExit(f"[ERR] 테스트 케이스 {nn} 를 {TEST_CASES_DIR} 에서 못 찾음")
    return matches[0]


def _embedding_query(ci) -> str:
    for value in (ci.cleaned_raw_query, ci.soft_preference_query, " ".join(ci.active_required_themes)):
        if value.strip():
            return value.strip()
    raise SystemExit("[ERR] embedding query 가 비어 있음")


# ─── congestion_index 방식들 (전부 0=한적 ~ 1=혼잡, 결측=0.5) ───
def idx_rank(vals: dict[str, float | None]) -> dict[str, float]:
    """현행: 방문객 서열 정규화 rank/(n-1)."""
    idx = {c: 0.5 for c, v in vals.items() if v is None}
    known = [(c, v) for c, v in vals.items() if v is not None]
    if not known:
        return {c: 0.5 for c in vals}
    if len(known) == 1:
        idx[known[0][0]] = 0.5
        return idx
    ordered = sorted(known, key=lambda x: x[1])
    last = len(ordered) - 1
    for r, (c, _v) in enumerate(ordered):
        idx[c] = r / last
    return idx


def idx_log_minmax(vals: dict[str, float | None]) -> dict[str, float]:
    """L1: ln(v) min-max 정규화."""
    idx = {c: 0.5 for c, v in vals.items() if not (v is not None and v > 0)}
    known = [(c, v) for c, v in vals.items() if v is not None and v > 0]
    if len(known) < 2:
        for c, _v in known:
            idx[c] = 0.5
        return idx
    logs = {c: math.log(v) for c, v in known}
    lo, hi = min(logs.values()), max(logs.values())
    span = hi - lo
    for c, lv in logs.items():
        idx[c] = 0.5 if span == 0 else (lv - lo) / span
    return idx


def idx_log_fixed(vals: dict[str, float | None], cap: float) -> dict[str, float]:
    """L2: ln(v)/ln(cap) 절대 정규화 (풀 무관)."""
    lcap = math.log(cap)
    idx: dict[str, float] = {}
    for c, v in vals.items():
        idx[c] = 0.5 if (v is None or v <= 0) else min(max(math.log(v) / lcap, 0.0), 1.0)
    return idx


def main() -> int:
    parser = argparse.ArgumentParser()
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--case", default=None, help="테스트 케이스 번호 (예: 1, 01, 14)")
    src.add_argument("--input", type=Path, default=None, help="단일 fixture JSON")
    parser.add_argument("--profile", default=None, help="AWS 프로필명")
    parser.add_argument("--cap", type=float, default=3_000_000.0, help="L2 고정기준 상한 (기본 300만)")
    args = parser.parse_args()

    if args.profile:
        os.environ["LOVV_AWS_PROFILE"] = args.profile

    path = _resolve_case(args.case) if args.case is not None else args.input
    raw = json.loads(path.read_text(encoding="utf-8"))
    api_payload = extract_recommendation_payload(raw)

    # intent (결정적) — candidate_evidence_input 확보
    intent = normalize_recommendation_request(api_payload)
    if intent.needs_clarification or intent.candidate_evidence_input is None:
        raise SystemExit(f"[ERR] {path.name}: intent가 clarification/None (candidate 불가)")
    ci = intent.candidate_evidence_input

    # 어댑터/에이전트 구성 (build_harness candidate 부분만)
    config = RuntimeConfig.from_env()
    factory = create_boto3_client_factory(profile_name=config.aws.profile_name)
    adapters = build_aws_runtime_adapters(client_factory=factory, config=config)
    embedding = require_embedding_adapter(adapters)
    ce_runtime = require_agent_converse_runtime(adapters, "candidate_evidence")
    candidate_agent = CandidateEvidenceAgent(
        destination_search=adapters.tools.destination_search,
        dynamo_lookup=adapters.tools.dynamo_lookup,
        reason_claim_runtime=ce_runtime,
        schema_retry_limit=config.retries.schema_retry_limit,
    )
    destination_search = adapters.tools.destination_search
    dynamo_lookup = adapters.tools.dynamo_lookup

    # query embedding (harness candidate_node와 동일)
    query_text = _embedding_query(ci)
    query_vector = embedding.embed_query(query_text)
    soft_text = ci.soft_preference_query.strip()
    soft_query_vector = (
        embedding.embed_query(soft_text) if soft_text and soft_text != query_text else None
    )

    package = candidate_agent.run(ci, query_vector=query_vector, soft_query_vector=soft_query_vector)
    rankings = list(package.city_rankings)
    if not rankings:
        raise SystemExit(f"[ERR] {path.name}: city_rankings 비어 있음 (status={package.status})")

    # base = city_score + congestion_penalty (congestion 제외 점수)
    base_by_city: dict[str, float] = {}
    pkg_cong_by_city: dict[str, float] = {}
    for r in rankings:
        cid = str(r["city_id"])
        cong = float(r["score_breakdown"]["congestion_penalty"])
        base_by_city[cid] = float(r["city_score"]) + cong
        pkg_cong_by_city[cid] = cong

    # retrieval 재실행으로 도시별 ddb_pk / 이름 확보 (visitor 조회용)
    pk_by_city: dict[str, str] = {}
    name_by_city: dict[str, str] = {}
    for theme in ci.active_required_themes:
        for cand in destination_search.search_candidates(query_vector, theme=theme):
            if cand.city_id and cand.city_id not in pk_by_city and cand.ddb_pk:
                pk_by_city[cand.city_id] = cand.ddb_pk
                name_by_city[cand.city_id] = cand.city_name_ko or cand.city_id

    ranking_ids = list(base_by_city.keys())
    pk_subset = {cid: pk_by_city[cid] for cid in ranking_ids if cid in pk_by_city}
    visitors = dynamo_lookup.city_visitor_stats(
        ranking_ids,
        ci.travel_month,
        partition_key_by_city=pk_subset,
    )

    # 방식별 index
    methods = {
        "rank": idx_rank(visitors),
        "logMM": idx_log_minmax(visitors),
        "logFix": idx_log_fixed(visitors, args.cap),
    }

    print(f"\n=== {path.name} | month={ci.travel_month} | base 고정, congestion 방식/선호만 변경 ===")
    print(f"themes={list(ci.active_required_themes)}  soft='{soft_text}'\n")

    # 도시별 표
    header = f"{'city_id':<12} {'name':<8} {'visitors':>13} {'rank':>6} {'logMM':>6} {'logFix':>7} {'base':>7}"
    print(header)
    print("-" * len(header))
    for cid in sorted(ranking_ids, key=lambda c: methods["rank"][c]):
        v = visitors.get(cid)
        vs = f"{v:,.0f}" if v is not None else "—(0.5)"
        print(
            f"{cid:<12} {name_by_city.get(cid, '?'):<8} {vs:>13} "
            f"{methods['rank'][cid]:>6.2f} {methods['logMM'][cid]:>6.2f} "
            f"{methods['logFix'][cid]:>7.2f} {base_by_city[cid]:>7.3f}"
        )

    # 검증: rank × (그 fixture의 w_cong) == 패키지 congestion?
    trigger = soft_text if soft_text else ci.cleaned_raw_query
    w_used = resolve_w_cong(trigger)
    mism = [
        cid
        for cid in ranking_ids
        if abs(methods["rank"][cid] * w_used - pkg_cong_by_city[cid]) > 1e-4
    ]
    print(
        f"\n[검증] rank × w_used({w_used:+.2f}) == 패키지 congestion : "
        + ("OK (probe retrieval/visitor가 agent와 일치)" if not mism else f"MISMATCH {mism}")
    )

    # 선호 × 방식 → #1 / top3
    def ranked(method_idx: dict[str, float], w: float) -> list[tuple[str, float]]:
        finals = {c: base_by_city[c] - method_idx[c] * w for c in ranking_ids}
        return sorted(finals.items(), key=lambda x: x[1], reverse=True)

    print("\n=== 선호별 1위 (방식 비교) ===")
    print(f"{'method':<8} " + "  ".join(f"{p:<16}" for p in PREFERENCES))
    for m, midx in methods.items():
        cells = []
        for _p, w in PREFERENCES.items():
            top = ranked(midx, w)[0][0]
            cells.append(f"{name_by_city.get(top, top):<16}")
        print(f"{m:<8} " + "  ".join(cells))

    print("\n=== 선호별 top3 (방식별 상세) ===")
    for m, midx in methods.items():
        print(f"\n[{m}]")
        for p, w in PREFERENCES.items():
            top3 = ranked(midx, w)[:3]
            chain = " > ".join(f"{name_by_city.get(c, c)}({s:.3f})" for c, s in top3)
            print(f"  {p:<16} {chain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
