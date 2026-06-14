"""Invoke the full AWS-backed Lovv LangGraph from an API request JSON.

Examples:
    uv run python scripts/invoke_live_recommendation.py --input request.json
    Get-Content request.json | uv run python scripts/invoke_live_recommendation.py

Required non-secret runtime settings are read through ``RuntimeConfig``. AWS
credentials continue to use the normal boto3 credential chain.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lovv_agent.harness import build_live_harness


def parse_args() -> argparse.Namespace:
    """Parse the optional JSON input path."""

    parser = argparse.ArgumentParser(
        description="Invoke the live AWS-backed Lovv LangGraph.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="UTF-8 JSON file containing the POST /recommendations payload.",
    )
    parser.add_argument(
        "--request-id",
        help="Optional recommendation request id for repeatable smoke tests.",
    )
    return parser.parse_args()


def load_payload(path: Path | None) -> dict[str, Any]:
    """Load one request object from a file or standard input."""

    text = path.read_text(encoding="utf-8") if path is not None else sys.stdin.read()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("recommendations input must be one JSON object")
    return payload


def main() -> int:
    """Build the live harness, invoke the graph, and print public JSON."""

    args = parse_args()
    payload = load_payload(args.input)
    harness = build_live_harness()
    response = harness.invoke(payload, request_id=args.request_id)
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
