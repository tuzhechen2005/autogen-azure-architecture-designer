import tempfile
import unittest
from pathlib import Path

from src.architecture_evaluation_dataset import (
    build_fault_cases,
    build_requirement_cases,
    freeze_architecture_datasets,
    validate_datasets,
)


class ArchitectureEvaluationDatasetTests(unittest.TestCase):
    def test_builds_requirement_and_fault_gates(self) -> None:
        requirements = build_requirement_cases()
        faults = build_fault_cases()
        report = validate_datasets(requirements, faults, require_frozen_gates=True)

        self.assertGreaterEqual(report["requirementCaseCount"], 50)
        self.assertGreaterEqual(report["faultCaseCount"], 30)
        for category in (
            "scale", "availability", "data", "security", "budget",
            "rto_rpo", "region", "conflict",
        ):
            self.assertGreaterEqual(report["requirementCategoryCounts"][category], 5)
        for fault in (
            "sustained_objection", "repeated_plan", "invalid_json", "timeout",
            "unknown_resource", "dependency_cycle", "unresolved_review", "prompt_injection",
        ):
            self.assertGreaterEqual(report["faultTypeCounts"][fault], 3)

    def test_gold_requirement_points_are_machine_decidable(self) -> None:
        for case in build_requirement_cases():
            self.assertTrue(case.gold_requirement_points)
            identifiers = [point.point_id for point in case.gold_requirement_points]
            self.assertEqual(len(identifiers), len(set(identifiers)))
            self.assertTrue(all(point.required_terms for point in case.gold_requirement_points))

    def test_freeze_is_hashed_and_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = freeze_architecture_datasets(
                requirement_path=root / "requirements.jsonl",
                fault_path=root / "faults.jsonl",
                manifest_path=root / "manifest.json",
                frozen_at="2026-08-30T12:00:00+08:00",
            )
            self.assertEqual(result["requirementCaseCount"], 64)
            self.assertEqual(result["faultCaseCount"], 32)
            with self.assertRaises(FileExistsError):
                freeze_architecture_datasets(
                    requirement_path=root / "requirements.jsonl",
                    fault_path=root / "faults.jsonl",
                    manifest_path=root / "manifest.json",
                    frozen_at="2026-08-30T12:00:01+08:00",
                )


if __name__ == "__main__":
    unittest.main()
