from __future__ import annotations

from lovv_agent_v2.agents.intent.modify_parser import parse_modify_query
from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.agents.intent.parser import parse_initial_query
from lovv_agent_v2.agents.intent.validator import validate_preference_sets


def test_parse_initial_query_extracts_preferred_theme_ids() -> None:
    result = parse_initial_query("바다랑 로컬 맛집 위주로 2박 3일 여행지를 추천해줘")

    assert result.preferred_theme_ids == ("sea_coast", "food_local")
    assert result.disliked_theme_ids == ()
    assert result.active_theme_labels == ("바다·해안", "미식·노포")


def test_parse_initial_query_extracts_disliked_theme_ids() -> None:
    result = parse_initial_query("전시는 좋지만 등산이나 트레킹 코스는 빼줘")

    assert result.preferred_theme_ids == ("art_sense",)
    assert result.disliked_theme_ids == ("nature_trekking",)


def test_parse_initial_query_extracts_preferred_and_disliked_regions() -> None:
    result = parse_initial_query("속초 말고 안동이나 경주처럼 역사 있는 곳으로 추천해줘")

    assert result.preferred_region_ids == ("andong", "gyeongju")
    assert result.preferred_region_names == ("안동", "경주")
    assert result.disliked_region_ids == ("sokcho",)
    assert result.disliked_region_names == ("속초",)
    assert result.preferred_theme_ids == ("history_tradition",)


def test_validator_flags_theme_and_region_contradictions() -> None:
    result = validate_preference_sets(
        preferred_theme_ids=("sea_coast",),
        disliked_theme_ids=("sea_coast",),
        preferred_region_ids=("gangwon",),
        disliked_region_ids=("gangwon",),
    )

    assert result.needs_clarification is True
    assert result.contradiction_reasons == (
        "theme:sea_coast",
        "region:gangwon",
    )


def test_parse_initial_query_surfaces_clarification_route() -> None:
    result = parse_initial_query("강원도는 싫은데 강원도 바다 여행지를 추천해줘")

    assert result.preferred_region_ids == ("gangwon",)
    assert result.disliked_region_ids == ("gangwon",)
    assert result.needs_clarification is True
    assert result.clarifying_question is not None


def test_parse_initial_query_flags_theme_clarification_route() -> None:
    result = parse_initial_query("바다는 좋은데 바다는 빼줘")

    assert result.preferred_theme_ids == ("sea_coast",)
    assert result.disliked_theme_ids == ("sea_coast",)
    assert result.needs_clarification is True


def test_intent_node_projects_request_preferences_to_intent_payload() -> None:
    output = intent_node(
        {
            "request": {
                "country": "KR",
                "travel_month": 8,
                "travel_year": 2026,
                "trip_type": "couple",
                "include_festivals": True,
                "raw_query": "강원도 말고 경북 바다랑 미식 여행지 추천해줘",
            },
        },
    )

    intent = output["intent"]
    assert intent["preferred_theme_ids"] == ("sea_coast", "food_local")
    assert intent["disliked_theme_ids"] == ()
    assert intent["preferred_region_ids"] == ("gyeongbuk",)
    assert intent["preferred_region_names"] == ("경북",)
    assert intent["disliked_region_ids"] == ("gangwon",)
    assert intent["disliked_region_names"] == ("강원도",)
    assert intent["city_select_input"]["active_required_themes"] == [
        "바다·해안",
        "미식·노포",
    ]


def test_intent_node_prefers_existing_city_select_input_over_request() -> None:
    output = intent_node(
        {
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 9,
                    "travel_year": 2026,
                    "trip_type": "solo",
                    "active_required_themes": ["역사·전통"],
                    "include_festivals": False,
                    "cleaned_raw_query": "안동 역사 여행",
                    "soft_preference_query": "",
                    "unsupported_conditions": [],
                },
            },
            "request": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "solo",
                "include_festivals": False,
                "raw_query": "바다 여행으로 바꿔줘",
            },
        },
    )

    intent = output["intent"]
    assert intent["city_select_input"]["active_required_themes"] == ["역사·전통"]
    assert intent["city_select_input"]["cleaned_raw_query"] == "안동 역사 여행"


def test_intent_node_accepts_intent_output_alias() -> None:
    output = intent_node(
        {
            "intent": {
                "intent_output": {
                    "country": "KR",
                    "travel_month": 9,
                    "travel_year": 2026,
                    "trip_type": "solo",
                    "active_required_themes": ["역사·전통"],
                    "include_festivals": False,
                    "cleaned_raw_query": "안동 역사 여행",
                    "soft_preference_query": "",
                    "unsupported_conditions": [],
                },
                "preferred_theme_ids": ("history_tradition",),
            },
        },
    )

    intent = output["intent"]
    assert intent["city_select_input"]["active_required_themes"] == ["역사·전통"]
    assert intent["preferred_theme_ids"] == ("history_tradition",)


def test_parse_modify_query_extracts_turn_updates() -> None:
    result = parse_modify_query("2일차 오후는 바다 말고 숲길이랑 온천 중심으로 바꿔줘")

    assert result.preferred_theme_ids == ("nature_trekking", "healing_rest")
    assert result.disliked_theme_ids == ("sea_coast",)


def test_parse_modify_query_extracts_region_updates() -> None:
    result = parse_modify_query("속초는 빼고 안동 쪽으로 바꿔줘")

    assert result.preferred_region_ids == ("andong",)
    assert result.preferred_region_names == ("안동",)
    assert result.disliked_region_ids == ("sokcho",)
    assert result.disliked_region_names == ("속초",)
