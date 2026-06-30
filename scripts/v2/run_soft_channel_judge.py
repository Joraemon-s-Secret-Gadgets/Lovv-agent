#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DEFAULT_BASE = Path(
    "docs/tasks/results/v2_retrieval_smoke/20260629T121521/soft_channel"
)
DEFAULT_MODEL = "gpt-4o-mini"

PAIRWISE_INSTRUCTIONS = """
You are evaluating two city recommendation candidate sets for a travel planning agent.

Judge only from the user request and the visible candidate information.
The two sets are anonymized. Do not infer which one came from which retrieval variant.
Do not use hidden mapping, internal scores, model assumptions, or retrieval source labels.
If internal scores are present in the input, ignore them.

Evaluation priority:
1. Explicit user constraints are most important: requested themes, region/location constraints, trip context, and hard requirements.
2. A set with fewer missing requested themes is usually better.
3. The top-ranked city is more important than lower-ranked cities.
4. Representative seed titles should plausibly support the requested themes.
5. Soft preference, mood, vibe, quietness, liveliness, or emotional tone is a secondary criterion.
6. Do not choose a set only because it has more variety. Choose it only if the higher-ranked cities better satisfy the request.
7. If A and B are materially similar, choose Tie.

Important rule:
Explicit theme and region fit must outweigh soft vibe fit.
A set should not win if it satisfies the soft vibe but misses important requested themes.

Return JSON only with keys: winner, reason.
winner must be exactly one of: A, B, Tie.
reason must be one concise Korean sentence explaining the decisive criterion.
"""

CANDIDATE_INSTRUCTIONS = """
You are evaluating whether a retrieved travel attraction matches the user's soft preference.

Judge only from the visible information:
- user raw query
- soft preference
- requested themes
- candidate title
- city
- theme tags
- subtype

Do not assume facts that are not visible.
Do not use external knowledge about actual popularity, crowd level, quietness, or tourist traffic.
If the soft preference is about quietness, liveliness, popularity, or crowdedness, require visible evidence from the title, subtype, or tags.
If the visible information is insufficient, give at most 3 points.

Scoring rubric:
1 = clearly conflicts with the soft preference
2 = weak or unlikely match
3 = related to the theme, but soft mood/vibe is unclear or unsupported
4 = good match with visible evidence
5 = excellent match with strong visible evidence

Important rule:
A candidate should not receive 4 or 5 only because it matches the broad travel theme.
It must visibly match the soft preference.

Return JSON only with keys: score, reason.
score must be an integer from 1 to 5.
reason must be one concise Korean sentence explaining the visible evidence or uncertainty.
"""


class JudgeClient(Protocol):
    def judge(self, *, instructions: str, user_input: str) -> str: ...


@dataclass(frozen=True, slots=True)
class OpenAIJudgeClient:
    model: str
    temperature: float
    max_output_tokens: int

    def judge(self, *, instructions: str, user_input: str) -> str:
        from openai import OpenAI

        client = OpenAI()
        response = client.responses.create(
            model=self.model,
            instructions=instructions,
            input=user_input,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )
        return response.output_text


@dataclass(frozen=True, slots=True)
class JudgeRunConfig:
    mode: str
    input_path: Path
    output_path: Path
    model: str
    limit: int | None
    resume: bool
    sleep_seconds: float


def main() -> int:
    args = _parse_args()
    _load_env_file(args.env_file)
    if not os.environ.get("OPENAI_API_KEY") and not args.dry_run:
        print(f"OPENAI_API_KEY is missing. Add it to {args.env_file}.", file=sys.stderr)
        return 2
    mode = args.mode
    runs = _planned_runs(mode, args)
    if args.dry_run:
        for config in runs:
            print(f"{config.mode}: {config.input_path} -> {config.output_path}")
        return 0
    client = OpenAIJudgeClient(
        model=args.model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
    )
    for config in runs:
        run_judge(config, client)
    return 0


def run_judge(config: JudgeRunConfig, client: JudgeClient) -> int:
    processed = _processed_task_ids(config.output_path) if config.resume else set()
    count = 0
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    with config.output_path.open(
        "a" if config.resume else "w", encoding="utf-8", newline="\n"
    ) as handle:
        for task in _read_jsonl(config.input_path):
            task_id = _required_text(task, "task_id")
            if task_id in processed:
                continue
            result = judge_one(config.mode, task, client, config.model)
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            count += 1
            if config.limit is not None and count >= config.limit:
                break
            if config.sleep_seconds > 0:
                time.sleep(config.sleep_seconds)
    return count


