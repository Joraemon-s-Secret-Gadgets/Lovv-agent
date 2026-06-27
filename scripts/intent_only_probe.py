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
# Intent LLM 단계만 실행해 6필드(특히 soft_preference_query)를 바로 확인한다.
# 프롬프트(soft 정의)를 고친 뒤 잘 나오는지 빠르게 반복 검증용. retrieval/planner 안 탐.
# ─── 실행 ───
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/intent_only_probe.py --case 1 --profile skn26_final
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/intent_only_probe.py --all --profile skn26_final
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/intent_only_probe.py --query "조용한 숲길 걷고 싶어요" --profile skn26_final

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

from lovv_agent.adapters.aws_runtime import build_aws_runtime_adapters, require_agent_converse_runtime
from lovv_agent.adapters.boto3_clients import create_boto3_client_factory
from lovv_agent.agentcore_entrypoint import extract_recommendation_payload
from lovv_agent.agents.intent import invoke_intent_structured_output
from lovv_agent.config import RuntimeConfig
from lovv_agent.prompts.registry import INTENT_NORMALIZATION_PROMPT_ID, prompt_text

TEST_CASES_DIR = ROOT / "docs" / "tasks" / "results" / "test_cases"


def _resolve_case(case: str) -> Path:
    nn = case.strip().zfill(2)
    matches = sorted(TEST_CASES_DIR.glob(f"{nn}_*.json"))
    if not matches:
        raise SystemExit(f"[ERR] 테스트 케이스 {nn} 를 {TEST_CASES_DIR} 에서 못 찾음")
    return matches[0]


def _payload_from_query(args) -> dict:
    return {
        "entryType": "chat",
        "destinationId": None,
        "country": "KR",
        "travelYear": 2026,
        "travelMonth": args.month,
        "tripType": args.trip,
        "themes": [t.strip() for t in args.themes.split(",") if t.strip()],
        "includeFestivals": args.festivals,
        "naturalLanguageQuery": args.query,
        "userLocation": None,
    }


def _run_one(label: str, api_payload: dict, *, runtime, retry_limit: int, min_chars: int) -> None:
    nl = (api_payload.get("naturalLanguageQuery") or "").strip()
    result = invoke_intent_structured_output(
        runtime=runtime,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": json.dumps(
                            {
                                "task": "API 입력을 Intent Agent 출력 계약으로 정규화하세요.",
                                "api_structured_input": api_payload,
                                "conversation_summary": "",
                                "messages": [],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            },
        ],
        structured_request=api_payload,
        retry_limit=retry_limit,
        system=[{"text": prompt_text(INTENT_NORMALIZATION_PROMPT_ID)}],
    )
    short = len(nl) < min_chars
    print(f"\n[{label}]" + ("  (짧은 쿼리 → 실제 파이프라인은 deterministic 경로)" if short else ""))
    print(f"  raw_NL : {nl!r}")
    print(f"  cleaned: {result.cleaned_raw_query!r}")
    print(f"  soft   : {result.soft_preference_query!r}")
    print(f"  clarify: {result.needs_clarification}"
          + (f"  q={result.clarifying_question!r}" if result.needs_clarification else ""))
    print(f"  unsup  : {list(result.unsupported_conditions)}")
    if result.handoff_notes:
        print(f"  notes  : {list(result.handoff_notes)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--case", default=None, help="테스트 케이스 번호 (예: 1, 14)")
    src.add_argument("--all", action="store_true", help="test_cases 전체 일괄")
    src.add_argument("--query", default=None, help="자연어 쿼리 직접 입력")
    parser.add_argument("--themes", default="sea_coast", help="--query용 themes (쉼표구분)")
    parser.add_argument("--trip", default="2d1n", help="--query용 tripType")
    parser.add_argument("--month", type=int, default=7, help="--query용 travelMonth")
    parser.add_argument("--festivals", action="store_true", help="--query용 includeFestivals")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args()

    if args.profile:
        os.environ["LOVV_AWS_PROFILE"] = args.profile

    config = RuntimeConfig.from_env()
    factory = create_boto3_client_factory(profile_name=config.aws.profile_name)
    adapters = build_aws_runtime_adapters(client_factory=factory, config=config)
    runtime = require_agent_converse_runtime(adapters, "intent")
    retry_limit = config.retries.schema_retry_limit
    min_chars = config.intent.min_natural_language_query_chars

    if args.all:
        paths = sorted(TEST_CASES_DIR.glob("*.json"))
        for path in paths:
            try:
                payload = extract_recommendation_payload(json.loads(path.read_text(encoding="utf-8")))
                _run_one(path.stem, payload, runtime=runtime, retry_limit=retry_limit, min_chars=min_chars)
            except Exception as exc:  # noqa: BLE001 - per-fixture 실패 기록 후 계속
                print(f"\n[{path.stem}]  [ERR] {exc}")
    elif args.case is not None:
        path = _resolve_case(args.case)
        payload = extract_recommendation_payload(json.loads(path.read_text(encoding="utf-8")))
        _run_one(path.stem, payload, runtime=runtime, retry_limit=retry_limit, min_chars=min_chars)
    else:
        _run_one("query", _payload_from_query(args), runtime=runtime, retry_limit=retry_limit, min_chars=min_chars)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
