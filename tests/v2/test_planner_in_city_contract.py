from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

from lovv_agent_v2.agents.planner.nodes import (
    assemble_itinerary_node,
    retrieve_places_node,
    route_days_node,
)
from lovv_agent_v2.agents.planner.ors_provider import OrsProviderConfig, OrsTravelTimeProvider
from lovv_agent_v2.agents.planner.context import travel_time_provider
from lovv_agent_v2.agents.planner.travel_time import (
    MatrixResponse,
    SnapResponse,
    TravelTimeProvider,
)


def _place(
    place_id: str,
    title: str,
    sim: float,
    theme: str,
    *,
    lat: float | None = 38.2,
    lon: float | None = 128.6,
    soft_sim: float | None = None,
    subtype: str = "view",
) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "assigned_theme": theme,
        "subtype": subtype,
        "latitude": lat,
        "longitude": lon,
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": soft_sim if soft_sim is not None else sim,
    }


class FakeEmbedding:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [float(len(self.queries)), 0.5]


class FakeDestinationSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search_candidates(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(
            {
                "vector": query_vector,
                "top_k": top_k,
                "city_id": city_id,
                "ddb_pk": ddb_pk,
                "theme": theme,
            },
        )
        if len(self.calls) == 1:
            return (
                _place("raw-1", "해변", 0.92, "바다·해안", subtype="beach"),
                _place("raw-2", "등대", 0.86, "바다·해안", subtype="view"),
            )
        return (
            _place("soft-1", "조용한 향교", 0.20, "역사·문화", soft_sim=0.82, subtype="history"),
        )


@dataclass(frozen=True, slots=True)
class FakePlannerTools:
    destination_search: FakeDestinationSearch
    embedding: FakeEmbedding


class FakeTravelTimeProvider(TravelTimeProvider):
    def snap_places(self, places: object, transport_pref: str) -> SnapResponse:
        del transport_pref
        source_places = cast(tuple[dict[str, object], ...], tuple(places))
        return SnapResponse(
            places=source_places,
            excluded_place_ids=("missing-coords",),
            audit={"snap_provider": "fake", "snap_profile": "driving"},
        )

    def matrix_minutes(self, place_ids: tuple[str, ...], transport_pref: str) -> MatrixResponse:
        del transport_pref
        durations: dict[tuple[str, str], float] = {}
        for first in place_ids:
            for second in place_ids:
                durations[(first, second)] = 0.0 if first == second else 12.0
        for place_id in place_ids:
            if place_id != "far-leg":
                durations[(place_id, "far-leg")] = 90.0
                durations[("far-leg", place_id)] = 90.0
        return MatrixResponse(
            durations=durations,
            audit={"matrix_provider": "fake", "duration_unit": "minutes"},
        )


def _base_state() -> dict[str, object]:
    return {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "속초 바다 역사",
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안", "역사·문화"],
                "theme_weights": {"바다·해안": 0.7, "역사·문화": 0.3},
                "transport_pref": "car",
                "soft_preference_query": "조용한 역사 산책",
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
                "alternative_city": {"city_id": "KR-GANGNEUNG", "city_name_ko": "강릉"},
                "seeds": [{"place_id": "raw-1", "theme": "바다·해안", "must_include": True}],
            },
        },
    }


def test_retrieve_places_node_runs_city_anchored_raw_and_soft_channels() -> None:
    search = FakeDestinationSearch()
    embedding = FakeEmbedding()
    state = _base_state()
    state["planner_runtime"] = FakePlannerTools(destination_search=search, embedding=embedding)

    result = retrieve_places_node(state)

    pool = cast(dict[str, object], result["planner_place_pool"])
    assert embedding.queries == ["속초 바다 역사", "조용한 역사 산책"]
    assert [call["theme"] for call in search.calls] == [None, None]
    assert [call["city_id"] for call in search.calls] == ["KR-SOKCHO", "KR-SOKCHO"]
    assert [call["ddb_pk"] for call in search.calls] == ["CITY#SOKCHO", "CITY#SOKCHO"]
    assert [place["place_id"] for place in cast(tuple[dict[str, object], ...], pool["raw_places"])] == [
        "raw-1",
        "raw-2",
    ]
    assert [place["place_id"] for place in cast(tuple[dict[str, object], ...], pool["soft_places"])] == [
        "soft-1",
    ]


def test_route_days_node_uses_snap_matrix_and_excludes_only_unroutable() -> None:
    state = _base_state()
    state["planner_runtime"] = FakePlannerTools(
        destination_search=FakeDestinationSearch(),
        embedding=FakeEmbedding(),
    )
    state["planner_travel_time_provider"] = FakeTravelTimeProvider()
    state["planner_place_pool"] = {
        "raw_places": (
            _place("raw-1", "해변", 0.92, "바다·해안", subtype="beach"),
            _place("raw-2", "등대", 0.88, "바다·해안", subtype="view"),
            _place("soft-1", "향교", 0.74, "역사·문화", subtype="history"),
            _place("missing-coords", "좌표없음", 0.70, "역사·문화", lat=None, lon=None),
            _place("far-leg", "먼 전망대", 0.68, "바다·해안"),
        ),
        "soft_places": (),
    }

    result = route_days_node(state)

    routed = cast(dict[str, object], result["planner_route"])
    audit = cast(dict[str, object], routed["audit"])
    assert audit["duration_unit"] == "minutes"
    assert audit["matrix_provider"] == "fake"
    assert "missing-coords" in cast(tuple[str, ...], audit["unroutable_place_ids"])
    assert "far-leg" in cast(tuple[str, ...], audit["trimmed_place_ids"])


