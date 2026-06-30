"""Unit tests for planner nodes."""

from __future__ import annotations

from lovv_agent_v2.agents.planner.node import planner_node
from lovv_agent_v2.agents.planner.place_selection import (
    PlannerSelectionInput,
    build_working_set,
)
from lovv_agent_v2.agents.planner.routing import route_days


def _place(
    place_id: str,
    title: str,
    sim: float,
    theme: str,
    *,
    lat: float = 37.0,
    lon: float = 127.0,
    soft_sim: float | None = None,
) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "assigned_theme": theme,
        "latitude": lat,
        "longitude": lon,
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": soft_sim if soft_sim is not None else sim,
    }


def test_build_working_set_preserves_seed_below_relative_threshold() -> None:
    raw_places = [
        _place("sea-1", "Sea 1", 0.90, "바다·해안"),
        _place("sea-2", "Sea 2", 0.80, "바다·해안"),
        _place("history-seed", "Old Site", 0.20, "역사·문화"),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=({"place_id": "history-seed", "theme": "역사·문화"},),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
        ),
    )

    selected_ids = [place.place_id for place in result.places]
    assert "history-seed" in selected_ids
    assert result.audit["relative_threshold"] == 0.54
    assert result.audit["seed_preserved_count"] == 1


def test_build_working_set_adds_only_on_theme_soft_places() -> None:
    raw_places = [_place("sea-1", "Sea 1", 0.80, "바다·해안")]
    soft_places = [
        _place("history-soft", "향교", 0.10, "역사·문화", soft_sim=0.70),
        _place("nature-soft", "저수지", 0.10, "자연", soft_sim=0.90),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=soft_places,
            seeds=(),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
        ),
    )

    selected_ids = [place.place_id for place in result.places]
    assert "history-soft" in selected_ids
    assert "nature-soft" not in selected_ids
    assert result.audit["soft_on_theme_added_count"] == 1
    assert result.audit["soft_off_theme_excluded_count"] == 1


def test_build_working_set_balances_requested_themes_without_profile() -> None:
    raw_places = [
        _place("sea-1", "Sea 1", 0.90, "바다·해안"),
        _place("sea-2", "Sea 2", 0.88, "바다·해안"),
        _place("sea-3", "Sea 3", 0.87, "바다·해안"),
        _place("history-1", "History 1", 0.60, "역사·문화"),
        _place("history-2", "History 2", 0.58, "역사·문화"),
        _place("history-3", "History 3", 0.57, "역사·문화"),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=4,
        ),
    )

    assert result.audit["theme_quota"] == {"바다·해안": 2, "역사·문화": 2}
    assert result.audit["theme_counts"] == {"바다·해안": 2, "역사·문화": 2}


def test_route_days_uses_minutes_and_keeps_outlier_from_becoming_anchor() -> None:
    places = (
        _place("seed", "Anchor", 0.9, "바다·해안", lat=37.0, lon=127.0),
        _place("near", "Near", 0.8, "바다·해안", lat=37.01, lon=127.01),
        _place("far", "Far", 0.7, "바다·해안", lat=37.8, lon=127.8),
    )
    working_set = build_working_set(
        PlannerSelectionInput(
            raw_places=places,
            soft_places=(),
            seeds=({"place_id": "seed", "theme": "바다·해안"},),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
        ),
    )

    routed = route_days(
        working_set.places,
        trip_type="2d1n",
        transport_pref="car",
    )

    assert len(routed.days) == 2
    assert {day.anchor_type for day in routed.days} == {"seed", "medoid"}
    assert routed.audit["duration_unit"] == "minutes"
    assert routed.audit["outlier_anchor_policy"] == "medoid_not_farthest"
    assert max(day.day_travel_min for day in routed.days) < 150


def test_planner_node_writes_v2_planner_output_from_city_select_state() -> None:
    state = {
        "intent": {
            "city_select_input": {
                "trip_type": "daytrip",
                "active_required_themes": ["바다·해안"],
                "theme_weights": None,
                "transport_pref": "walk",
                "soft_preference_query": "조용한 바다",
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-SOKCHO",
                    "city_name_ko": "속초",
                    "country": "KR",
                    "ddb_pk": "CITY#SOKCHO",
                },
                "seeds": [
                    {"place_id": "seed", "theme": "바다·해안", "must_include": True},
                ],
                "passthrough": {"transport_pref": "walk"},
            },
            "scoring_audit": {
                "recommended_places": [
                    _place("seed", "해변", 0.9, "바다·해안", lat=38.20, lon=128.59),
                    _place("near", "전망대", 0.8, "바다·해안", lat=38.21, lon=128.60),
                    _place("tail", "항구", 0.7, "바다·해안", lat=38.22, lon=128.61),
                ],
                "reserve_places": [],
            },
        },
    }

    result = planner_node(state)

    planner = result["planner"]["planner_output"]
    assert planner["validation_result"]["planner_status_gate"] == "ok"
    assert planner["itinerary"][0]["placeId"] == "seed"
    assert planner["itinerary"][0]["moveMinutes"] == 0
    assert "walk" in " ".join(planner["user_notice"])
