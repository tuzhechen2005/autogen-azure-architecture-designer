"""Regression tests for structured run diagnostics."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.output_parser import StructuredOutputError
from src.run_log import (
    LOGGER_NAME,
    _MAX_EXCERPT_CHARS,
    log_attempt_failure,
    log_run_failure,
    summarize_failures,
)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class RunLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = _Capture()
        self.logger = logging.getLogger(LOGGER_NAME)
        self.logger.addHandler(self.handler)
        self.addCleanup(self.logger.removeHandler, self.handler)

    def _record_failure(self, raw_output: str = "{broken") -> object:
        return log_attempt_failure(
            run_id="run-1",
            role="planner",
            phase="revision",
            review_round=2,
            attempt=1,
            max_attempts=2,
            error=StructuredOutputError("schema validation failed"),
            raw_output=raw_output,
        )

    def test_failure_record_captures_actionable_context(self) -> None:
        record = self._record_failure()

        self.assertEqual(record.run_id, "run-1")
        self.assertEqual(record.role, "planner")
        self.assertEqual(record.phase, "revision")
        self.assertEqual(record.review_round, 2)
        self.assertEqual(record.attempt, 1)
        self.assertEqual(record.max_attempts, 2)
        self.assertEqual(record.error_type, "StructuredOutputError")

    def test_long_model_output_is_never_stored_verbatim(self) -> None:
        raw = "A" * 10_000
        record = self._record_failure(raw)

        self.assertEqual(record.raw_output_chars, 10_000)
        self.assertLessEqual(len(record.raw_output_excerpt), _MAX_EXCERPT_CHARS + 1)
        self.assertNotIn(raw, record.as_json())

    def test_excerpt_is_single_line(self) -> None:
        record = self._record_failure("line one\nline two\r\nline three")

        self.assertNotIn("\n", record.raw_output_excerpt)
        self.assertNotIn("\r", record.raw_output_excerpt)

    def test_record_serializes_as_json(self) -> None:
        record = self._record_failure()
        payload = json.loads(record.as_json())

        self.assertEqual(payload["run_id"], "run-1")
        self.assertIn("recorded_at", payload)

    def test_attempt_failure_is_logged_at_warning(self) -> None:
        self._record_failure()

        self.assertEqual(len(self.handler.records), 1)
        self.assertEqual(self.handler.records[0].levelno, logging.WARNING)

    def test_run_failure_is_logged_at_error(self) -> None:
        log_run_failure(
            run_id="run-2",
            error=RuntimeError("boom"),
            review_rounds_completed=1,
        )

        self.assertEqual(len(self.handler.records), 1)
        self.assertEqual(self.handler.records[0].levelno, logging.ERROR)
        self.assertIn("run-2", self.handler.records[0].getMessage())

    def test_summary_groups_repeated_reasons(self) -> None:
        failures = [self._record_failure(), self._record_failure()]
        summary = summarize_failures(failures)  # type: ignore[arg-type]

        self.assertEqual(summary["total_failed_attempts"], 2)
        self.assertEqual(summary["roles"], ["planner"])
        self.assertEqual(summary["reasons"]["schema validation failed"], 2)


if __name__ == "__main__":
    unittest.main()
