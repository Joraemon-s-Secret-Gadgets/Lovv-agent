from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_runner_module() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "run_generation_to_planner_smoke.py"
    spec = importlib.util.spec_from_file_location("run_generation_to_planner_smoke", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_initial_state_wraps_generation_intent_output() -> None:
    runner = _load_runner_module()
    state = runner.build_initial_state(
        {
            "id": "case-1",
            "intent_output": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안"],
                "include_festivals": False,
                "cleaned_raw_query": "조용한 바다",
                "congestion_pref": "quiet",
                "transport_pref": "walk",
                "destination_id": None,
                "user_location": None,
            },
        },
    )

    assert state["request"]["request_id"] == "case-1"
    assert state["request"]["themes"] == ("바다·해안",)
    assert state["request"]["congestion_pref"] == "quiet"
    assert state["request"]["transport_pref"] == "walk"
    assert state["intent"]["intent_output"]["cleaned_raw_query"] == "조용한 바다"


def test_build_initial_state_attaches_itinerary_explanation_runtime() -> None:
    runner = _load_runner_module()
    runtime = object()

    state = runner.build_initial_state(
        {
            "id": "case-1",
            "intent_output": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안"],
                "include_festivals": False,
                "cleaned_raw_query": "조용한 바다",
                "destination_id": None,
                "user_location": None,
            },
        },
        itinerary_explanation_runtime=runtime,
    )

    assert state["itinerary_explanation_runtime"] is runtime
