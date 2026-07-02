"""Unit tests for the standalone Intent playground helpers."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import types

import pytest


MODULE_PATH = Path(__file__).with_name("run.py")
LIVE_BEDROCK_MODEL_ID = "openai.gpt-oss-120b-1:0"
LIVE_BEDROCK_REGION = "us-east-1"
SPEC = importlib.util.spec_from_file_location("intent_playground_run", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
playground = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(playground)

from lovv_agent_v2.agents.intent.node import intent_node  # noqa: E402


TEXTFIELD_CASES_PATH = Path(__file__).with_name("v2_textfield_cases.jsonl")


def _live_bedrock_runtime():
    args = types.SimpleNamespace(
        region=os.environ.get("LOVV_AWS_REGION", LIVE_BEDROCK_REGION),
        profile=os.environ.get("LOVV_AWS_PROFILE"),
    )
    return playground.build_runtime(
        args,
        os.environ.get("LOVV_LLM_MODEL_ID", LIVE_BEDROCK_MODEL_ID),
    )


def _load_textfield_cases():
    return [
        json.loads(line)
        for line in TEXTFIELD_CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _state_from_textfield_case(case):
    textfield = case["api_structured_input"]
    return {
        "request": {
            "country": textfield["country"],
            "travel_month": textfield["travelMonth"],
            "travel_year": textfield["travelYear"],
            "trip_type": textfield["tripType"],
            "active_required_themes": textfield["themes"],
            "include_festivals": textfield["includeFestivals"],
            "naturalLanguageQuery": textfield["naturalLanguageQuery"],
            "softPreferenceQuery": textfield.get("softPreferenceQuery", ""),
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
            "user_location": textfield["userLocation"],
            "execution_mode": "city_discovery",
        }
    }


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


def test_live_bedrock_converse_smoke_uses_playground_runtime() -> None:
    runtime = _live_bedrock_runtime()
    request = playground.build_request(
        prompt=(
            "You return only valid JSON matching the requested schema. "
            "Keep Korean text concise."
        ),
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["cleaned_raw_query", "soft_preference_query"],
            "properties": {
                "cleaned_raw_query": {"type": "string"},
                "soft_preference_query": {"type": "string"},
            },
        },
        case_input={
            "api_structured_input": {"country": "KR"},
            "conversation_summary": None,
            "messages": [
                {
                    "role": "user",
                    "content": "history sites and quiet nature",
                },
            ],
        },
        max_tokens=512,
        temperature=0,
    )

    response = runtime(request)
    output = playground.extract_structured_output(response)

    assert isinstance(output["cleaned_raw_query"], str)
    assert isinstance(output["soft_preference_query"], str)


def test_live_bedrock_drives_v2_intent_node_prompt_runtime() -> None:
    runtime = _live_bedrock_runtime()
    state = _state_from_textfield_case(_load_textfield_cases()[0])

    output = intent_node(
        state
        | {
            "runtime": {
                "intent_prompt_runtime": {
                    "runtime": runtime,
                    "schema_retry_limit": 3,
                },
            },
        },
    )

    intent = output["intent"]
    city_input = intent["city_select_input"]
    assert intent["intent_extraction_mode"] == "prompt_structured_output"
    assert isinstance(city_input["cleaned_raw_query"], str)
    assert city_input["cleaned_raw_query"]
    assert city_input["congestion_pref"] in {"quiet", "vibrant", "neutral"}
    assert city_input["transport_pref"] in {"walk", "car", "unknown"}


@pytest.mark.parametrize("case", _load_textfield_cases(), ids=lambda case: case["case_id"])
def test_live_bedrock_extracts_textfield_intent_cases(case) -> None:
    runtime = _live_bedrock_runtime()
    state = _state_from_textfield_case(case)
    output = intent_node(
        state
        | {
            "runtime": {
                "intent_prompt_runtime": {
                    "runtime": runtime,
                    "schema_retry_limit": 3,
                },
            },
        },
    )

    intent = output["intent"]
    city_input = intent["city_select_input"]
    expected = case["expected"]
    assert intent["intent_extraction_mode"] == "prompt_structured_output"
    for key in ("transport_pref", "congestion_pref"):
        if key in expected:
            assert city_input[key] == expected[key]
    if "active_required_themes" in expected:
        assert city_input["active_required_themes"] == expected["active_required_themes"]
    for key in (
        "preferred_theme_ids",
        "disliked_theme_ids",
        "preferred_region_ids",
        "disliked_region_ids",
    ):
        if key in expected:
            assert intent[key] == tuple(expected[key])


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
