#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
RESULT_ROOT = REPO_ROOT / "docs" / "tasks" / "results" / "tests" / "agentv2_intent"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lovv_agent_v2.agents.intent.modify_parser import parse_modify_query
from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.agents.intent.parser import parse_initial_query
from lovv_agent_v2.core.state import UnifiedAgentState

from agentv2_intent_results import TestRun, refresh_result_index, write_report, write_summary, write_test_output


def main() -> int:
    args = _parse_args()
    result_dir = _result_dir(args.timestamp)
    result_dir.mkdir(parents=True, exist_ok=True)

    agent_run = _run_pytest(
        name="AgentV2 Intent 로컬 pytest",
        paths=("tests/v2/test_intent.py", "tests/v2/test_state_contract.py"),
        log_name="pytest_agentv2_intent.log",
        result_dir=result_dir,
    )
    playground_run = _run_pytest(
        name="Intent Playground pytest",
        paths=("intent_playground/test_run.py",),
        log_name="pytest_playground.log",
        result_dir=result_dir,
    )
    runtime_run = _run_pytest(
        name="V2 Intent runtime wiring pytest",
        paths=("tests/v2/test_harness.py", "tests/v2/test_config.py", "tests/v2/test_runtime_dependency_injection.py"),
        log_name="pytest_intent_runtime.log",
        result_dir=result_dir,
    )
    runs = (agent_run, playground_run, runtime_run)

    write_summary(result_dir, runs, branch=_git_text("branch", "--show-current"), commit=_git_text("rev-parse", "--short", "HEAD"))
    write_test_output(result_dir, runs)
    _write_input_output(result_dir)
    write_report(result_dir, runs, scope="AgentV2 intent parser, prompt runtime, and harness wiring")
    refresh_result_index(RESULT_ROOT)

    print(f"result_dir={result_dir.relative_to(REPO_ROOT).as_posix()}")
    for run in runs:
        print(f"{run.log_name}: exit_code={run.return_code}, {run.passed_line}")
    return 0 if all(run.return_code == 0 for run in runs) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timestamp", help="YYYYMMDDTHHMMSSZ result folder name")
    return parser.parse_args()


def _result_dir(timestamp: str | None) -> Path:
    folder_name = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return RESULT_ROOT / folder_name


def _run_pytest(
    *,
    name: str,
    paths: tuple[str, ...],
    log_name: str,
    result_dir: Path,
) -> TestRun:
    command = (
        sys.executable,
        "-m",
        "pytest",
        *paths,
        "-q",
        "--basetemp",
        ".cache/pytest-tmp",
        "-p",
        "no:cacheprovider",
    )
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("UV_CACHE_DIR", ".cache/uv")
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    run = TestRun(
        name=name,
        command=command,
        log_name=log_name,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    (result_dir / log_name).write_text(run.output_text, encoding="utf-8", newline="\n")
    return run


def _write_input_output(result_dir: Path) -> None:
    body = [
        "# AgentV2 Intent 테스트 Input/Output 결과",
        "",
        "이 파일은 실제 AgentV2 parser, modify parser, intent node를 호출해 생성한 input/output 결과다.",
        "",
    ]
    cases = _input_output_cases()
    for title, input_payload, output_payload in cases:
        body.extend(
            [
                f"## {title}",
                "",
                "### Input",
                "",
                "```json",
                json.dumps(input_payload, ensure_ascii=False, indent=2),
                "```",
                "",
                "### Output",
                "",
                "```json",
                json.dumps(output_payload, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    (result_dir / "input_output.md").write_text("\n".join(body), encoding="utf-8", newline="\n")


def _input_output_cases() -> tuple[tuple[str, object, object], ...]:
    theme_query = "바다랑 로컬 맛집 위주로 2박 3일 여행지를 추천해줘"
    disliked_theme_query = "전시는 좋지만 등산이나 트레킹 코스는 빼줘"
    region_query = "속초 말고 안동이나 경주처럼 역사 있는 곳으로 추천해줘"
    conflict_query = "강원도는 싫은데 강원도 바다 여행지를 추천해줘"
    node_state: UnifiedAgentState = {
        "request": {
            "country": "KR",
            "travel_month": 8,
            "travel_year": 2026,
            "trip_type": "couple",
            "include_festivals": True,
            "raw_query": "강원도 말고 경북 바다랑 미식 여행지 추천해줘",
        }
    }
    modify_theme_query = "2일차 오후는 바다 말고 숲길이랑 온천 중심으로 바꿔줘"
    modify_region_query = "속초는 빼고 안동 쪽으로 바꿔줘"
    return (
        ("선호 테마 추출", {"raw_query": theme_query}, _result_dict(parse_initial_query(theme_query))),
        ("선호/비선호 테마 분리", {"raw_query": disliked_theme_query}, _result_dict(parse_initial_query(disliked_theme_query))),
        ("선호/비선호 지역 분리", {"raw_query": region_query}, _result_dict(parse_initial_query(region_query))),
        ("지역 선호 충돌 감지", {"raw_query": conflict_query}, _result_dict(parse_initial_query(conflict_query))),
        ("intent_node request handoff", node_state, intent_node(node_state)),
        ("수정 턴 테마 업데이트", {"raw_query": modify_theme_query}, _result_dict(parse_modify_query(modify_theme_query))),
        ("수정 턴 지역 업데이트", {"raw_query": modify_region_query}, _result_dict(parse_modify_query(modify_region_query))),
    )


def _result_dict(result: object) -> dict[str, object]:
    preferred_theme_ids = tuple(getattr(result, "preferred_theme_ids"))
    disliked_theme_ids = tuple(getattr(result, "disliked_theme_ids"))
    preferred_region_ids = tuple(getattr(result, "preferred_region_ids"))
    disliked_region_ids = tuple(getattr(result, "disliked_region_ids"))
    return {
        "cleaned_raw_query": getattr(result, "cleaned_raw_query"),
        "preferred_theme_ids": list(preferred_theme_ids),
        "disliked_theme_ids": list(disliked_theme_ids),
        "preferred_region_ids": list(preferred_region_ids),
        "preferred_region_names": list(getattr(result, "preferred_region_names")),
        "disliked_region_ids": list(disliked_region_ids),
        "disliked_region_names": list(getattr(result, "disliked_region_names")),
        "active_theme_labels": list(getattr(result, "active_theme_labels")),
        "needs_clarification": getattr(result, "needs_clarification"),
        "clarifying_question": getattr(result, "clarifying_question"),
        "contradiction_reasons": list(getattr(result, "contradiction_reasons")),
    }


def _git_text(*args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
