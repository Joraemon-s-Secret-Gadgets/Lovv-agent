from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_results_module() -> ModuleType:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "agentv2_intent_results.py"
    spec = importlib.util.spec_from_file_location("agentv2_intent_results", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agentv2_intent_results"] = module
    spec.loader.exec_module(module)
    return module


def test_write_report_and_refresh_index_create_agentv2_intent_artifacts(tmp_path: Path) -> None:
    results = _load_results_module()
    result_root = tmp_path / "agentv2_intent"
    result_dir = result_root / "20260702T060000Z"
    result_dir.mkdir(parents=True)
    run = results.TestRun(
        name="Intent Playground pytest",
        command=("python", "-m", "pytest", "intent_playground/test_run.py", "-q"),
        log_name="pytest_playground.log",
        return_code=0,
        stdout="............. [100%]\n13 passed in 7.26s\n",
        stderr="",
    )

    results.write_report(result_dir, (run,), scope="V2 intent prompt runtime")
    results.refresh_result_index(result_root)

    report = (result_dir / "report.md").read_text(encoding="utf-8")
    readme = (result_root / "README.md").read_text(encoding="utf-8")
    assert "V2 intent prompt runtime" in report
    assert "13 passed in 7.26s" in report
    assert "20260702T060000Z" in readme
    assert "./20260702T060000Z/report.md" in readme
