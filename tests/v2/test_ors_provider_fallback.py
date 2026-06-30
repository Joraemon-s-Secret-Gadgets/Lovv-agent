from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from lovv_agent_v2.agents.planner.ors_provider import (
    OrsProviderConfig,
    OrsTravelTimeProvider,
)


def _place(place_id: str, title: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": ["바다·해안"],
        "latitude": 38.2,
        "longitude": 128.6,
    }


def test_ors_provider_snap_failure_falls_back_to_haversine(
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
                "",
                "class MatrixResult:",
                "    def __init__(self, profile, places):",
                "        self.profile = profile",
                "        self.place_ids = [place.place_id for place in places]",
                "        self.durations_sec = [[0.0 if a == b else 180.0 for b in self.place_ids] for a in self.place_ids]",
                "        self.fallback_used = True",
                "        self.source = 'ors_haversine'",
                "",
                "class OrsMatrixClient:",
                "    def __init__(self, timeout_sec=20, cache_dir=None):",
                "        self.timeout_sec = timeout_sec",
                "        self.cache_dir = cache_dir",
                "",
                "    def snap_places(self, places, profile, radius_m=300):",
                "        raise RuntimeError('snap timeout')",
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

    snapped = provider.snap_places((_place("raw-1", "해변"), _place("raw-2", "등대")), "car")
    matrix = provider.matrix_minutes(("raw-1", "raw-2"), "car")

    assert snapped.audit["snap_provider"] == "ors_external_snap_failure_fallback"
    assert [place["place_id"] for place in snapped.places] == ["raw-1", "raw-2"]
    assert matrix.audit["matrix_provider"] == "ors_external"
    assert matrix.durations[("raw-1", "raw-2")] > 0.0
