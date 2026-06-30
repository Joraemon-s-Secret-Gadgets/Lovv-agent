from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
import unittest


def _load_offline_rescore() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "offline_rescore.py"
    spec = importlib.util.spec_from_file_location("offline_rescore", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineRescoreTest(unittest.TestCase):
    def test_selected_city_map_contains_only_selected_city_pks(self) -> None:
        rescore = _load_offline_rescore()

        selected = rescore.selected_city_map(
            [
                {
                    "case_id": "case-a",
                    "selected": {"ddb_pk": "CITY#ANDONG"},
                },
                {
                    "case_id": "case-b",
                    "selected": None,
                },
            ],
        )

        self.assertEqual(selected, {"case-a": "CITY#ANDONG"})


if __name__ == "__main__":
    unittest.main()