def test_assemble_itinerary_node_returns_structured_audit_and_thin_city_notice() -> None:
    state = _base_state()
    state["planner_route"] = {
        "days": (
            {
                "day": 1,
                "anchor_place_id": "raw-1",
                "anchor_type": "seed",
                "places": (
                    {
                        "place": _place("raw-1", "해변", 0.92, "바다·해안"),
                        "move_min_from_prev": 0,
                    },
                ),
                "day_travel_min": 0,
            },
        ),
        "reserve": (),
        "audit": {"duration_unit": "minutes", "trimmed_place_ids": ()},
    }
    state["planner_selection"] = {"audit": {"target_count": 8, "selected_count": 1}}

    result = assemble_itinerary_node(state)

    output = cast(dict[str, object], cast(dict[str, object], result["planner"])["planner_output"])
    validation = cast(dict[str, object], output["validation_result"])
    structure = cast(dict[str, object], validation["itinerary_structure"])
    assert validation["planner_status_gate"] == "insufficient_candidates"
    assert validation["alternative_city_recommended"] == "KR-GANGNEUNG"
    assert structure["days"]
    assert "planner_audit" in validation


def test_assemble_itinerary_node_preserves_public_grounding_fields() -> None:
    state = _base_state()
    state["planner_route"] = {
        "days": (
            {
                "day": 1,
                "anchor_place_id": "raw-1",
                "anchor_type": "seed",
                "places": (
                    {
                        "place": {
                            **_place("raw-1", "해변", 0.92, "바다·해안"),
                            "city_id": "KR-SOKCHO",
                            "city_name_ko": "속초",
                            "ddb_pk": "CITY#SOKCHO",
                            "ddb_sk": "PLACE#RAW-1",
                            "source": "s3_vector",
                        },
                        "move_min_from_prev": 0,
                    },
                ),
                "day_travel_min": 0,
            },
        ),
        "reserve": (),
        "audit": {"duration_unit": "minutes", "trimmed_place_ids": ()},
    }
    state["planner_selection"] = {"audit": {"target_count": 4, "selected_count": 1}}

    result = assemble_itinerary_node(state)

    output = cast(dict[str, object], cast(dict[str, object], result["planner"])["planner_output"])
    item = cast(tuple[dict[str, object], ...], output["itinerary"])[0]
    assert item["item_type"] == "attraction"
    assert item["city_id"] == "KR-SOKCHO"
    assert item["city_name_ko"] == "속초"
    assert item["theme_tags"] == ("바다·해안",)
    assert item["ddb_pk"] == "CITY#SOKCHO"
    assert item["ddb_sk"] == "PLACE#RAW-1"


def test_ors_provider_loads_external_snap_matrix_module(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module_file = tmp_path / "ors_matrix.py"
    module_file.write_text(
        "\n".join(
            (
                "class PlaceCandidate:",
                "    def __init__(self, place_id, title, lat, lon, theme_tags=None, subtype=None, source_tier=None):",
                "        self.place_id = place_id",
                "        self.title = title",
                "        self.lat = lat",
                "        self.lon = lon",
                "        self.theme_tags = theme_tags",
                "        self.subtype = subtype",
                "        self.source_tier = source_tier",
                "",
                "class SnapResult:",
                "    def __init__(self, profile, original_places, snapped_places):",
                "        self.profile = profile",
                "        self.original_places = original_places",
                "        self.snapped_places = snapped_places",
                "        self.snapped_distances_m = [3.5 for _ in original_places]",
                "        self.road_names = ['road' for _ in original_places]",
                "        self.snapped = [True for _ in original_places]",
                "        self.fallback_used = False",
                "",
                "class MatrixResult:",
                "    def __init__(self, profile, places):",
                "        self.profile = profile",
                "        self.place_ids = [place.place_id for place in places]",
                "        self.durations_sec = [[0.0 if a == b else 120.0 for b in self.place_ids] for a in self.place_ids]",
                "        self.fallback_used = False",
                "        self.source = 'ors'",
                "",
                "class OrsMatrixClient:",
                "    def __init__(self, timeout_sec=20, cache_dir=None):",
                "        self.timeout_sec = timeout_sec",
                "        self.cache_dir = cache_dir",
                "",
                "    def snap_places(self, places, profile, radius_m=300):",
                "        snapped = [PlaceCandidate(place.place_id, place.title, place.lat + 0.01, place.lon + 0.01) for place in places]",
                "        return SnapResult(profile, places, snapped)",
                "",
                "    def get_matrix(self, places, profile, use_cache=True, allow_fallback=True):",
                "        return MatrixResult(profile, places)",
                "",
            ),
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORS_API_KEY", "fake")
    provider = OrsTravelTimeProvider(
        OrsProviderConfig(module_file=module_file, cache_dir=None, load_env_local=False),
    )

    snapped = provider.snap_places(
        (_place("raw-1", "해변", 0.92, "바다·해안"), _place("raw-2", "등대", 0.88, "바다·해안")),
        "walk",
    )
    matrix = provider.matrix_minutes(("raw-1", "raw-2"), "walk")

    assert snapped.audit["snap_provider"] == "ors_external"
    assert snapped.places[0]["latitude"] == 38.21
    assert matrix.audit["matrix_provider"] == "ors_external"
    assert matrix.durations[("raw-1", "raw-2")] == 2.0

    monkeypatch.setenv("LOVV_PLANNER_TRAVEL_TIME_PROVIDER", "ors")
    monkeypatch.setenv("LOVV_ORS_CODE_DIR", str(tmp_path))
    configured_provider = travel_time_provider({})

    assert isinstance(configured_provider, OrsTravelTimeProvider)
