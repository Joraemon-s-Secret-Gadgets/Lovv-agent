"""Unit tests for the standalone Intent playground helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("intent_playground_run", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
playground = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(playground)


def test_build_request_matches_converse_structured_output_shape() -> None:
    request = playground.build_request(
        prompt="system prompt",
        schema={"type": "object", "properties": {}},
        case_input={
            "api_structured_input": {"country": "KR"},
            "conversation_summary": None,
            "messages": [],
        },
        max_tokens=100,
        temperature=0,
    )

    assert request["system"] == [{"text": "system prompt"}]
    assert request["outputConfig"]["textFormat"]["type"] == "json_schema"
    assert request["inferenceConfig"]["temperature"] == 0


@pytest.mark.parametrize(
    ("operator", "actual", "expected", "passed"),
    [
        ("equals", "KR", "KR", True),
        ("contains", "조용한 바다", "조용", True),
        ("not_contains", "바다 산책", "숙소", True),
        ("includes", ["바다·해안"], "바다·해안", True),
        ("length_equals", ["a", "b"], 2, True),
    ],
)
def test_assertion_operators(operator, actual, expected, passed) -> None:
    assert (
        playground.apply_operator(
            operator=operator,
            actual=actual,
            expected=expected,
            found=True,
        )
        is passed
    )


def test_resolve_json_path_supports_nested_objects_and_arrays() -> None:
    payload = {"candidate": {"themes": ["바다·해안"]}}

    assert playground.resolve_json_path(payload, "candidate.themes.0") == (
        "바다·해안",
        True,
    )
    assert playground.resolve_json_path(payload, "candidate.missing") == (None, False)


def test_load_default_cases() -> None:
    cases = playground.load_cases(
        Path(__file__).with_name("cases.jsonl"),
        case_id=None,
    )

    assert len(cases) >= 5
    assert len({case["id"] for case in cases}) == len(cases)


def test_resolve_theme_state_promotes_raw_query_themes_and_backs_up_selected() -> None:
    result = playground.resolve_theme_state(
        {"themes": ["sea_coast", "healing_rest"]},
        {
            "mentioned_theme_ids": ["art_sense"],
            "excluded_theme_ids": [],
        },
    )

    assert result == {
        "active_theme_ids": ["art_sense"],
        "backup_theme_ids": ["sea_coast", "healing_rest"],
        "excluded_theme_ids": [],
    }


def test_resolve_theme_state_keeps_selected_when_raw_query_has_no_theme() -> None:
    result = playground.resolve_theme_state(
        {"themes": ["sea_coast", "healing_rest"]},
        {
            "mentioned_theme_ids": [],
            "excluded_theme_ids": [],
        },
    )

    assert result["active_theme_ids"] == ["sea_coast", "healing_rest"]
    assert result["backup_theme_ids"] == []


def test_vibe_schema_excludes_theme_and_crowd_tags() -> None:
    import json

    schema = json.loads(Path(__file__).with_name("schema.json").read_text(encoding="utf-8"))
    allowed = set(schema["properties"]["desired_vibe_tags"]["items"]["enum"])

    assert {"romantic", "sunset_view", "open_view"} <= allowed
    assert not allowed & {
        "healing",
        "artistic",
        "historic",
        "traditional",
        "quiet",
        "lively",
        "beach",
        "museum",
        "indoor",
        "outdoor",
        "photo_spot",
        "family_friendly",
    }
