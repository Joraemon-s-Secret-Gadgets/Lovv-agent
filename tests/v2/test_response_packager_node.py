from __future__ import annotations

from lovv_agent_v2.agents.response_packager.agent import ResponsePackagerAgent
from lovv_agent_v2.agents.response_packager.contracts import ResponsePackagerInput
from lovv_agent_v2.agents.response_packager.node import response_packager_node


def test_response_packager_flattens_verified_festival_city_payloads() -> None:
    result = response_packager_node(
        {
            "request": {
                "request_id": "REQ-FEST",
                "country": "KR",
                "travel_month": 10,
                "trip_type": "2d1n",
                "destination_id": None,
                "themes": ("역사·전통",),
            },
            "festival_gate": {
                "result": {
                    "verified_festival_cities": [
                        {
                            "city_id": "KR-36-4",
                            "city_name": "김해시",
                            "festivals": [
                                {
                                    "festival_id": "F-1",
                                    "name": "가야문화축제",
                                    "date_status": "confirmed",
                                    "event_start_date": "2026-10",
                                    "event_end_date": "2026-10",
                                    "source": "dynamodb",
                                },
                            ],
                        },
                    ],
                },
            },
        },
    )

    payload = result["response"]["response_payload"]
    verifications = payload["festivalDateVerifications"]
    assert verifications[0]["festivalId"] == "F-1"
    assert verifications[0]["dateStatus"] == "confirmed"


def test_response_packager_agent_packages_without_unified_state() -> None:
    output = ResponsePackagerAgent().run(
        ResponsePackagerInput(
            request={
                "request_id": "REQ-AGENT",
                "country": "KR",
                "travel_month": 10,
                "trip_type": "daytrip",
                "destination_id": None,
                "themes": ("바다·해안",),
            },
            planner_output=None,
            selected_city=None,
            festival_verifications=(),
            unsupported_conditions=(),
            clarification=None,
        ),
    )

    assert output.response["response_status"] == "completed"
    assert output.response["response_payload"]["recommendationId"] == "REQ-AGENT"


def test_response_packager_agent_packages_clarification_mapping() -> None:
    clarification = {
        "reason_code": "festival_none",
        "prompt": "확정 축제 도시가 없습니다. 축제 없이 계속할까요?",
        "options": [
            {
                "option_id": "continue_without_festival",
                "label": "축제 없이 계속",
                "apply": {"include_festivals": False},
                "then": "rerun_discovery",
            },
        ],
        "context": {"travel_month": 10},
        "failure_signals": ["no_confirmed_festival_city"],
    }

    output = ResponsePackagerAgent().run(
        ResponsePackagerInput(
            request={
                "request_id": "REQ-WAIT",
                "country": "KR",
                "travel_month": 10,
                "trip_type": "daytrip",
                "destination_id": None,
                "themes": ("축제·이벤트",),
            },
            planner_output=None,
            selected_city=None,
            festival_verifications=(),
            unsupported_conditions=(),
            clarification=clarification,
        ),
    )

    payload = output.response["response_payload"]
    assert output.response["response_status"] == "END_WAIT_USER"
    assert payload["clarification"]["reasonCode"] == "festival_none"
    assert payload["explainability"]["userNotice"] == clarification["prompt"]
