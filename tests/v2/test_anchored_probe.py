from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
import unittest


def _load_anchored_probe() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "anchored_probe.py"
    spec = importlib.util.spec_from_file_location("anchored_probe", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingS3Vectors:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def list_vectors(self, **request: Any) -> dict[str, Any]:
        raise AssertionError(f"list_vectors should not be used: {request}")

    def query_vectors(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "vectors": [
                {
                    "key": "attraction#1#0",
                    "distance": 0.1,
                    "metadata": {
                        "entity_type": "attraction",
                        "place_id": "attraction#1",
                        "title": "안동 장소",
                        "ddb_pk": "CITY#ANDONG",
                        "city_id": "KR-47-170",
                        "theme_tags": ["history"],
                    },
                },
                {
                    "key": "attraction#2#0",
                    "distance": 0.2,
                    "metadata": {
                        "entity_type": "attraction",
                        "place_id": "attraction#2",
                        "title": "다른 도시 장소",
                        "ddb_pk": "CITY#BUSAN",
                        "city_id": "KR-26-110",
                        "theme_tags": ["history"],
                    },
                },
            ],
        }


class AnchoredProbeTest(unittest.TestCase):
    def test_city_id_of_anchor_resolves_selected_ddb_pk_from_v2_metadata(self) -> None:
        probe = _load_anchored_probe()

        city_id = probe.city_id_of_anchor(
            "CITY#ANDONG",
            {"CITY#ANDONG": "KR-47-170"},
        )

        self.assertEqual(city_id, "KR-47-170")

    def test_query_anchored_filters_directly_on_city_id(self) -> None:
        probe = _load_anchored_probe()
        s3vectors = RecordingS3Vectors()

        candidates = probe.query_anchored(s3vectors, [0.1, 0.2], "KR-47-170", 20)

        self.assertEqual(len(s3vectors.requests), 1)
        self.assertEqual(
            s3vectors.requests[0]["filter"],
            {
                "$and": [
                    {"entity_type": {"$eq": "attraction"}},
                    {"city_id": {"$eq": "KR-47-170"}},
                ],
            },
        )
        self.assertEqual([candidate["place_id"] for candidate in candidates], ["attraction#1"])

    def test_v2_index_is_default_for_anchored_probe(self) -> None:
        probe = _load_anchored_probe()

        self.assertEqual(probe.VECTOR_INDEX, "kr-tour-domain-v2")


if __name__ == "__main__":
    unittest.main()
