import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from scripts.orchestrator_smoke_test import ScriptedModelClient
from src.orchestrator import ArchitectureOrchestrator
from src.trace_writer import save_trace
from tests.test_orchestrator_revision import APPROVED, REQUIREMENT, initial_plan


class CollaborationTraceContractTests(unittest.TestCase):
    def test_messages_capture_hashes_latency_tokens_and_validation(self) -> None:
        client = ScriptedModelClient([
            json.dumps(initial_plan(), ensure_ascii=False),
            json.dumps(APPROVED, ensure_ascii=False),
        ])
        result = asyncio.run(ArchitectureOrchestrator(client, max_review_rounds=1).run(REQUIREMENT))

        self.assertEqual(len(result.messages), 2)
        for message in result.messages:
            self.assertRegex(message.input_summary_sha256, r"^[0-9a-f]{64}$")
            self.assertRegex(message.raw_output_sha256, r"^[0-9a-f]{64}$")
            self.assertGreaterEqual(message.duration_ms, 0)
            self.assertGreaterEqual(message.prompt_tokens, 0)
            self.assertGreaterEqual(message.completion_tokens, 0)
            self.assertEqual(message.validation_status, "valid")

    def test_invalid_attempt_is_hashed_and_marked_without_repair(self) -> None:
        client = ScriptedModelClient([
            "{invalid",
            json.dumps(initial_plan(), ensure_ascii=False),
            json.dumps(APPROVED, ensure_ascii=False),
        ])
        result = asyncio.run(
            ArchitectureOrchestrator(client, max_review_rounds=1, max_parse_retries=1).run(REQUIREMENT)
        )
        self.assertEqual(result.messages[0].raw_content, "{invalid")
        self.assertEqual(result.messages[0].validation_status, "invalid")
        self.assertIsNone(result.messages[0].parsed_content)

    def test_redacted_trace_contains_spans_not_sensitive_text(self) -> None:
        client = ScriptedModelClient([
            json.dumps(initial_plan(), ensure_ascii=False),
            json.dumps(APPROVED, ensure_ascii=False),
        ])
        result = asyncio.run(ArchitectureOrchestrator(client, max_review_rounds=1).run(REQUIREMENT))
        with tempfile.TemporaryDirectory() as directory:
            path = save_trace(result, Path(directory).resolve() / "traces")
            record = json.loads(path.read_text())

        serialized = json.dumps(record, ensure_ascii=False)
        self.assertEqual(len(record["spans"]), 2)
        self.assertNotIn(REQUIREMENT, serialized)
        self.assertNotIn(result.messages[0].raw_content, serialized)
        self.assertEqual(record["termination_reason"], "approved")


if __name__ == "__main__":
    unittest.main()
