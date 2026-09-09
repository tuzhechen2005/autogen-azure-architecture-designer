from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.orchestrator_smoke_test import ScriptedModelClient
from src.orchestrator import ArchitectureOrchestrator
from src.phase7_evidence import (
    build_loop_fault_case,
    build_shared_manifest_extension,
    build_task3_trace_events,
    redact_evidence,
)
from src.trace_writer import save_trace
from tests.test_orchestrator_revision import (
    APPROVED,
    REQUIREMENT,
    REVIEW_REQUIRED,
    initial_plan,
)


ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = ROOT.parent.parent / "微软" / "微软task1 & 2"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from evaluation.contract_validator import (  # noqa: E402
    load_canary_registry,
    validate_fault_case,
    validate_trace_event,
)


class Phase7EvidenceTests(unittest.TestCase):
    def _completed_result(self):  # type: ignore[no-untyped-def]
        client = ScriptedModelClient(
            [
                json.dumps(initial_plan(), ensure_ascii=False),
                json.dumps(APPROVED, ensure_ascii=False),
            ]
        )
        return asyncio.run(
            ArchitectureOrchestrator(client, max_review_rounds=1).run(REQUIREMENT)
        )

    def test_completed_collaboration_maps_rounds_and_terminal_trace(self) -> None:
        result = self._completed_result()
        events = build_task3_trace_events(
            result,
            trace_id="11111111-1111-4111-8111-111111111111",
            model="fixture-local-model",
            prompt_version="task3-collaboration-v1",
        )
        self.assertEqual(
            [event["step"] for event in events],
            ["planning", "review", "termination"],
        )
        self.assertEqual(events[-1]["termination"]["state"], "completed")
        self.assertEqual(events[-1]["termination"]["reason"], "approved")
        for event in events:
            validate_trace_event(event)
            self.assertEqual(event["run_id"], result.run_id)

    def test_invalid_json_retry_is_classified_as_parse_not_schema(self) -> None:
        client = ScriptedModelClient(
            [
                "{invalid",
                json.dumps(initial_plan(), ensure_ascii=False),
                json.dumps(APPROVED, ensure_ascii=False),
            ]
        )
        result = asyncio.run(
            ArchitectureOrchestrator(
                client,
                max_review_rounds=1,
                max_parse_retries=1,
            ).run(REQUIREMENT)
        )
        self.assertEqual(result.messages[0].validation_error_category, "parse")

        events = build_task3_trace_events(
            result,
            trace_id="33333333-3333-4333-8333-333333333333",
            model="fixture-local-model",
            prompt_version="task3-collaboration-v1",
        )
        self.assertEqual(events[0]["validation"]["error_category"], "parse")
        self.assertEqual(events[0]["retry"]["decision"], "retry")

        with tempfile.TemporaryDirectory() as directory:
            path = save_trace(result, Path(directory).resolve() / "traces")
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["spans"][0]["validation_error_category"], "parse")

    def test_invalid_request_terminal_is_classified_as_input(self) -> None:
        client = ScriptedModelClient([])
        result = asyncio.run(ArchitectureOrchestrator(client).run("short"))
        events = build_task3_trace_events(
            result,
            trace_id="44444444-4444-4444-8444-444444444444",
            model="fixture-local-model",
            prompt_version="task3-collaboration-v1",
        )
        terminal = events[-1]
        self.assertEqual(terminal["termination"]["state"], "failed")
        self.assertEqual(terminal["validation"]["error_category"], "input")
        self.assertEqual(terminal["retry"]["decision"], "exhausted")

    def test_invalid_revision_and_failed_terminal_are_classified_as_state(self) -> None:
        revised = deepcopy(initial_plan())
        revised["revision"] = 2
        client = ScriptedModelClient(
            [
                json.dumps(initial_plan(), ensure_ascii=False),
                json.dumps(REVIEW_REQUIRED, ensure_ascii=False),
                json.dumps(revised, ensure_ascii=False),
            ]
        )
        result = asyncio.run(
            ArchitectureOrchestrator(
                client,
                max_review_rounds=2,
                max_parse_retries=0,
            ).run(REQUIREMENT)
        )
        self.assertEqual(result.messages[-1].validation_error_category, "state")

        events = build_task3_trace_events(
            result,
            trace_id="55555555-5555-4555-8555-555555555555",
            model="fixture-local-model",
            prompt_version="task3-collaboration-v1",
        )
        self.assertEqual(events[-2]["validation"]["error_category"], "state")
        self.assertEqual(events[-1]["validation"]["error_category"], "state")

    def test_repeated_review_loop_maps_to_degraded_state_terminal(self) -> None:
        revised = deepcopy(initial_plan())
        revised["revision"] = 2
        revised["resources"][0]["high_availability"] = ["两个实例"]
        client = ScriptedModelClient(
            [
                json.dumps(initial_plan(), ensure_ascii=False),
                json.dumps(REVIEW_REQUIRED, ensure_ascii=False),
                json.dumps(revised, ensure_ascii=False),
                json.dumps(REVIEW_REQUIRED, ensure_ascii=False),
            ]
        )
        result = asyncio.run(
            ArchitectureOrchestrator(client, max_review_rounds=3).run(REQUIREMENT)
        )
        events = build_task3_trace_events(
            result,
            trace_id="22222222-2222-4222-8222-222222222222",
            model="fixture-local-model",
            prompt_version="task3-collaboration-v1",
        )
        terminal = events[-1]
        self.assertEqual(terminal["step"], "termination")
        self.assertEqual(terminal["validation"]["error_category"], "state")
        self.assertEqual(terminal["termination"]["state"], "degraded")
        self.assertEqual(terminal["termination"]["reason"], "no_progress")
        self.assertEqual(result.review_rounds_completed, 2)
        validate_trace_event(terminal)

        with tempfile.TemporaryDirectory() as directory:
            path = save_trace(result, Path(directory).resolve() / "traces")
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["shared_contract"]["contract_version"], "phase7-v1")
        stored_terminal = record["shared_trace"][-1]
        self.assertEqual(stored_terminal["trace_id"], record["trace_id"])
        for field in ("run_id", "step", "validation", "termination"):
            self.assertEqual(stored_terminal[field], terminal[field])
        self.assertNotIn("description", record["review_resolutions"][0])

    def test_loop_fault_case_and_manifest_use_shared_machine_contracts(self) -> None:
        fault = build_loop_fault_case(timeout_ms=5000)
        validate_fault_case(fault)
        self.assertEqual(fault["expected_terminal"], "degraded")
        self.assertEqual(fault["expected_error_category"], "state")

        extension = build_shared_manifest_extension()
        self.assertEqual(extension["contract_version"], "phase7-v1")
        for field in (
            "trace_schema_sha256",
            "error_taxonomy_sha256",
            "security_canaries_sha256",
            "state_rules_sha256",
        ):
            self.assertRegex(extension[field], r"^[0-9a-f]{64}$")

    def test_all_registered_canaries_are_removed_from_trace_metadata(self) -> None:
        registry = load_canary_registry(
            SHARED_ROOT / "evaluation" / "contracts" / "security_canaries.yaml"
        )
        canaries = list(registry["canaries"].values())
        rendered = json.dumps(redact_evidence({"error": " | ".join(canaries)}))
        for canary in canaries:
            self.assertNotIn(canary, rendered)

        client = ScriptedModelClient(
            [
                json.dumps(initial_plan(), ensure_ascii=False),
                json.dumps(APPROVED, ensure_ascii=False),
            ]
        )
        result = asyncio.run(
            ArchitectureOrchestrator(client, max_review_rounds=1).run(
                "设计一个本地架构；安全测试标记：" + " | ".join(canaries)
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = save_trace(
                result,
                Path(directory).resolve() / "traces",
                include_sensitive_content=True,
            )
            stored = path.read_text(encoding="utf-8")
        for canary in canaries:
            self.assertNotIn(canary, stored)
        self.assertIn("[REDACTED]", stored)


if __name__ == "__main__":
    unittest.main()