def judge_one(
    mode: str, task: dict[str, Any], client: JudgeClient, model: str
) -> dict[str, Any]:
    match mode:
        case "pairwise":
            raw = client.judge(
                instructions=PAIRWISE_INSTRUCTIONS, user_input=_pairwise_prompt(task)
            )
            parsed = _parse_json_object(raw)
            winner = parsed.get("winner")
            reason = parsed.get("reason")
            if winner not in {"A", "B", "Tie"}:
                winner = "Tie"
                reason = f"invalid winner from model: {raw[:160]}"
            return {
                "task_id": _required_text(task, "task_id"),
                "case_id": _required_text(task, "case_id"),
                "winner": winner,
                "reason": _clean_reason(reason),
                "model": model,
            }
        case "candidate":
            raw = client.judge(
                instructions=CANDIDATE_INSTRUCTIONS, user_input=_candidate_prompt(task)
            )
            parsed = _parse_json_object(raw)
            return {
                "task_id": _required_text(task, "task_id"),
                "case_id": _required_text(task, "case_id"),
                "judge_score": _score(parsed.get("score")),
                "judge_reason": _clean_reason(parsed.get("reason")),
                "model": model,
            }
        case unreachable:
            raise AssertionError(f"unsupported mode: {unreachable}")


def _planned_runs(mode: str, args: argparse.Namespace) -> list[JudgeRunConfig]:
    base = args.base_dir
    pairwise = JudgeRunConfig(
        mode="pairwise",
        input_path=args.pairwise_input or base / "judge_input_sanitized.jsonl",
        output_path=args.pairwise_output or base / "pairwise_city_judgements.jsonl",
        model=args.model,
        limit=args.limit,
        resume=args.resume,
        sleep_seconds=args.sleep,
    )
    candidate = JudgeRunConfig(
        mode="candidate",
        input_path=args.candidate_input
        or base / "soft_only_candidates_for_judge.jsonl",
        output_path=args.candidate_output
        or base / "soft_only_candidate_judgements.jsonl",
        model=args.model,
        limit=args.limit,
        resume=args.resume,
        sleep_seconds=args.sleep,
    )
    match mode:
        case "pairwise":
            return [pairwise]
        case "candidate":
            return [candidate]
        case "both":
            return [pairwise, candidate]
        case unreachable:
            raise AssertionError(f"unsupported mode: {unreachable}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run GPT judge for V2 soft-channel validation JSONL files."
    )
    parser.add_argument(
        "--mode", choices=["pairwise", "candidate", "both"], default="pairwise"
    )
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--pairwise-input", type=Path)
    parser.add_argument("--candidate-input", type=Path)
    parser.add_argument("--pairwise-output", type=Path)
    parser.add_argument("--candidate-output", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-output-tokens", type=int, default=180)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _pairwise_prompt(task: dict[str, Any]) -> str:
    visible = {
        "raw_query": task.get("raw_query"),
        "soft_query": task.get("soft_query"),
        "themes": task.get("themes"),
        "candidate_set_a": task.get("variant_a"),
        "candidate_set_b": task.get("variant_b"),
        "evaluation_criteria": [
            "explicit requested themes",
            "soft mood or vibe preference",
            "plausibility as a travel destination",
            "clarity of representative seed",
            "absence of severe missing-theme issues",
        ],
    }
    return json.dumps(visible, ensure_ascii=False, indent=2)


def _candidate_prompt(task: dict[str, Any]) -> str:
    visible = {
        "raw_query": task.get("raw_query"),
        "soft_query": task.get("soft_query"),
        "themes": task.get("themes"),
        "candidate": task.get("candidate"),
        "score_scale": {
            "1": "clearly does not match",
            "2": "weak match",
            "3": "partial or ambiguous match",
            "4": "good match",
            "5": "excellent match",
        },
    }
    return json.dumps(visible, ensure_ascii=False, indent=2)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        data = json.loads(line)
        if not isinstance(data, dict):
            raise TypeError(f"{path}:{line_number} must contain a JSON object")
        yield data


def _processed_task_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for item in _read_jsonl(path):
        task_id = item.get("task_id")
        if isinstance(task_id, str):
            ids.add(task_id)
    return ids


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise TypeError("model output must be a JSON object")
    return parsed


def _score(value: Any) -> int:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, int) and 1 <= value <= 5:
        return value
    return 3


def _clean_reason(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else "no reason"


def _required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value:
        return value
    raise KeyError(f"missing required text field: {key}")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
