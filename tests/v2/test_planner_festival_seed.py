from __future__ import annotations

from typing import cast

from lovv_agent_v2.agents.planner.subgraph import compile_planner_subgraph


def _place(place_id: str, title: str, sim: float) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": ["역사·문화"],
        "assigned_theme": "역사·문화",
        "latitude": 36.56,
        "longitude": 128.72,
        "city_id": "KR-FEST",
        "city_name_ko": "축제시",
        "ddb_pk": "CITY#FEST",
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": sim,
    }


def test_planner_places_verified_festival_as_seed_item() -> None:
    result = compile_planner_subgraph().invoke(_state())

    planner = cast(dict[str, object], result["planner"])
    output = cast(dict[str, object], planner["planner_output"])
    itinerary = cast(list[dict[str, object]], output["itinerary"])
    festival_items = [item for item in itinerary if item["item_type"] == "festival"]
    scratch = cast(dict[str, object], planner["scratch"])
    pool = cast(dict[str, object], scratch["place_pool"])
    pool_audit = cast(dict[str, object], pool["audit"])

    assert len(festival_items) == 1
    assert festival_items[0]["placeId"] == "festival#F-ANDONG"
    assert festival_items[0]["festivalId"] == "F-ANDONG"
    assert festival_items[0]["reason_code"] == "seed_floor"
    assert festival_items[0]["slot"] == "afternoon"
    assert festival_items[0]["eventStartDate"] == "2026-10-01"
    assert pool_audit["festival_seed_count"] == 1


def _state() -> dict[str, object]:
    return {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "축제와 역사 여행",
                "trip_type": "2d1n",
                "active_required_themes": ["역사·문화"],
                "theme_weights": {"역사·문화": 1.0},
                "transport_pref": "car",
                "soft_preference_query": "",
            },
        },
        "festival_gate": {
            "result": {
                "status": "ok",
                "verified_festival_cities": [
                    {
                        "city_id": "KR-FEST",
                        "city_name": "축제시",
                        "ddb_pk": "CITY#FEST",
                        "festivals": [
                            {
                                "festival_id": "F-ANDONG",
                                "name": "안동 문화 축제",
                                "city_id": "KR-FEST",
                                "city_name": "축제시",
                                "month": 10,
                                "theme_tags": ["축제·이벤트"],
                                "event_start_date": "2026-10-01",
                                "event_end_date": "2026-10-05",
                                "date_status": "confirmed",
                                "latitude": 36.56,
                                "longitude": 128.73,
                                "source": "dynamodb",
                            },
                        ],
                    },
                ],
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-FEST",
                    "city_name_ko": "축제시",
                    "country": "KR",
                    "ddb_pk": "CITY#FEST",
                },
                "seeds": [],
            },
            "scoring_audit": {
                "recommended_places": (
                    _place("p-1", "역사 산책로", 0.93),
                    _place("p-2", "문화 거리", 0.89),
                    _place("p-3", "전통 시장", 0.84),
                    _place("p-4", "고택 마을", 0.80),
                ),
                "reserve_places": (),
            },
        },
    }
