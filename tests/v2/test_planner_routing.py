from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.route_days.day_profile import (
    day_place_targets,
    min_day_place_targets,
    trip_min_place_target,
    trip_place_target,
)
from lovv_agent_v2.agents.planner.steps.route_days.place_selection import (
    PlannerSelectionInput,
    build_working_set,
)
from lovv_agent_v2.agents.planner.steps.route_days.routing import route_days


def _place(
    place_id: str,
    title: str,
    sim: float,
    theme: str,
    *,
    lat: float = 37.0,
    lon: float = 127.0,
    soft_sim: float | None = None,
    subtype: str = "view",
    subtype_code: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "assigned_theme": theme,
        "latitude": lat,
        "longitude": lon,
        "attraction_subtype_name": subtype,
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": soft_sim if soft_sim is not None else sim,
    }
    if subtype_code is not None:
        payload["attraction_subtype_code"] = subtype_code
    return payload


def test_trip_place_targets_keep_edge_days_lighter() -> None:
    assert min_day_place_targets("daytrip") == (2,)
    assert day_place_targets("daytrip") == (3,)
    assert min_day_place_targets("2d1n") == (2, 2)
    assert day_place_targets("2d1n") == (3, 3)
    assert min_day_place_targets("3d2n") == (2, 3, 2)
    assert day_place_targets("3d2n") == (3, 4, 3)
    assert trip_min_place_target("daytrip") == 2
    assert trip_place_target("daytrip") == 3
    assert trip_min_place_target("2d1n") == 4
    assert trip_place_target("2d1n") == 6
    assert trip_min_place_target("3d2n") == 7
    assert trip_place_target("3d2n") == 10


def test_route_days_uses_day_place_targets_for_overnight_trips() -> None:
    places = tuple(
        _place(
            f"sea-{index}",
            f"Sea {index}",
            0.90 - index * 0.01,
            "바다·해안",
            subtype=f"coast-{index % 2}",
        )
        for index in range(10)
    )
    working_set = build_working_set(
        PlannerSelectionInput(
            raw_places=places,
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="3d2n",
            target_count=10,
        ),
    )

    routed = route_days(
        working_set.places,
        trip_type="3d2n",
        transport_pref="car",
    )

    assert tuple(len(day.places) for day in routed.days) == (3, 4, 3)
    assert routed.audit["day_place_targets"] == (3, 4, 3)
    assert routed.audit["place_density_policy"] == "edge_days_lighter"


def test_route_days_keeps_nearest_neighbor_order_without_slot_bias() -> None:
    places = (
        _place("seed", "Anchor", 0.95, "바다·해안", lat=37.0, lon=127.0),
        _place("tower", "야경 전망타워", 0.93, "바다·해안", lat=37.01, lon=127.01, subtype_code="VE010200"),
        _place("park", "해안공원", 0.91, "바다·해안", lat=37.08, lon=127.08, subtype_code="NA040300"),
    )
    working_set = build_working_set(
        PlannerSelectionInput(
            raw_places=places,
            soft_places=(),
            seeds=({"place_id": "seed", "theme": "바다·해안"},),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="daytrip",
            target_count=3,
        ),
    )

    routed = route_days(
        working_set.places,
        trip_type="daytrip",
        transport_pref="car",
    )

    assert tuple(item.place.place_id for item in routed.days[0].places) == ("seed", "tower", "park")


def test_route_days_uses_raw_soft_blend_for_semantic_anchor_order() -> None:
    places = (
        _place("raw-heavy", "Raw Heavy", 0.90, "바다·해안", soft_sim=0.70),
        _place("soft-heavy", "Soft Heavy", 0.70, "역사·문화", soft_sim=1.00),
    )
    soft_places = (
        _place("raw-heavy", "Raw Heavy", 0.10, "바다·해안", soft_sim=0.70),
        _place("soft-heavy", "Soft Heavy", 0.10, "역사·문화", soft_sim=1.00),
    )
    working_set = build_working_set(
        PlannerSelectionInput(
            raw_places=places,
            soft_places=soft_places,
            seeds=(),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="daytrip",
            target_count=2,
        ),
    )

    routed = route_days(
        working_set.places,
        trip_type="daytrip",
        transport_pref="car",
    )

    assert routed.days[0].anchor_place_id == "raw-heavy"


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
