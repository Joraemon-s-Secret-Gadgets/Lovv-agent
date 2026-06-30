#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lovv_agent_v2.analysis.soft_channel import ValidationConfig, run_validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate soft_query channel from saved retrieval JSON only.")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--top-n", default=30, type=int)
    parser.add_argument("--judge-candidates-per-case", default=10, type=int)
    parser.add_argument("--city-top-k", default=5, type=int)
    args = parser.parse_args()
    run_validation(
        ValidationConfig(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            top_n=args.top_n,
            judge_candidates_per_case=args.judge_candidates_per_case,
            city_top_k=args.city_top_k,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
