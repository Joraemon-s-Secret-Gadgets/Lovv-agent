from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "lovv_agent"
RUNTIME_ROOT = ROOT / "app" / "LovvAgentV1" / "lovv_agent"
PATTERNS = ("**/*.py", "prompts/*.md")


def _tracked_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for pattern in PATTERNS:
        for path in root.glob(pattern):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            files[path.relative_to(root).as_posix()] = path
    return files


class RuntimeParityTest(unittest.TestCase):
    def test_source_and_agentcore_runtime_copy_match(self) -> None:
        source_files = _tracked_files(SOURCE_ROOT)
        runtime_files = _tracked_files(RUNTIME_ROOT)

        missing_from_runtime = sorted(set(source_files) - set(runtime_files))
        extra_in_runtime = sorted(set(runtime_files) - set(source_files))
        mismatched = sorted(
            path
            for path in set(source_files) & set(runtime_files)
            if source_files[path].read_bytes() != runtime_files[path].read_bytes()
        )

        self.assertEqual(missing_from_runtime, [], "missing runtime files")
        self.assertEqual(extra_in_runtime, [], "extra runtime files")
        self.assertEqual(mismatched, [], "mismatched runtime files")


if __name__ == "__main__":
    unittest.main()
