from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.route_days.place_selection import (
    PlannerSelectionInput,
    build_working_set,
)


def _place(
    place_id: str,
    title: str,
    sim: float,
    theme: str,
    *,
    subtype: str,
    subtype_code: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "assigned_theme": theme,
        "latitude": 37.0,
        "longitude": 127.0,
        "attraction_subtype_name": subtype,
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": sim,
    }
    if subtype_code is not None:
        payload["attraction_subtype_code"] = subtype_code
    return payload


def test_single_theme_working_set_caps_one_subtype_at_half_when_alternatives_exist() -> None:
    raw_places = (
        *(
            _place(
                f"beach-{index}",
                f"Beach {index}",
                0.90 - index * 0.01,
                "바다·해안",
                subtype="해수욕장",
                subtype_code="NA020700",
            )
            for index in range(4)
        ),
        _place("port-1", "Port 1", 0.70, "바다·해안", subtype="등대, 포구, 항구", subtype_code="NA020900"),
        _place("port-2", "Port 2", 0.69, "바다·해안", subtype="등대, 포구, 항구", subtype_code="NA020900"),
    )

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="2d1n",
            target_count=6,
            min_count=4,
        ),
    )

    assert len(result.places) == 5
    assert result.audit["subtype_cap_limit"] == 3
    assert result.audit["subtype_cap_relaxed"] is False
    assert result.audit["subtype_counts"] == {"NA020700": 3, "NA020900": 2}


def test_single_theme_single_subtype_pool_does_not_apply_cap() -> None:
    raw_places = tuple(
        _place(
            f"beach-{index}",
            f"Beach {index}",
            0.90 - index * 0.01,
            "바다·해안",
            subtype="해수욕장",
            subtype_code="NA020700",
        )
        for index in range(5)
    )

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="2d1n",
            target_count=6,
            min_count=4,
        ),
    )

    assert len(result.places) == 5
    assert result.audit["subtype_cap_limit"] == 6
    assert result.audit["subtype_cap_relaxed"] is False
    assert result.audit["subtype_counts"] == {"NA020700": 5}


def test_single_theme_subtype_cap_uses_attraction_subtype_code_only() -> None:
    raw_places = (
        _place("code-a-1", "Code A 1", 0.90, "바다·해안", subtype="해수욕장", subtype_code="NA020700"),
        _place("code-a-2", "Code A 2", 0.89, "바다·해안", subtype="해수욕장", subtype_code="NA020700"),
        _place("code-a-3", "Code A 3", 0.88, "바다·해안", subtype="해수욕장", subtype_code="NA020700"),
        _place("code-a-4", "Code A 4", 0.87, "바다·해안", subtype="해수욕장", subtype_code="NA020700"),
        _place("code-b-1", "Code B 1", 0.86, "바다·해안", subtype="해수욕장", subtype_code="NA020800"),
        _place("code-b-2", "Code B 2", 0.85, "바다·해안", subtype="해수욕장", subtype_code="NA020800"),
    )

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="2d1n",
            target_count=6,
            min_count=4,
        ),
    )

    assert len(result.places) == 5
    assert result.audit["subtype_cap_relaxed"] is False
    assert result.audit["subtype_counts"] == {"NA020700": 3, "NA020800": 2}


def test_multi_theme_subtype_cap_refills_each_theme_quota_from_pool() -> None:
    raw_places = (
        _place("sea-beach-1", "Sea Beach 1", 0.95, "바다·해안", subtype="해수욕장", subtype_code="NA020700"),
        _place("sea-beach-2", "Sea Beach 2", 0.94, "바다·해안", subtype="해수욕장", subtype_code="NA020700"),
        _place("sea-beach-3", "Sea Beach 3", 0.93, "바다·해안", subtype="해수욕장", subtype_code="NA020700"),
        _place("sea-port", "Sea Port", 0.82, "바다·해안", subtype="항구", subtype_code="NA020900"),
        _place("sea-cliff", "Sea Cliff", 0.81, "바다·해안", subtype="해안절경", subtype_code="NA020800"),
        _place("history-temple-1", "Temple 1", 0.92, "역사·문화", subtype="사찰", subtype_code="HS030100"),
        _place("history-temple-2", "Temple 2", 0.91, "역사·문화", subtype="사찰", subtype_code="HS030100"),
        _place("history-temple-3", "Temple 3", 0.90, "역사·문화", subtype="사찰", subtype_code="HS030100"),
        _place("history-fortress", "Fortress", 0.80, "역사·문화", subtype="성곽", subtype_code="HS010200"),
        _place("history-museum", "Museum", 0.79, "역사·문화", subtype="박물관", subtype_code="VE070100"),
    )

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=6,
            min_count=4,
        ),
    )

    selected_ids = {place.place_id for place in result.places}
    assert len(result.places) == 6
    assert selected_ids == {
        "sea-beach-1",
        "sea-port",
        "sea-cliff",
        "history-temple-1",
        "history-fortress",
        "history-museum",
    }
    assert result.audit["subtype_cap_limits"] == {"바다·해안": 1, "역사·문화": 1}
    assert result.audit["theme_counts"] == {"바다·해안": 3, "역사·문화": 3}


def test_single_theme_facet_expansion_admits_only_allowed_subtypes() -> None:
    raw_places = (
        _place("sea-1", "Sea 1", 0.92, "바다·해안", subtype="해변", subtype_code="NA020700"),
        _place("coastal-rock", "Coastal Rock", 0.90, "자연", subtype="해안절경", subtype_code="NA020800"),
        _place("inland-park", "Inland Park", 0.89, "자연", subtype="공원", subtype_code="NA040300"),
    )

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="daytrip",
            target_count=3,
            min_count=2,
        ),
    )

    selected_ids = {place.place_id for place in result.places}
    assert selected_ids == {"sea-1", "coastal-rock"}
    assert result.audit["facet_expansion_added_count"] == 1
    assert result.audit["off_theme_excluded_count"] == 1
