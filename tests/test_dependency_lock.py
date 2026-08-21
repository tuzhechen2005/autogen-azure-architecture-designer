"""Regression tests for reproducible Python dependency installation."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class DependencyLockTests(unittest.TestCase):
    def test_complete_lock_has_exact_versions_and_hashes(self) -> None:
        lock_path = REPOSITORY_ROOT / "requirements.lock"
        self.assertTrue(lock_path.is_file(), "requirements.lock is required")
        content = lock_path.read_text(encoding="utf-8")
        logical_lines = re.sub(r"\\\n\s+", " ", content).splitlines()
        requirement_lines = [
            line.strip()
            for line in logical_lines
            if line.strip() and not line.lstrip().startswith(("#", "--"))
        ]

        self.assertGreater(len(requirement_lines), 20)
        for line in requirement_lines:
            with self.subTest(line=line[:80]):
                self.assertIn("==", line)
                self.assertRegex(line, r"--hash=sha256:[0-9a-f]{64}")

        normalized = content.casefold().replace("_", "-")
        for package in (
            "autogen-agentchat",
            "autogen-core",
            "llama-cpp-python",
            "streamlit",
            "pydantic",
            "numpy",
            "protobuf",
            "pyarrow",
            "requests",
            "tornado",
            "pytest",
        ):
            with self.subTest(package=package):
                self.assertIn(f"{package}==", normalized)

    def test_metal_build_recipe_is_documented(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("-DGGML_METAL=on", readme)
        self.assertIn("--no-binary=llama-cpp-python", readme)


if __name__ == "__main__":
    unittest.main()
