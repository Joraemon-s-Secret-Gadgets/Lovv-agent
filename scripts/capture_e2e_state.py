# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "boto3>=1.34,<2",
#   "langgraph>=0.6,<2",
#   "opentelemetry-api>=1.24.0",
# ]
# ///
# ─── How to run ───
# uv run scripts/capture_e2e_state.py --mock
# LOVV_ENABLE_AWS_SMOKE=1 uv run scripts/capture_e2e_state.py --live

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lovv_agent.adapters.aws_runtime import build_aws_runtime_adapters
from lovv_agent.config import (
    AwsSettings,
    DynamoDbSettings,
    EmbeddingSettings,
    LlmSettings,
    RuntimeConfig,
    S3VectorSettings,
)
from lovv_agent.harness import build_harness, build_live_harness
from tests.test_harness import RecordingAwsFactory

RESULTS_DIR = ROOT / "docs" / "tasks" / "results"


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--request-id", default="REQ-E2E-DUMP-1")
    args = parser.parse_args()

    harness = _live_harness() if args.live else _mock_harness()
    state = harness.invoke_state(_payload(), request_id=args.request_id)
    path = _write_dump(state.to_dict())
    print(path)
    return 0


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


def _write_dump(state: dict[str, object]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"e2e_state_dump_{timestamp}.json"
    path.write_text(
        json.dumps(state, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    raise SystemExit(main())
