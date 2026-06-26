"""Invoke the DEPLOYED LovvAgentV1 AgentCore Runtime (Tier 2 / Observability).

Unlike ``invoke_live_recommendation.py`` and ``capture_e2e_state.py`` — which run
the LangGraph in-process — this script calls the deployed AgentCore Runtime via
``bedrock-agentcore:InvokeAgentRuntime``. Only this path emits OTel spans through
the runtime's ADOT collector to X-Ray / CloudWatch, so it is required for the
Observability (NF-*, OB-*) sections of the test result report.

Each invocation returns a ``traceId`` which is printed and (in --input-dir mode)
saved, so the report can look the trace up in X-Ray ServiceLens (OB-04).

Examples:
    uv run python scripts/invoke_deployed_runtime.py \
        --input docs/tasks/results/agent_input_payloads/tc009_chat_nature_coast_quiet.json

    uv run python scripts/invoke_deployed_runtime.py \
        --input-dir docs/tasks/results/agent_input_payloads

Requirements:
    - AWS credentials with ``bedrock-agentcore:InvokeAgentRuntime``
    - boto3/botocore recent enough to expose the ``bedrock-agentcore`` client
    - The runtime code must actually emit node spans/metrics for OB-01 to pass
      (instrumentation = SPEC Phase A; otherwise only auto-instrumented spans appear).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import boto3

DEFAULT_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:925273580929:runtime/"
    "LovvAgentCore_LovvAgentV1-PumZyEGRsT"
)
DEFAULT_REGION = "us-east-1"
DEFAULT_QUALIFIER = "DEFAULT"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Invoke the deployed LovvAgentV1 runtime.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=Path, help="One fixture JSON file.")
    src.add_argument("--input-dir", type=Path, help="Directory of fixture JSON files.")
    parser.add_argument("--arn", default=DEFAULT_ARN, help="AgentCore Runtime ARN.")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--qualifier", default=DEFAULT_QUALIFIER, help="Runtime endpoint qualifier.")
    parser.add_argument(
        "--session-id",
        default=None,
        help="runtimeSessionId(33+자). **미지정(기본)=호출마다 새 세션→새 MicroVM(격리·콜드, 기능 테스트용)**. "
        "고정값 지정 시 모든 호출이 그 세션 공유→워밍 MicroVM 재사용(latency 측정용).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path to write {fixture, traceId, statusCode} summary (dir mode).",
    )
    return parser.parse_args()


def _session_id() -> str:
    # AgentCore requires runtimeSessionId length >= 33; uuid4 hex with a prefix is safe.
    return f"lovv-test-{uuid.uuid4().hex}"


def _read_response_body(response: Any) -> Any:
    """Read a buffered StreamingBody or a streamed EventStream into text/JSON."""

    body = response.get("response")
    if body is None:
        return None
    if hasattr(body, "read"):  # botocore StreamingBody (buffered)
        raw = body.read()
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    else:  # EventStream (chunked) — concatenate chunk payloads
        chunks: list[str] = []
        for event in body:
            if isinstance(event, (bytes, bytearray)):
                chunks.append(event.decode("utf-8"))
            elif isinstance(event, dict):
                part = event.get("chunk", {}).get("bytes") or event.get("bytes")
                if isinstance(part, (bytes, bytearray)):
                    chunks.append(part.decode("utf-8"))
        text = "".join(chunks)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def invoke_one(
    client: Any,
    *,
    arn: str,
    qualifier: str,
    payload: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    response = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        qualifier=qualifier,
        runtimeSessionId=session_id,
        contentType="application/json",
        payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    return {
        "statusCode": response.get("statusCode"),
        "traceId": response.get("traceId"),
        "contentType": response.get("contentType"),
        "body": _read_response_body(response),
    }


def main() -> int:
    args = parse_args()
    client = boto3.client("bedrock-agentcore", region_name=args.region)
    # --session-id 지정 → 모든 호출이 그 세션 공유(워밍 MicroVM 재사용, latency 측정용).
    # 미지정(기본) → 호출마다 새 세션 = 새 MicroVM(격리·콜드, 기능 테스트엔 이게 안전).
    def _sid() -> str:
        return args.session_id or _session_id()

    if args.input is not None:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = invoke_one(client, arn=args.arn, qualifier=args.qualifier, payload=payload, session_id=_sid())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    files = sorted(p for p in args.input_dir.glob("*.json"))
    summary: list[dict[str, Any]] = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            result = invoke_one(client, arn=args.arn, qualifier=args.qualifier, payload=payload, session_id=_sid())
            summary.append(
                {
                    "fixture": path.name,
                    "statusCode": result["statusCode"],
                    "traceId": result["traceId"],
                },
            )
            print(f"[ok] {path.name}  status={result['statusCode']}  traceId={result['traceId']}")
        except Exception as exc:  # noqa: BLE001 - record per-fixture failure, continue batch.
            summary.append({"fixture": path.name, "error": str(exc)})
            print(f"[ERR] {path.name}  {exc}")

    out = args.out or (args.input_dir.parent / "deployed_invoke_trace_summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsummary -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
