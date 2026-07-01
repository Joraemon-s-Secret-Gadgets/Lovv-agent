"""Unit tests for V2 entrypoint routing and pseudonymous actor mapping."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from lovv_agent_v2.agentcore_entrypoint import (
    extract_actor_id,
    extract_graph_payload,
    extract_request_id,
    handle_v2_invocation,
)


def test_extract_actor_id() -> None:
    """Verify that actorId is preferred, and fallback userIds are resolved correctly."""
    # actorId
    assert extract_actor_id({"actorId": "usr-123"}) == "usr-123"
    # actor_id
    assert extract_actor_id({"actor_id": "usr-456"}) == "usr-456"
    # userId
    assert extract_actor_id({"userId": "usr-789"}) == "usr-789"
    # None
    assert extract_actor_id({}) is None


def test_extract_request_id() -> None:
    """Verify extraction of sessionId or requestId."""
    assert extract_request_id({"sessionId": "sess-999"}) == "sess-999"
    assert extract_request_id({"requestId": "req-111"}) == "req-111"
    assert extract_request_id({"headers": {"x-request-id": "hdr-222"}}) == "hdr-222"


@patch("lovv_agent_v2.agentcore_entrypoint._cached_live_harness")
def test_handle_v2_invocation_plumbing(mock_cached_harness: MagicMock) -> None:
    """Verify that handle_v2_invocation correctly maps session and actor ids into graph config."""
    mock_harness_instance = MagicMock()
    mock_harness_instance.invoke.return_value = {
        "trace": {"debug": "hidden"},
        "response": {"response_payload": {"recommendationId": "REC-1"}},
    }
    mock_cached_harness.return_value = mock_harness_instance

    event = {
        "entryType": "chat",
        "country": "KR",
        "travelMonth": 10,
        "tripType": "2d1n",
        "themes": ["sea_coast"],
        "includeFestivals": False,
        "sessionId": "session-xyz",
        "actorId": "actor-abc",
    }

    result = handle_v2_invocation(event)

    # harness.invoke가 호출되었는지 검증하고, 전달된 인자 체크
    mock_harness_instance.invoke.assert_called_once()
    args, kwargs = mock_harness_instance.invoke.call_args
    
    # 1. Payload가 제대로 분리되었는지
    payload = args[0]
    assert payload["request"]["country"] == "KR"
    assert payload["intent"]["city_select_input"]["travel_month"] == 10
    
    # 2. request_id가 sessionId 인지
    assert kwargs["request_id"] == "session-xyz"
    
    # 3. graph_config가 적절한 thread_id와 actor_id를 들고 있는지
    graph_config = kwargs["graph_config"]
    assert graph_config["configurable"]["thread_id"] == "session-xyz"
    assert graph_config["configurable"]["actor_id"] == "actor-abc"
    assert result == {"recommendationId": "REC-1"}


def test_extract_graph_payload_wraps_generation_intent_mock() -> None:
    event = {
        "id": "v2_gen_10_history_festival_2d1n",
        "intent_output": {
            "country": "KR",
            "travel_month": 10,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "active_required_themes": ["역사·전통"],
            "include_festivals": True,
            "cleaned_raw_query": "가을 전통 축제와 유적을 함께 보는 1박 2일 일정이요.",
            "soft_preference_query": "",
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
            "destination_id": None,
            "user_location": None,
            "unsupported_conditions": [],
        },
    }

    payload = extract_graph_payload(event, request_id="agentcore-session")

    assert payload["request"]["request_id"] == "agentcore-session"
    assert payload["request"]["themes"] == ("역사·전통",)
    assert payload["intent"]["intent_output"]["include_festivals"] is True
    assert payload["profile"] == {}


def test_extract_graph_payload_wraps_public_recommendation_request() -> None:
    event = {
        "entryType": "chat",
        "country": "KR",
        "travelMonth": 6,
        "travelYear": 2026,
        "tripType": "daytrip",
        "themes": ["바다·해안"],
        "includeFestivals": False,
        "rawQuery": "조용한 바다 당일치기",
        "congestionPref": "quiet",
        "transportPref": "car",
    }

    payload = extract_graph_payload(event, request_id="REQ-PUBLIC")

    city_input = payload["intent"]["city_select_input"]
    assert payload["request"]["request_id"] == "REQ-PUBLIC"
    assert city_input["active_required_themes"] == ("바다·해안",)
    assert city_input["cleaned_raw_query"] == "조용한 바다 당일치기"
    assert city_input["execution_mode"] == "city_discovery"
