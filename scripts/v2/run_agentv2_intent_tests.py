#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class TestRun:
    name: str
    command: tuple[str, ...]
    log_name: str
    return_code: int
    stdout: str
    stderr: str

    @property
    def output_text(self) -> str:
        if self.stderr:
            return f"{self.stdout.rstrip()}\n{self.stderr.rstrip()}\n"
        return f"{self.stdout.rstrip()}\n"

    @property
    def passed_line(self) -> str:
        for line in reversed(self.output_text.splitlines()):
            if " passed" in line or " failed" in line or " error" in line:
                return line.strip()
        return "결과 요약을 찾지 못함"


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
    runs = (agent_run, playground_run)

    _write_summary(result_dir, runs)
    _write_test_output(result_dir, runs)
    _write_input_output(result_dir)

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


def _write_summary(result_dir: Path, runs: Sequence[TestRun]) -> None:
    branch = _git_text("branch", "--show-current")
    commit = _git_text("rev-parse", "--short", "HEAD")
    body = [
        "# AgentV2 Intent 로컬 테스트 결과",
        "",
        "## 범위",
        "",
        f"- Branch: `{branch}`",
        f"- Base commit: `{commit}`",
        "- 목표: 사용자 발화에서 선호/비선호 테마를 추출한다.",
        "- 목표: 사용자 발화에서 선호/비선호 지역과 한글 지역명을 추출한다.",
        "- 대상: AgentV2 deterministic intent parser, modify parser, preference validator, intent node handoff.",
        "- GitHub main issue: #18",
        "- GitHub sub issue: #19, #20, #21, #22, #23, #24",
        "",
        "## 결과",
        "",
    ]
    for run in runs:
        body.extend(
            [
                f"- `{_display_command(run.command)}`",
                f"  - 결과: `{run.passed_line}`",
                f"  - 종료 코드: `{run.return_code}`",
                f"  - 원문 로그: `{run.log_name}`",
                "  - 출력 결과: `test_output.md`",
                "  - Input/Output 결과: `input_output.md`",
            ]
        )
    body.extend(
        [
            "",
            "## 실패",
            "",
            "- 없음." if all(run.return_code == 0 for run in runs) else "- 실패한 pytest 실행이 있다. 원문 로그를 확인한다.",
            "",
            "## 후속 작업",
            "",
            "- Live smoke testing은 이 로컬 unit/playground gate와 별도로 수행한다.",
            "",
            "## 검증 필드",
            "",
            "- `preferred_theme_ids`",
            "- `disliked_theme_ids`",
            "- `preferred_region_ids`",
            "- `preferred_region_names`",
            "- `disliked_region_ids`",
            "- `disliked_region_names`",
            "- `needs_clarification`",
            "- `clarifying_question`",
            "- `contradiction_reasons`",
            "- `city_select_input.active_required_themes`",
        ]
    )
    (result_dir / "summary.md").write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")


def _write_test_output(result_dir: Path, runs: Sequence[TestRun]) -> None:
    body = ["# AgentV2 Intent 테스트 출력 결과", ""]
    for run in runs:
        body.extend(
            [
                f"## {run.name}",
                "",
                "실행 명령:",
                "",
                "```bash",
                _display_command(run.command),
                "```",
                "",
                "출력:",
                "",
                "```text",
                run.output_text.rstrip(),
                "```",
                "",
                "해석:",
                "",
                f"- 종료 코드: `{run.return_code}`",
                f"- 결과 요약: `{run.passed_line}`",
                "",
            ]
        )
    body.extend(
        [
            "## 종합 결과",
            "",
            f"- 전체 실행 성공 여부: `{all(run.return_code == 0 for run in runs)}`",
            "- 원문 로그: `pytest_agentv2_intent.log`, `pytest_playground.log`",
            "- 테스트 Input/Output 결과: `input_output.md`",
        ]
    )
    (result_dir / "test_output.md").write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")


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


def _display_command(command: Sequence[str]) -> str:
    parts = list(command)
    if parts and parts[0] == sys.executable:
        parts[0] = "python"
    return " ".join(parts).replace(str(REPO_ROOT), ".")


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
