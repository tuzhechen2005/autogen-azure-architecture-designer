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
        self.assertIn("packaging/build_llama_cpp_python.sh", readme)
        self.assertIn("--require-hashes", readme)

    def test_vulnerable_diskcache_is_not_installable(self) -> None:
        """`diskcache` must not reach the installed environment.

        Upstream llama-cpp-python hard-requires it, but its pickle-backed
        persistence is affected by CVE-2025-69872 and no fixed release exists.
        The build applies a local patch that drops the dependency, so the lock
        must not carry it either.
        """

        lock = (REPOSITORY_ROOT / "requirements.lock").read_text(encoding="utf-8")
        requirement_lines = [
            line.strip()
            for line in lock.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "--"))
        ]
        for line in requirement_lines:
            with self.subTest(line=line[:80]):
                self.assertNotRegex(line.casefold().replace("_", "-"), r"^diskcache==")

    def test_diskcache_removal_patch_is_present_and_pinned(self) -> None:
        patch_path = (
            REPOSITORY_ROOT
            / "packaging"
            / "patches"
            / "llama-cpp-python-0.3.35-remove-diskcache.patch"
        )
        self.assertTrue(patch_path.is_file(), "the diskcache removal patch is required")
        patch_text = patch_path.read_text(encoding="utf-8")
        # The patch must drop the dependency declaration and the pickle cache.
        self.assertIn('-    "diskcache>=5.6.1",', patch_text)
        self.assertIn("-import diskcache", patch_text)

        script_path = REPOSITORY_ROOT / "packaging" / "build_llama_cpp_python.sh"
        self.assertTrue(script_path.is_file(), "the build script is required")
        script = script_path.read_text(encoding="utf-8")

        # Both the upstream sdist and the patch must be hash-pinned, and the
        # sdist hash must match the one the lock file pins.
        import hashlib
        import re

        digest = hashlib.sha256(patch_path.read_bytes()).hexdigest()
        self.assertIn(digest, script, "build script must pin the patch SHA-256")

        lock = (REPOSITORY_ROOT / "requirements.lock").read_text(encoding="utf-8")
        sdist_hash = re.search(r'SDIST_SHA256="([0-9a-f]{64})"', script)
        self.assertIsNotNone(sdist_hash, "build script must pin the sdist SHA-256")
        self.assertIn(sdist_hash.group(1), lock)


if __name__ == "__main__":
    unittest.main()
