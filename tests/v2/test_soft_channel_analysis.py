from __future__ import annotations

import json
from pathlib import Path

from lovv_agent_v2.analysis.soft_channel import ValidationConfig, load_cases, run_validation


def test_load_cases_uses_saved_soft_and_raw_retrieval_without_network(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_case(input_dir / "001_case.json", soft_query="조용한 분위기")

    cases = load_cases(input_dir, top_n=2)

    assert len(cases) == 1
    assert cases[0].case_id == "case-1"
    assert cases[0].has_soft_query
    assert [candidate.place_id for candidate in cases[0].raw_candidates] == ["raw-1", "shared"]
    assert [candidate.place_id for candidate in cases[0].soft_candidates] == ["soft-1", "shared"]


def test_run_validation_writes_required_artifacts(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    _write_case(input_dir / "001_case.json", soft_query="조용한 분위기")
    _write_case(input_dir / "002_case.json", case_id="case-2", soft_query="")

    run_validation(ValidationConfig(input_dir=input_dir, output_dir=output_dir, top_n=2, city_top_k=3))

    expected = {
        "case_metrics.csv",
        "summary_metrics.json",
        "soft_only_candidates_for_judge.csv",
        "soft_only_candidates_for_judge.jsonl",
        "city_ablation_topk.csv",
        "ranking_stability.csv",
        "pairwise_city_judge_tasks.jsonl",
        "judge_input_sanitized.jsonl",
        "pairwise_auto_ties.jsonl",
        "soft_channel_validation_report.md",
    }
    assert expected == {path.name for path in output_dir.iterdir()}
    summary = json.loads((output_dir / "summary_metrics.json").read_text(encoding="utf-8"))
    assert summary["case_count"] == 2
    assert summary["soft_query_case_count"] == 1
    assert summary["mean_place_jaccard"] == 0.333333
    assert "weak" not in (output_dir / "soft_channel_validation_report.md").read_text(encoding="utf-8")
    sanitized = (output_dir / "judge_input_sanitized.jsonl").read_text(encoding="utf-8").splitlines()
    auto_ties = (output_dir / "pairwise_auto_ties.jsonl").read_text(encoding="utf-8").splitlines()
    candidate_rows = (output_dir / "soft_only_candidates_for_judge.jsonl").read_text(encoding="utf-8").splitlines()
    assert sanitized == []
    assert len(auto_ties) == 8
    tie = json.loads(auto_ties[0])
    assert tie["auto_winner"] == "Tie"
    assert "hidden_mapping" not in tie
    assert "score" not in json.dumps(tie, ensure_ascii=False)
    assert tie["variant_a"]["cities"][0]["representative_seed_subtype_name"] == "해변. 해수욕장"
    assert "representative_seed_subtype_label" not in tie["variant_a"]["cities"][0]
    candidate = json.loads(candidate_rows[0])
    assert candidate["candidate"]["subtype_name"] == "해변. 해수욕장"
    assert "subtype_label" not in candidate["candidate"]


def _write_case(path: Path, *, case_id: str = "case-1", soft_query: str) -> None:
    payload = {
        "case_id": case_id,
        "query": {
            "raw_query": "바다 여행",
            "soft_query": soft_query,
            "themes": ["바다·해안"],
        },
        "channels": {
            "raw": {
                "per_theme": {
                    "바다·해안": {
                        "ranked": [
                            _candidate("raw-1", 1, 0.10, "CITY#RAW", "속초", "Raw Beach"),
                            _candidate("shared", 2, 0.20, "CITY#SHARED", "강릉", "Shared Beach"),
                        ],
                    },
                },
                "per_theme_union": {
                    "ranked": [
                        _candidate("raw-1", 1, 0.10, "CITY#RAW", "속초", "Raw Beach"),
                        _candidate("shared", 2, 0.20, "CITY#SHARED", "강릉", "Shared Beach"),
                    ],
                },
            },
            "soft": {
                "per_theme": {
                    "바다·해안": {
                        "ranked": [
                            _candidate("soft-1", 1, 0.05, "CITY#SOFT", "고성", "Soft Beach"),
                            _candidate("shared", 2, 0.30, "CITY#SHARED", "강릉", "Shared Beach"),
                        ],
                    },
                },
                "per_theme_union": {
                    "ranked": [
                        _candidate("soft-1", 1, 0.05, "CITY#SOFT", "고성", "Soft Beach"),
                        _candidate("shared", 2, 0.30, "CITY#SHARED", "강릉", "Shared Beach"),
                    ],
                },
            },
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _candidate(place_id: str, rank: int, distance: float, city_key: str, city_name: str, title: str) -> dict[str, object]:
    return {
        "rank": rank,
        "place_id": place_id,
        "distance": distance,
        "city_id": city_key.removeprefix("CITY#"),
        "city_name_ko": city_name,
        "title": title,
        "theme_tags": ["바다·해안"],
        "subtype": "NA020900",
        "ddb_pk": city_key,
        "ddb_sk": f"ATTRACTION#{place_id}",
    }
