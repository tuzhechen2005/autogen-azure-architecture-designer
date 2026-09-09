"""Regression tests that runtime failures map to actionable guidance."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import AppConfig, ConfigurationError
from src.diagnostics import Diagnosis, diagnose
from src.local_model_client import (
    LocalModelProtocolError,
    LocalModelRuntimeConflictError,
    LocalModelTimeoutError,
)
from src.output_parser import StructuredOutputError


def _config(**overrides: object) -> AppConfig:
    defaults: dict[str, object] = {
        "model_path": Path("/tmp/model.gguf"),
        "model_root": Path("/tmp"),
        "n_ctx": 4096,
        "max_tokens": 512,
        "temperature": 0.0,
        "n_gpu_layers": -1,
    }
    defaults.update(overrides)
    return AppConfig(**defaults)  # type: ignore[arg-type]


class ModelLoadDiagnosticsTests(unittest.TestCase):
    """Each check in AppConfig.validate must produce specific guidance."""

    def _assert_specific(self, error: ConfigurationError) -> Diagnosis:
        diagnosis = diagnose(error)
        self.assertNotEqual(
            diagnosis.title,
            "本地运行失败",
            f"未被识别的配置错误，会退化为通用提示: {error}",
        )
        self.assertTrue(diagnosis.remedies, "诊断必须给出至少一条可执行建议")
        return diagnosis

    def test_relative_model_path_is_explained(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            _config(model_path=Path("models/x.gguf")).validate()
        diagnosis = self._assert_specific(ctx.exception)
        self.assertEqual(diagnosis.env_hint, "PHI3_MODEL_PATH")

    def test_wrong_extension_is_explained(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            _config(model_path=Path("/tmp/model.bin")).validate()
        self._assert_specific(ctx.exception)

    def test_missing_model_root_is_explained(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            _config(model_root=None).validate()
        diagnosis = self._assert_specific(ctx.exception)
        self.assertEqual(diagnosis.env_hint, "PHI3_MODEL_ROOT")

    def test_missing_file_is_explained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ConfigurationError) as ctx:
                _config(
                    model_path=root / "absent.gguf", model_root=root
                ).validate()
            self._assert_specific(ctx.exception)

    def test_non_gguf_content_is_explained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "fake.gguf"
            target.write_bytes(b"NOTGGUF" + b"\0" * 32)
            with self.assertRaises(ConfigurationError) as ctx:
                _config(model_path=target, model_root=root).validate()
            self._assert_specific(ctx.exception)

    def test_model_outside_trusted_root_is_explained(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            with tempfile.TemporaryDirectory() as root:
                target = Path(outside) / "model.gguf"
                with target.open("wb") as handle:
                    handle.write(b"GGUF")
                    handle.truncate(64 * 1024 * 1024 + 4)
                with self.assertRaises(ConfigurationError) as ctx:
                    _config(model_path=target, model_root=Path(root)).validate()
                self._assert_specific(ctx.exception)

    def test_invalid_context_length_is_explained(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            _config(n_ctx=16).validate()
        self._assert_specific(ctx.exception)

    def test_invalid_max_tokens_is_explained(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            _config(max_tokens=0).validate()
        self._assert_specific(ctx.exception)

    def test_invalid_temperature_is_explained(self) -> None:
        with self.assertRaises(ConfigurationError) as ctx:
            _config(temperature=5.0).validate()
        self._assert_specific(ctx.exception)


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_timeout_suggests_raising_the_deadline(self) -> None:
        diagnosis = diagnose(LocalModelTimeoutError("inference exceeded deadline"))
        self.assertEqual(diagnosis.env_hint, "PHI3_INFERENCE_TIMEOUT_SECONDS")
        self.assertTrue(diagnosis.remedies)

    def test_runtime_conflict_is_recognised(self) -> None:
        diagnosis = diagnose(LocalModelRuntimeConflictError("conflicting runtime"))
        self.assertIn("冲突", diagnosis.title)

    def test_protocol_error_is_recognised(self) -> None:
        diagnosis = diagnose(LocalModelProtocolError("images are unsupported"))
        self.assertNotEqual(diagnosis.title, "本地运行失败")

    def test_structured_output_failure_is_recognised(self) -> None:
        diagnosis = diagnose(StructuredOutputError("schema validation failed"))
        self.assertTrue(diagnosis.remedies)
        self.assertNotEqual(diagnosis.title, "本地运行失败")

    def test_unknown_error_falls_back_without_losing_detail(self) -> None:
        diagnosis = diagnose(RuntimeError("something entirely new"))
        self.assertEqual(diagnosis.title, "本地运行失败")
        self.assertTrue(diagnosis.remedies)

    def test_conflict_is_matched_before_the_generic_protocol_rule(self) -> None:
        # LocalModelRuntimeConflictError subclasses LocalModelProtocolError, so
        # rule order must keep the specific diagnosis reachable.
        conflict = diagnose(LocalModelRuntimeConflictError("x"))
        protocol = diagnose(LocalModelProtocolError("x"))
        self.assertNotEqual(conflict.title, protocol.title)


if __name__ == "__main__":
    unittest.main()
