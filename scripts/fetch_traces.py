# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "boto3>=1.40,<2",
#   "botocore[crt]>=1.40",
# ]
# ///
# ─── How to run (uv) ───
#   단일 trace:
#     uv run scripts/fetch_traces.py --trace-id 6a3c84ef2aae2c3a2dd47bd45d223baa --profile skn26_final
#   invoke 요약 일괄 (invoke_deployed_runtime.py --input-dir 산출물):
#     uv run scripts/fetch_traces.py --summary docs/tasks/results/deployed_invoke_trace_summary.json \
#         --out docs/tasks/results/traces_fetched.json --profile skn26_final
#   최근 N분 트레이스 목록(연결/권한 빠른 확인용):
#     uv run scripts/fetch_traces.py --since-min 30 --profile skn26_final
#   CloudWatch AGENT_NODE_METRIC 로그도 같이 끌기:
#     uv run scripts/fetch_traces.py --trace-id <id> --logs --profile skn26_final
"""배포 LovvAgentV1 런타임의 트레이스를 X-Ray(+선택적 CloudWatch Logs)에서 자동 수집.

수동 콘솔 캡처 없이 결과서 NF-*/OB-* 입력을 구조화 JSON으로 떨군다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3


def to_xray_id(tid: str) -> str:
    """OTel 32-hex trace id → X-Ray '1-{8}-{24}'. 이미 X-Ray 포맷이면 그대로."""

    raw = tid.replace("-", "")
    if tid.startswith("1-") and tid.count("-") == 2:
        return tid
    if len(raw) == 32 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return f"1-{raw[:8]}-{raw[8:]}"
    return tid  # 알 수 없는 형태는 그대로 시도


def _client(service: str, region: str, profile: str | None):
    # region을 Session에도 준다 — SSO/login 자격증명 provider가 토큰 교환 시 region을 요구한다.
    kwargs = {"region_name": region}
    if profile:
        kwargs["profile_name"] = profile
    session = boto3.Session(**kwargs)
    return session.client(service, region_name=region)


def _is_health_ping(doc: dict[str, Any]) -> bool:
    """헬스체크(/ping, InternalOperation) 세그먼트 여부 — latency 집계에서 제외용."""

    name = str(doc.get("name", ""))
    url = str(doc.get("http", {}).get("request", {}).get("url", ""))
    return name == "InternalOperation" or url.rstrip("/").endswith("/ping")


def _dur(node: dict[str, Any]) -> float | None:
    s, e = node.get("start_time"), node.get("end_time")
    return round(e - s, 4) if isinstance(s, (int, float)) and isinstance(e, (int, float)) else None


def _walk_subsegments(subs: Any) -> list[dict[str, Any]]:
    """중첩 subsegment를 재귀로 펼치고 aws/http 상세를 함께 뽑는다."""

    out: list[dict[str, Any]] = []
    for sub in subs or []:
        aws = sub.get("aws", {}) or {}
        http = sub.get("http", {}) or {}
        entry = {
            "name": sub.get("name"),
            "namespace": sub.get("namespace"),
            "duration": _dur(sub),
            "op": aws.get("operation"),
            "request_id": aws.get("request_id"),
            "table_name": aws.get("table_name"),
            "status": (http.get("response", {}) or {}).get("status"),
            "error": sub.get("error"),
            "fault": sub.get("fault"),
            "throttle": sub.get("throttle"),
            "subsegments": _walk_subsegments(sub.get("subsegments")),
        }
        # None / 빈 리스트 / False 플래그는 떨궈서 노이즈를 줄인다 (0.0·status 200은 보존).
        out.append({k: v for k, v in entry.items() if v is not None and v != [] and v is not False})
    return out


def _summarize_segment(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": doc.get("name"),
        "origin": doc.get("origin"),
        "duration": _dur(doc),
        "health_ping": _is_health_ping(doc),
        "subsegments": _walk_subsegments(doc.get("subsegments")),
    }


def fetch_traces(xray, trace_ids: list[str], *, include_raw: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    norm = [to_xray_id(t) for t in trace_ids]
    for i in range(0, len(norm), 5):  # batch_get_traces: 최대 5개
        resp = xray.batch_get_traces(TraceIds=norm[i : i + 5])
        for t in resp.get("Traces", []):
            docs = [json.loads(s["Document"]) for s in t.get("Segments", [])]
            segments = [_summarize_segment(d) for d in docs]
            entry = {
                "trace_id": t["Id"],
                "duration": t.get("Duration"),
                "segments_excluding_ping": [s for s in segments if not s["health_ping"]],
                "ping_segment_count": sum(1 for s in segments if s["health_ping"]),
            }
            if include_raw:
                entry["raw_segments"] = docs  # 원본 Document 통째 (모든 필드 보존)
            out.append(entry)
        unprocessed = resp.get("UnprocessedTraceIds") or []
        if unprocessed:
            print(f"  [warn] unprocessed: {unprocessed}", file=sys.stderr)
    return out


def fetch_logs(logs, *, since_min: int, log_group: str | None) -> dict[str, Any]:
    """AGENT_NODE_METRIC 로그 best-effort 조회 (OB-01/NF-06 샘플)."""

    groups = []
    if log_group:
        groups = [log_group]
    else:
        paginator = logs.get_paginator("describe_log_groups")
        for page in paginator.paginate(logGroupNamePrefix="/aws/bedrock-agentcore"):
            groups += [g["logGroupName"] for g in page.get("logGroups", [])]
    if not groups:
        return {"error": "no /aws/bedrock-agentcore log groups found", "groups": []}

    end = int(datetime.now(timezone.utc).timestamp())
    start = end - since_min * 60
    qid = logs.start_query(
        logGroupNames=groups[:20],
        startTime=start,
        endTime=end,
        queryString='fields @timestamp, @message | filter @message like /AGENT_NODE_METRIC/ | sort @timestamp desc | limit 5',
    )["queryId"]
    import time

    for _ in range(30):
        res = logs.get_query_results(queryId=qid)
        if res["status"] in {"Complete", "Failed", "Cancelled"}:
            return {"groups": groups, "status": res["status"], "results": res.get("results", [])}
        time.sleep(1)
    return {"groups": groups, "status": "Timeout", "results": []}


def main() -> int:
    p = argparse.ArgumentParser(description="X-Ray/CloudWatch 트레이스 자동 수집")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--trace-id", help="단일 trace id (OTel 또는 X-Ray 포맷)")
    src.add_argument("--summary", type=Path, help="deployed_invoke_trace_summary.json 경로")
    src.add_argument("--since-min", type=int, help="최근 N분 트레이스 요약 목록")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--profile", default=None, help="AWS 프로필 (예: skn26_final)")
    p.add_argument("--out", type=Path, default=None, help="결과 JSON 저장 경로")
    p.add_argument("--logs", action="store_true", help="AGENT_NODE_METRIC 로그도 조회")
    p.add_argument("--log-group", default=None, help="로그그룹 직접 지정")
    p.add_argument("--raw", action="store_true", help="원본 segment Document 통째 포함")
    args = p.parse_args()

    xray = _client("xray", args.region, args.profile)

    if args.since_min is not None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=args.since_min)
        s = xray.get_trace_summaries(StartTime=start, EndTime=end)
        rows = [
            {"id": ts["Id"], "duration": ts.get("Duration"), "responseTime": ts.get("ResponseTime"),
             "hasError": ts.get("HasError"), "http": ts.get("Http", {}).get("HttpURL")}
            for ts in s.get("TraceSummaries", [])
        ]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if args.trace_id:
        ids = [args.trace_id]
    else:
        data = json.loads(args.summary.read_text(encoding="utf-8"))
        ids = [r["traceId"] for r in data if r.get("traceId")]

    result: dict[str, Any] = {"traces": fetch_traces(xray, ids, include_raw=args.raw)}
    if not result["traces"]:
        print("[info] batch_get_traces 빈 결과. ID 포맷/Transaction Search 여부 확인 또는 --since-min 사용.", file=sys.stderr)

    if args.logs:
        logs = _client("logs", args.region, args.profile)
        result["agent_node_metric_logs"] = fetch_logs(logs, since_min=60, log_group=args.log_group)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"saved -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
