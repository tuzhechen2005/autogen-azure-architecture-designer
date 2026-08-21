"""Security regression tests for local trace persistence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from src.trace_writer import save_trace


class FakeRunResult:
    def __init__(self, run_id: str = "a" * 32) -> None:
        self.run_id = run_id

    def model_dump(self, *, mode: str) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "request": {"requirements": "customer-secret"},
            "messages": [{"raw_content": "model-secret"}],
            "status": "completed",
        }


class SecureTraceWriterTests(unittest.TestCase):
    def test_concurrent_runs_publish_separate_complete_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory).resolve() / "traces"
            results = [FakeRunResult(f"run-{index:08d}") for index in range(12)]

            with ThreadPoolExecutor(max_workers=6) as executor:
                paths = list(
                    executor.map(
                        lambda result: save_trace(  # type: ignore[arg-type]
                            result,
                            output_directory,
                        ),
                        results,
                    )
                )

            self.assertEqual(len(set(paths)), len(results))
            self.assertEqual(
                sorted(path.name for path in output_directory.glob("*.json")),
                sorted(f"{result.run_id}.json" for result in results),
            )
            self.assertEqual(list(output_directory.glob(".tmp-*")), [])
            for path in paths:
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(record["run_id"], path.stem)

    def test_failed_write_never_publishes_partial_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory).resolve() / "traces"
            original_write = os.write
            calls = 0

            def fail_after_partial_write(file_descriptor: int, data: object) -> int:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return original_write(file_descriptor, bytes(data)[:5])
                raise OSError("simulated disk failure")

            with patch("src.trace_writer.os.write", side_effect=fail_after_partial_write):
                with self.assertRaises(OSError):
                    save_trace(FakeRunResult(), output_directory)  # type: ignore[arg-type]

            self.assertEqual(list(output_directory.iterdir()), [])

    def test_trace_permissions_are_private_and_content_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory).resolve() / "traces"
            previous_umask = os.umask(0)
            try:
                output_path = save_trace(  # type: ignore[arg-type]
                    FakeRunResult(),
                    output_directory,
                )
            finally:
                os.umask(previous_umask)

            directory_mode = stat.S_IMODE(output_directory.stat().st_mode)
            file_mode = stat.S_IMODE(output_path.stat().st_mode)
            serialized = output_path.read_text(encoding="utf-8")
            self.assertEqual(directory_mode, 0o700)
            self.assertEqual(file_mode, 0o600)
            self.assertNotIn("customer-secret", serialized)
            self.assertNotIn("model-secret", serialized)

    def test_rejects_symbolic_link_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            target = root / "attacker-controlled"
            target.mkdir()
            sentinel = target / "do-not-touch"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            output_directory = root / "traces"
            output_directory.symlink_to(target, target_is_directory=True)

            with self.assertRaises(OSError):
                save_trace(  # type: ignore[arg-type]
                    FakeRunResult(),
                    output_directory,
                )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")


if __name__ == "__main__":
    unittest.main()
