from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


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


def write_summary(
    result_dir: Path,
    runs: Sequence[TestRun],
    *,
    branch: str,
    commit: str,
) -> None:
    body = [
        "# AgentV2 Intent 로컬 테스트 결과",
        "",
        "## 범위",
        "",
        f"- Branch: `{branch}`",
        f"- Base commit: `{commit}`",
        "- 목표: 사용자 발화에서 선호/비선호 테마를 추출한다.",
        "- 목표: 사용자 발화에서 선호/비선호 지역과 한글 지역명을 추출한다.",
        "- 대상: AgentV2 intent parser, prompt runtime, preference validator, intent node handoff.",
        "",
        "## 결과",
        "",
    ]
    for run in runs:
        body.extend(
            [
                f"- `{display_command(run.command)}`",
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
            "- `intent_extraction_mode`",
        ]
    )
    _write_text(result_dir / "summary.md", body)


def write_test_output(result_dir: Path, runs: Sequence[TestRun]) -> None:
    body = ["# AgentV2 Intent 테스트 출력 결과", ""]
    for run in runs:
        body.extend(
            [
                f"## {run.name}",
                "",
                "실행 명령:",
                "",
                "```bash",
                display_command(run.command),
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
            "- 테스트 Input/Output 결과: `input_output.md`",
        ]
    )
    _write_text(result_dir / "test_output.md", body)


def write_report(result_dir: Path, runs: Sequence[TestRun], *, scope: str) -> None:
    body = [
        "# AgentV2 Intent Test Report",
        "",
        f"> Evidence Directory: `{_posix(result_dir)}`",
        "",
        "## Summary",
        "",
        f"- Scope: {scope}",
        f"- Overall: `{'PASS' if all(run.return_code == 0 for run in runs) else 'FAIL'}`",
        "",
        "## Results",
        "",
        "| Check | Result | Evidence |",
        "|---|---:|---|",
    ]
    for run in runs:
        body.append(f"| {run.name} | `{run.passed_line}` | `{run.log_name}` |")
    body.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `summary.md`",
            "- `test_output.md`",
            "- `input_output.md`",
            "- raw pytest logs listed in the result table",
        ]
    )
    _write_text(result_dir / "report.md", body)


def refresh_result_index(result_root: Path) -> None:
    result_root.mkdir(parents=True, exist_ok=True)
    rows = [_index_row(path) for path in sorted(result_root.iterdir(), reverse=True) if path.is_dir()]
    body = [
        "# AgentV2 Intent Test Results",
        "",
        "AgentV2 intent 관련 테스트 결과는 이 폴더 아래 timestamp 단위로 자동 생성한다.",
        "",
        "## Runs",
        "",
        "| Timestamp | Main Result | Entry Point |",
        "|---|---:|---|",
        *rows,
        "",
        "## Generate",
        "",
        "```powershell",
        "uv run python scripts/v2/run_agentv2_intent_tests.py",
        "```",
    ]
    _write_text(result_root / "README.md", body)


def display_command(command: Sequence[str]) -> str:
    parts = ["python" if index == 0 and part.endswith("python.exe") else part for index, part in enumerate(command)]
    return " ".join(parts)


def _index_row(path: Path) -> str:
    entry = "report.md" if (path / "report.md").exists() else "summary.md"
    result = _first_result_line(path / entry)
    return f"| `{path.name}` | {result} | [`{entry}`](./{path.name}/{entry}) |"


def _first_result_line(path: Path) -> str:
    if not path.exists():
        return "n/a"
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.startswith("- Overall:"):
            return line.replace("|", "\\|").strip()
    for line in lines:
        if " passed" in line or " failed" in line or "FAIL" in line or "PASS" in line:
            return line.replace("|", "\\|").strip()
    return "see report"


def _write_text(path: Path, lines: Sequence[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _posix(path: Path) -> str:
    parts = path.parts
    if "docs" in parts:
        return "/".join(parts[parts.index("docs") :])
    return path.as_posix()
