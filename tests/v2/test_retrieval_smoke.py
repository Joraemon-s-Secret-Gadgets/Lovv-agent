from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
import unittest


def _load_retrieval_smoke() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "retrieval_smoke.py"
    spec = importlib.util.spec_from_file_location("retrieval_smoke", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetrievalSmokeTest(unittest.TestCase):
    def test_v2_index_is_default_for_retrieval_smoke(self) -> None:
        smoke = _load_retrieval_smoke()

        self.assertEqual(smoke.VECTOR_INDEX, "kr-tour-domain-v2")


if __name__ == "__main__":
    unittest.main()
