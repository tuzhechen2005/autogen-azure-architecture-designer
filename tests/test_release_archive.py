"""Regression tests for allowlisted source archive generation."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from scripts.build_release import ReleaseValidationError, build_release_archive


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ReleaseArchiveTests(unittest.TestCase):
    def test_release_builder_exists(self) -> None:
        self.assertTrue(
            (REPOSITORY_ROOT / "scripts" / "build_release.py").is_file(),
            "release archives require a tracked-file allowlist builder",
        )

    @staticmethod
    def _git(repo_root: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )

    def _initialize_repository(self, repo_root: Path) -> None:
        self._git(repo_root, "init", "-q")
        (repo_root / ".gitignore").write_text(
            ".env\n*.swp\n.venv/\ndist/\n",
            encoding="utf-8",
        )
        (repo_root / "app.py").write_text("print('safe')\n", encoding="utf-8")
        self._git(repo_root, "add", ".gitignore", "app.py")
        self._git(
            repo_root,
            "-c",
            "user.name=Archive Test",
            "-c",
            "user.email=archive@example.invalid",
            "commit",
            "-qm",
            "initial",
        )

    def test_archive_contains_only_committed_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory).resolve()
            self._initialize_repository(repo_root)
            (repo_root / ".env").write_text("SECRET=not-for-zip\n", encoding="utf-8")
            (repo_root / "notes.swp").write_text("local metadata\n", encoding="utf-8")
            (repo_root / ".venv").mkdir()
            (repo_root / ".venv" / "secret").write_text(
                "private\n",
                encoding="utf-8",
            )

            artifact = build_release_archive(repo_root)

            with zipfile.ZipFile(artifact.path) as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
            self.assertEqual(artifact.file_count, 2)
            self.assertTrue(any(name.endswith("/.gitignore") for name in names))
            self.assertTrue(any(name.endswith("/app.py") for name in names))
            self.assertFalse(any(".env" in name for name in names))
            self.assertFalse(any(name.endswith(".swp") for name in names))
            self.assertFalse(any(".venv" in name for name in names))

    def test_refuses_dirty_tracked_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory).resolve()
            self._initialize_repository(repo_root)
            (repo_root / "app.py").write_text("print('dirty')\n", encoding="utf-8")

            with self.assertRaisesRegex(ReleaseValidationError, "committed"):
                build_release_archive(repo_root)

    def test_refuses_tracked_sensitive_path_and_symlink(self) -> None:
        for unsafe_kind in ("environment", "symlink"):
            with self.subTest(unsafe_kind=unsafe_kind):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repo_root = Path(temporary_directory).resolve()
                    self._initialize_repository(repo_root)
                    if unsafe_kind == "environment":
                        (repo_root / ".env").write_text(
                            "SECRET=tracked\n",
                            encoding="utf-8",
                        )
                        self._git(repo_root, "add", "-f", ".env")
                    else:
                        (repo_root / "linked.py").symlink_to("app.py")
                        self._git(repo_root, "add", "linked.py")
                    self._git(
                        repo_root,
                        "-c",
                        "user.name=Archive Test",
                        "-c",
                        "user.email=archive@example.invalid",
                        "commit",
                        "-qm",
                        "unsafe",
                    )

                    with self.assertRaises(ReleaseValidationError):
                        build_release_archive(repo_root)


if __name__ == "__main__":
    unittest.main()
