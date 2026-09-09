"""Frozen-final batch runner and deterministic fault injector for Task 3."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.orchestrator_smoke_test import ScriptedModelClient
from src.architecture_evaluation_dataset import (
    ArchitectureFaultCase,
    ArchitectureRequirementCase,
    RequirementPoint,
)
from src.frozen_runner import (
    FIXTURE_APPROVED,
    FaultInjectingClient,
    FixtureCollaborationClient,
    FrozenRunError,
    run_fault_cases,
    run_requirement_cases,
    score_run_directory,
    verify_sha256,
)
from src.orchestrator import ArchitectureOrchestrator
from src.prompts import PLANNER_SYSTEM_PROMPT, REVIEWER_SYSTEM_PROMPT
from tests.test_orchestrator_revision import initial_plan


def _requirement_case(index: int) -> ArchitectureRequirementCase:
    return ArchitectureRequirementCase(
        case_id=f"req_{index:03d}",
        split="frozen_test",
        language="zh",
        primary_category="scale",
        requirements="设计一个包含 API 和数据库的高可用交易系统，不执行真实部署。",
        gold_requirement_points=[
            RequirementPoint(
                category="scale", point_id="scale-01", required_terms=["api"]
            )
        ],
    )


class FixtureClientTests(unittest.TestCase):
    def test_fixture_client_reaches_approval_and_reports_role(self) -> None:
        client = FixtureCollaborationClient()
        result = asyncio.run(
            ArchitectureOrchestrator(client, max_review_rounds=3).run(
                "设计一个包含 API 和数据库的高可用交易系统，不执行真实部署。"
            )
        )
        self.assertEqual(result.status.value, "completed")
        self.assertEqual(client.calls_by_role, {"planner": 3, "reviewer": 3})
        self.assertEqual(
            FaultInjectingClient.role_of(
                [type("M", (), {"content": PLANNER_SYSTEM_PROMPT})()]
            ),
            "planner",
        )
        self.assertEqual(
            FaultInjectingClient.role_of(
                [type("M", (), {"content": REVIEWER_SYSTEM_PROMPT})()]
            ),
            "reviewer",
        )


class FaultInjectionTests(unittest.TestCase):
    def _case(
        self, fault_type: str, injection_round: int, expected: str
    ) -> ArchitectureFaultCase:
        return ArchitectureFaultCase(
            case_id=f"fault_{fault_type}_{injection_round}",
            split="fault",
            fault_type=fault_type,  # type: ignore[arg-type]
            injection_round=injection_round,
            expected_terminal=expected,
            expected_max_agent_calls=12,
        )

    def test_each_fault_type_terminates_within_bounds_and_records_outcome(self) -> None:
        cases = [
            self._case("sustained_objection", 0, "degraded"),
            self._case("invalid_json", 1, "failed"),
            self._case("timeout", 0, "timeout"),
            self._case("unknown_resource", 0, "failed"),
            self._case("dependency_cycle", 1, "failed"),
            self._case("prompt_injection", 0, "failed"),
            self._case("repeated_plan", 1, "degraded"),
            self._case("unresolved_review", 0, "degraded"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            run_dir = run_fault_cases(
                cases,
                run_id="fault-run",
                output_root=Path(directory),
                max_review_rounds=5,
                timeout_seconds_for_timeout_fault=0.2,
            )
            rows = [
                json.loads(line)
                for line in (run_dir / "fault_results.jsonl").read_text().splitlines()
            ]
        self.assertEqual(
            [row["caseId"] for row in rows], [case.case_id for case in cases]
        )
        for row in rows:
            self.assertIn(
                row["actualTerminal"], {"completed", "degraded", "timeout", "failed"}
            )
            self.assertIsInstance(row["expectedTerminal"], bool)
            self.assertLessEqual(row["agentCalls"], 12)
            self.assertTrue(row["boundedTermination"])
        by_type = {row["faultType"]: row for row in rows}
        self.assertEqual(by_type["timeout"]["actualTerminal"], "timeout")
        self.assertEqual(by_type["prompt_injection"]["actualTerminal"], "failed")
        self.assertEqual(by_type["prompt_injection"]["agentCalls"], 0)
        self.assertEqual(by_type["invalid_json"]["actualTerminal"], "failed")
        self.assertEqual(by_type["sustained_objection"]["actualTerminal"], "degraded")

    def test_fault_runner_refuses_existing_directory(self) -> None:
        cases = [self._case("prompt_injection", 0, "failed")]
        with tempfile.TemporaryDirectory() as directory:
            run_fault_cases(
                cases,
                run_id="fault-run",
                output_root=Path(directory),
                max_review_rounds=5,
            )
            with self.assertRaises(FileExistsError):
                run_fault_cases(
                    cases,
                    run_id="fault-run",
                    output_root=Path(directory),
                    max_review_rounds=5,
                )


class RequirementRunnerTests(unittest.TestCase):
    def test_requirement_run_writes_raw_trace_manifest_and_scores(self) -> None:
        cases = [_requirement_case(1), _requirement_case(2)]
        client = ScriptedModelClient(
            [
                json.dumps(initial_plan(), ensure_ascii=False),
                json.dumps(FIXTURE_APPROVED, ensure_ascii=False),
                json.dumps(initial_plan(), ensure_ascii=False),
                json.dumps(FIXTURE_APPROVED, ensure_ascii=False),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run_dir = run_requirement_cases(
                cases,
                client,
                run_id="req-run",
                output_root=root,
                max_review_rounds=2,
                model_metadata={"file": "scripted", "sha256": "0" * 64},
                manifest_extra={"dataset": {"sha256": "1" * 64}},
            )
            raw = [
                json.loads(line)
                for line in (run_dir / "raw_predictions.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["caseId"] for row in raw], ["req_001", "req_002"])
            self.assertEqual(raw[0]["status"], "completed")
            self.assertEqual(len(raw[0]["messages"]), 2)
            self.assertEqual(
                raw[0]["messages"][0]["rawOutputSha256"],
                hashlib.sha256(
                    raw[0]["messages"][0]["rawContent"].encode()
                ).hexdigest(),
            )
            self.assertTrue((run_dir / "traces" / f"{raw[0]['runId']}.json").is_file())
            manifest = json.loads((run_dir / "run_manifest.json").read_text())
            self.assertEqual(manifest["runType"], "frozen_final")
            self.assertEqual(manifest["caseCount"], 2)
            self.assertIsNotNone(manifest["finishedAtUtc"])
            metrics = score_run_directory(run_dir, cases)
            self.assertEqual(metrics["caseCount"], 2)
            self.assertEqual(metrics["structuredOutputSuccessRate"], 1.0)
            self.assertTrue((run_dir / "evaluated_cases.jsonl").is_file())
            self.assertTrue((run_dir / "metrics.json").is_file())
            with self.assertRaises(FileExistsError):
                score_run_directory(run_dir, cases)
            with self.assertRaises(FileExistsError):
                run_requirement_cases(
                    cases,
                    client,
                    run_id="req-run",
                    output_root=root,
                    max_review_rounds=2,
                    model_metadata={},
                    manifest_extra={},
                )

    def test_sha256_gate_and_duplicate_ids_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x"
            path.write_bytes(b"abc")
            self.assertEqual(
                verify_sha256(path, hashlib.sha256(b"abc").hexdigest()),
                hashlib.sha256(b"abc").hexdigest(),
            )
            with self.assertRaises(FrozenRunError):
                verify_sha256(path, "0" * 64)
            with self.assertRaises(FrozenRunError):
                run_requirement_cases(
                    [_requirement_case(1), _requirement_case(1)],
                    ScriptedModelClient(["{}"]),
                    run_id="dup",
                    output_root=Path(directory),
                    max_review_rounds=2,
                    model_metadata={},
                    manifest_extra={},
                )


if __name__ == "__main__":
    unittest.main()
