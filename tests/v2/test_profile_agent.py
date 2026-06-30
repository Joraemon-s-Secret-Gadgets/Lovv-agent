from __future__ import annotations

from lovv_agent_v2.agents.profile.node import profile_node
from lovv_agent_v2.models.profile import LovvUserProfile, build_profile_theme_weights
from lovv_agent_v2.models.schemas import CitySelectInput


def _candidate_input() -> dict[str, object]:
    return {
        "country": "KR",
        "travel_month": 9,
        "travel_year": 2026,
        "trip_type": "3d2n",
        "active_required_themes": ["바다·해안", "자연·트레킹"],
        "include_festivals": False,
        "cleaned_raw_query": "숲길과 바다를 함께 보고 싶어요.",
        "soft_preference_query": "",
        "congestion_pref": "neutral",
        "transport_pref": "unknown",
        "destination_id": None,
        "user_location": None,
        "execution_mode": "city_discovery",
        "unsupported_conditions": [],
    }


def test_build_profile_theme_weights_uses_v2_22_activation_gate() -> None:
    cold = LovvUserProfile(
        saved_trip_count=2,
        saved_theme_counts={"sea_coast": 2},
    )
    active = LovvUserProfile(
        saved_trip_count=3,
        saved_theme_counts={"sea_coast": 3},
    )

    assert build_profile_theme_weights(cold, ["바다·해안", "자연·트레킹"]).active is False
    assert build_profile_theme_weights(active, ["바다·해안", "자연·트레킹"]).theme_weights == {
        "바다·해안": 1.3,
        "자연·트레킹": 0.8,
    }


def test_profile_node_enriches_intent_candidate_input_for_city_select() -> None:
    state = {
        "intent": {"city_select_input": _candidate_input(), "raw": "preserved"},
        "profile": {
            "lovv_user_profile": {
                "saved_trip_count": 5,
                "saved_theme_counts": {"sea_coast": 5},
            },
        },
    }

    result = profile_node(state)

    enriched = result["intent"]["city_select_input"]
    assert result["intent"]["raw"] == "preserved"
    assert enriched["theme_weights"] == {"바다·해안": 1.3, "자연·트레킹": 0.8}
    assert result["profile"]["effective_theme_weights"] == {
        "바다·해안": 1.3,
        "자연·트레킹": 0.8,
    }
    assert result["profile"]["audit"]["profile_active"] is True
    CitySelectInput.from_mapping(enriched)


def test_profile_node_leaves_city_select_input_unweighted_without_profile() -> None:
    result = profile_node({"intent": {"city_select_input": _candidate_input()}})

    city_input = result["intent"]["city_select_input"]
    assert "theme_weights" not in city_input
    assert result["profile"]["effective_theme_weights"] is None
    assert result["profile"]["audit"]["profile_active"] is False
    CitySelectInput.from_mapping(city_input)


def test_profile_node_accepts_db_like_profile_record() -> None:
    result = profile_node(
        {
            "intent": {"city_select_input": _candidate_input()},
            "profile": {
                "profile_record": {
                    "actor_id": "mock://profile/P_sea",
                    "profile_status": "found",
                    "lovv_user_profile": {
                        "saved_trip_count": 3,
                        "saved_theme_counts": {"sea_coast": 3},
                    },
                },
            },
        },
    )

    assert result["intent"]["city_select_input"]["theme_weights"] == {
        "바다·해안": 1.3,
        "자연·트레킹": 0.8,
    }
