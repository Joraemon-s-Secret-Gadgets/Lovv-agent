from __future__ import annotations

from typing import Any

from lovv_agent_v2.agents.festival_verifier import node as festival_node_module
from lovv_agent_v2.agents.festival_verifier.node import festival_verifier_node
from lovv_agent_v2.core.graph import compile_v2_graph
from lovv_agent_v2.infra.dynamo_lookup import FestivalSeedResult


def _city_input() -> dict[str, object]:
    return {
        "country": "KR",
        "travel_month": 10,
        "travel_year": 2026,
        "trip_type": "2d1n",
        "active_required_themes": ["축제"],
        "include_festivals": True,
        "cleaned_raw_query": "10월 축제 여행",
        "soft_preference_query": "",
        "unsupported_conditions": [],
        "destination_id": None,
        "user_location": None,
        "execution_mode": "city_discovery",
        "congestion_pref": "neutral",
        "transport_pref": "unknown",
    }


def _festival_candidate(
    festival_id: str,
    *,
    city_id: str = "KR-T",
    date_status: str = "tentative",
) -> dict[str, object]:
    return {
        "festival_id": festival_id,
        "name": f"축제 {festival_id}",
        "country": "KR",
        "city_id": city_id,
        "city_name": "통영시",
        "month": 10,
        "theme_tags": ("festival",),
        "event_end_date": "2026-10-05",
        "date_status": date_status,
        "source": "test",
    }


def test_festival_verifier_node_writes_festival_gate_state() -> None:
    # Given: intent asks for festivals and the mock gate input has one confirmed city.
    state = {
        "intent": {"city_select_input": _city_input()},
        "festival_gate": {
            "candidates": (
                _festival_candidate("F-A", city_id="KR-A", date_status="confirmed"),
            ),
        },
    }

    # When: the festival verifier node runs.
    result = festival_verifier_node(state)

    # Then: the gate state exposes the allowed city ids for city_select.
    festival_gate = result["festival_gate"]
    assert festival_gate["allowed_city_ids"] == ["KR-A"]
    assert festival_gate["result"]["status"] == "ok"
    assert festival_gate["clarification"] is None
    assert result["routing"]["needs_clarification"] is False


def test_festival_verifier_node_queries_dynamo_lookup_by_city_when_anchored(
    monkeypatch: Any,
) -> None:
    # Given: no candidates were preloaded, so the node must query the lookup tool.
    lookup = RecordingFestivalLookup()
    monkeypatch.setattr(
        festival_node_module,
        "_build_festival_lookup_tool",
        lambda: lookup,
    )
    city_input = _city_input()
    city_input["destination_id"] = "KR-36-4"
    city_input["city_key"] = "CITY#GIMHAE"
    city_input["execution_mode"] = "anchored_place_search"

    # When: the festival verifier node runs.
    result = festival_verifier_node({"intent": {"city_select_input": city_input}})

    # Then: the lookup receives the GSI/city narrowing inputs and feeds gate state.
    assert lookup.calls == [
        {
            "country": "KR",
            "travel_month": 10,
            "travel_year": 2026,
            "theme_pool": ("축제",),
            "city_id": "KR-36-4",
            "city_key": "CITY#GIMHAE",
            "max_candidates": None,
        },
    ]
    assert result["festival_gate"]["allowed_city_ids"] == ["KR-36-4"]
    assert result["festival_gate"]["result"]["execution_mode"] == "anchored"


def test_graph_stops_before_city_select_when_festival_needs_clarification() -> None:
    # Given: tentative festival data requires a user choice.
    graph = compile_v2_graph()
    state = {
        "intent": {"city_select_input": _city_input()},
        "festival_gate": {"candidates": (_festival_candidate("F-T"),)},
    }

    # When: the graph is invoked.
    result = graph.invoke(state)

    # Then: city_select is not called; the graph ends with a pending clarification.
    assert "city_select" not in result
    assert result["festival_gate"]["result"]["status"] == "needs_clarification"
    assert result["festival_gate"]["clarification"]["reason_code"] == "festival_tentative"
    assert result["routing"]["next_node"] == "response_packager"
    assert result["response"]["response_status"] == "END_WAIT_USER"
    assert result["response"]["response_payload"]["clarification"]["reasonCode"] == "festival_tentative"


class RecordingFestivalLookup:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search_festival_city_seeds(
        self,
        *,
        country: str,
        travel_month: int,
        travel_year: int | None = None,
        theme_pool: tuple[str, ...],
        city_id: str | None = None,
        city_key: str | None = None,
        max_candidates: int | None = None,
    ) -> FestivalSeedResult:
        self.calls.append(
            {
                "country": country,
                "travel_month": travel_month,
                "travel_year": travel_year,
                "theme_pool": theme_pool,
                "city_id": city_id,
                "city_key": city_key,
                "max_candidates": max_candidates,
            },
        )
        return FestivalSeedResult(
            status="ok",
            tier="confirmed",
            allowed_city_ids=("KR-36-4",),
            verified_festival_cities=(
                {
                    "ddb_pk": "CITY#GIMHAE",
                    "city_id": "KR-36-4",
                    "city_name": "김해시",
                    "festivals": [],
                },
            ),
            audit={
                "travel_month": travel_month,
                "target_year": travel_year,
                "requested_destination_id": city_id,
                "candidate_counts": {
                    "confirmed": 1,
                    "tentative": 0,
                    "excluded": 0,
                },
            },
        )
