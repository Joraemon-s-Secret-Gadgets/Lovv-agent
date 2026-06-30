from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "v2" / "run_soft_channel_judge.py"
SPEC = importlib.util.spec_from_file_location("run_soft_channel_judge", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load run_soft_channel_judge.py")
judge_runner = importlib.util.module_from_spec(SPEC)
sys.modules["run_soft_channel_judge"] = judge_runner
SPEC.loader.exec_module(judge_runner)


@dataclass(frozen=True, slots=True)
class FakeJudgeClient:
    response: str

    def judge(self, *, instructions: str, user_input: str) -> str:
        assert "hidden_mapping" not in user_input
        assert '"score"' not in user_input
        assert instructions
        return self.response


def test_judge_one_pairwise_returns_winner_without_hidden_mapping_or_scores() -> None:
    task = {
        "task_id": "pairwise::case-1::soft_weight_0.10",
        "case_id": "case-1",
        "raw_query": "바다 여행",
        "soft_query": "조용한 분위기",
        "themes": ["바다·해안"],
        "variant_a": {"label": "A", "cities": [_city("속초")]},
        "variant_b": {"label": "B", "cities": [_city("고성")]},
    }

    result = judge_runner.judge_one(
        "pairwise",
        task,
        FakeJudgeClient('{"winner":"B","reason":"soft preference에 더 잘 맞습니다."}'),
        "gpt-4o-mini",
    )

    assert result == {
        "task_id": "pairwise::case-1::soft_weight_0.10",
        "case_id": "case-1",
        "winner": "B",
        "reason": "soft preference에 더 잘 맞습니다.",
        "model": "gpt-4o-mini",
    }


def test_run_judge_resumes_existing_task_ids(tmp_path: Path) -> None:
    input_path = tmp_path / "judge_input_sanitized.jsonl"
    output_path = tmp_path / "pairwise_city_judgements.jsonl"
    input_rows = [
        {"task_id": "task-1", "case_id": "case-1", "variant_a": {"cities": []}, "variant_b": {"cities": []}},
        {"task_id": "task-2", "case_id": "case-2", "variant_a": {"cities": []}, "variant_b": {"cities": []}},
    ]
    input_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in input_rows) + "\n", encoding="utf-8")
    output_path.write_text(json.dumps({"task_id": "task-1", "case_id": "case-1", "winner": "Tie"}) + "\n", encoding="utf-8")
    config = judge_runner.JudgeRunConfig(
        mode="pairwise",
        input_path=input_path,
        output_path=output_path,
        model="gpt-4o-mini",
        limit=None,
        resume=True,
        sleep_seconds=0.0,
    )

    count = judge_runner.run_judge(
        config,
        FakeJudgeClient('{"winner":"A","reason":"A가 더 적합합니다."}'),
    )

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert count == 1
    assert len(lines) == 2
    assert json.loads(lines[1])["task_id"] == "task-2"


def test_judge_one_candidate_clamps_invalid_score_to_neutral() -> None:
    task = {
        "task_id": "soft_only::case-1::place-1",
        "case_id": "case-1",
        "raw_query": "바다 여행",
        "soft_query": "조용한 분위기",
        "themes": ["바다·해안"],
        "candidate": {"title": "해변"},
    }

    result = judge_runner.judge_one(
        "candidate",
        task,
        FakeJudgeClient('{"score":9,"reason":"점수 범위 밖입니다."}'),
        "gpt-4o-mini",
    )

    assert result["judge_score"] == 3
    assert result["judge_reason"] == "점수 범위 밖입니다."


def _city(name: str) -> dict[str, Any]:
    return {
        "rank": 1,
        "city_name_ko": name,
        "representative_seed_title": "대표 장소",
        "missing_themes": [],
    }
