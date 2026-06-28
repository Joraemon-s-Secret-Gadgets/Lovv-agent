# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "boto3>=1.34,<2",
#   "langgraph>=0.6,<2",
#   "opentelemetry-api>=1.24.0",
#   "python-dotenv>=1.0,<2",
# ]
# ///
# ─── How to run ───
# uv run scripts/capture_e2e_state.py --mock
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/capture_e2e_state.py --live --input docs/tasks/results/agent_input_payloads/tc009_chat_nature_coast_quiet.json
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/capture_e2e_state.py --live --input-dir docs/tasks/results/agent_input_payloads

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# .env.local 주입 — main.py 엔트리포인트와 동일. capture는 main.py를 안 거치므로
# 여기서 직접 로드해야 --live의 build_live_harness()가 RuntimeConfig를 env에서 읽는다.
from dotenv import load_dotenv

load_dotenv(ROOT / ".env.local", override=False)

from lovv_agent.adapters.aws_runtime import build_aws_runtime_adapters
from lovv_agent.config import (
    AwsSettings,
    DynamoDbSettings,
    EmbeddingSettings,
    LlmSettings,
    RuntimeConfig,
    S3VectorSettings,
)
from lovv_agent.agentcore_entrypoint import (
    extract_recommendation_payload,
    extract_request_id,
)
from lovv_agent.harness import build_harness, build_live_harness
from tests.test_harness import RecordingAwsFactory

RESULTS_DIR = ROOT / "docs" / "tasks" / "results"
TEST_CASES_DIR = RESULTS_DIR / "test_cases"
KST = timezone(timedelta(hours=9))


def _resolve_case(case: str) -> Path:
    """테스트 케이스 번호(예: '1', '01', '14')를 test_cases/NN_*.json 으로 해석."""

    nn = case.strip().zfill(2)
    matches = sorted(TEST_CASES_DIR.glob(f"{nn}_*.json"))
    if not matches:
        raise SystemExit(f"[ERR] 테스트 케이스 {nn} 를 {TEST_CASES_DIR} 에서 못 찾음")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true")
    mode.add_argument("--live", action="store_true")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, help="단일 fixture JSON (raw 또는 wrapper)")
    source.add_argument("--input-dir", type=Path, help="fixture JSON 폴더 (일괄)")
    source.add_argument(
        "--case",
        default=None,
        help="테스트 케이스 번호만 (예: 1, 01, 14) → test_cases/NN_*.json 자동 매칭",
    )
    parser.add_argument("--request-id", default=None)
    parser.add_argument(
        "--profile",
        default=None,
        help="AWS 프로필명. 지정 시 LOVV_AWS_PROFILE로 주입돼 라이브 harness가 그 프로필로 AWS를 호출.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="state dump 저장 폴더. 미지정 시 입력 폴더 내 results/ (단건은 그 파일 폴더의 results/).",
    )
    args = parser.parse_args()

    if args.profile:
        os.environ["LOVV_AWS_PROFILE"] = args.profile
    harness = _live_harness() if args.live else _mock_harness()

    if args.input_dir is not None:
        paths: list[Path | None] = sorted(args.input_dir.glob("*.json"))
    elif args.case is not None:
        paths = [_resolve_case(args.case)]
    elif args.input is not None:
        paths = [args.input]
    else:
        paths = [None]  # 입력 미지정 시 하드코딩 기본 payload

    # 결과는 입력 폴더 내 results/ 에 저장한다(입력과 산출물을 함께 묶어 둠).
    if args.out_dir is not None:
        out_dir = args.out_dir
    elif args.input_dir is not None:
        out_dir = args.input_dir / "results"
    elif args.case is not None:
        out_dir = TEST_CASES_DIR / "results"
    elif args.input is not None:
        out_dir = args.input.parent / "results"
    else:
        out_dir = RESULTS_DIR

    for path in paths:
        label = path.stem if path is not None else "default"
        try:
            payload, req_id = _load_payload(path, args.request_id)
            state = harness.invoke_state(payload, request_id=req_id)
            out = _write_dump(state.to_dict(), label=label, out_dir=out_dir)
            print(f"[ok] {label} -> {out}")
        except Exception as exc:  # noqa: BLE001 - per-fixture 실패 기록 후 계속.
            print(f"[ERR] {label}: {exc}")
    return 0


def _load_payload(
    path: Path | None,
    request_id: str | None,
) -> tuple[dict[str, object], str | None]:
    """fixture를 raw/wrapper 모두 정규화해 (payload, request_id)로 반환."""

    if path is None:
        return _payload(), request_id or "REQ-E2E-DUMP-1"
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = extract_recommendation_payload(raw)  # raw + AgentCore/HTTP wrapper 정규화
    req_id = request_id or extract_request_id(raw) or path.stem
    return payload, req_id


def _mock_harness():
    config = RuntimeConfig(
        aws=AwsSettings(region="us-east-1"),
        s3_vectors=S3VectorSettings(
            bucket_name="lovv-vector-dev",
            index_name="kr-tour-domain-v1",
        ),
        dynamodb=DynamoDbSettings(table_name="TourKoreaDomainData"),
        embeddings=EmbeddingSettings(model_id="amazon.titan-embed-text-v2:0"),
        llm=LlmSettings(model_id="openai.gpt-oss-120b-1:0"),
    )
    adapters = build_aws_runtime_adapters(
        client_factory=RecordingAwsFactory(),
        config=config,
    )
    return build_harness(config=config, adapters=adapters)


def _live_harness():
    return build_live_harness()


def _payload() -> dict[str, object]:
    return {
        "entryType": "chat",
        "destinationId": None,
        "country": "KR",
        "travelYear": 2026,
        "travelMonth": 10,
        "tripType": "daytrip",
        "themes": ["sea_coast"],
        "includeFestivals": False,
        "naturalLanguageQuery": "조용하고 덜 붐비는 바다 산책을 하고 싶어요.",
        "userLocation": None,
    }


def _write_dump(
    state: dict[str, object],
    label: str = "default",
    out_dir: Path = RESULTS_DIR,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(KST).strftime("%Y%m%dT%H%M%S") + "KST"
    path = out_dir / f"e2e_state_dump_{label}_{timestamp}.json"
    path.write_text(
        json.dumps(state, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    raise SystemExit(main())
