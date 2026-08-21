"""Security regression tests for local model path validation."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from src.config import AppConfig, ConfigurationError


class ModelPathValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.valid_model = self.root / "model.gguf"
        self.valid_model.write_bytes(b"GGUF")
        with self.valid_model.open("r+b") as handle:
            handle.truncate(1024 * 1024)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def assert_invalid(self, path: Path) -> None:
        with self.assertRaises(ConfigurationError) as context:
            AppConfig(model_path=path, model_root=self.root).validate()
        self.assertNotIn(str(path), str(context.exception))

    def test_rejects_relative_model_path(self) -> None:
        relative = Path(os.path.relpath(self.valid_model, Path.cwd()))
        self.assert_invalid(relative)

    def test_rejects_non_gguf_extension(self) -> None:
        text_file = self.root / "model.txt"
        text_file.write_bytes(self.valid_model.read_bytes())
        self.assert_invalid(text_file)

    def test_rejects_symlink_even_when_target_is_valid(self) -> None:
        link = self.root / "linked.gguf"
        link.symlink_to(self.valid_model)
        self.assert_invalid(link)

    def test_rejects_wrong_magic_and_tiny_files(self) -> None:
        wrong_magic = self.root / "wrong.gguf"
        wrong_magic.write_bytes(b"NOPE")
        with wrong_magic.open("r+b") as handle:
            handle.truncate(1024 * 1024)

        tiny = self.root / "tiny.gguf"
        tiny.write_bytes(b"GGUF")
        for path in (wrong_magic, tiny):
            with self.subTest(path=path.name):
                self.assert_invalid(path)

    def test_rejects_directory_and_missing_path(self) -> None:
        self.assert_invalid(self.root)
        self.assert_invalid(self.root / "missing.gguf")

    def test_rejects_valid_file_outside_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as other_directory:
            outside = Path(other_directory) / "outside.gguf"
            outside.write_bytes(b"GGUF")
            with outside.open("r+b") as handle:
                handle.truncate(1024 * 1024)
            self.assert_invalid(outside)

    def test_accepts_regular_gguf_file(self) -> None:
        AppConfig(model_path=self.valid_model, model_root=self.root).validate()

    def test_rejects_unbounded_inference_timeout(self) -> None:
        for timeout in (0.0, 600.01):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(
                    ConfigurationError,
                    "PHI3_INFERENCE_TIMEOUT_SECONDS",
                ):
                    AppConfig(
                        model_path=self.valid_model,
                        model_root=self.root,
                        inference_timeout_seconds=timeout,
                    ).validate()
