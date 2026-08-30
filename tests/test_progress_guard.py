import asyncio
import json
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from scripts.orchestrator_smoke_test import ScriptedModelClient
from src.orchestrator import ArchitectureOrchestrator
from src.progress_guard import ProgressGuard, resolve_review_changes
from src.schemas import ArchitecturePlan, ArchitectureReview, RunStatus, TerminationReason
from tests.test_orchestrator_revision import APPROVED, REQUIREMENT, REVIEW_REQUIRED, initial_plan


class ProgressGuardTests(unittest.TestCase):
    def test_plan_hash_ignores_revision_but_detects_substantive_change(self) -> None:
        first = ArchitecturePlan.model_validate(initial_plan())
        same = deepcopy(initial_plan())
        same["revision"] = 2
        changed = deepcopy(same)
        changed["resources"][0]["high_availability"] = ["两个实例"]
        guard = ProgressGuard()

        self.assertTrue(guard.observe_plan(first))
        self.assertFalse(guard.observe_plan(ArchitecturePlan.model_validate(same)))
        self.assertTrue(guard.observe_plan(ArchitecturePlan.model_validate(changed)))

    def test_review_resolution_maps_each_required_change(self) -> None:
        plan = deepcopy(initial_plan())
        plan["resources"][0]["high_availability"] = ["两个实例"]
        resolutions = resolve_review_changes(
            ArchitectureReview.model_validate_json(json.dumps(REVIEW_REQUIRED)),
            ArchitecturePlan.model_validate(plan),
        )
        self.assertEqual(len(resolutions), 1)
        self.assertEqual(resolutions[0].status, "implemented")
        self.assertEqual(resolutions[0].required_change_index, 0)

    def test_max_rounds_is_explicit_degradation(self) -> None:
        client = ScriptedModelClient([
            json.dumps(initial_plan(), ensure_ascii=False),
            json.dumps(REVIEW_REQUIRED, ensure_ascii=False),
        ])
        result = asyncio.run(
            ArchitectureOrchestrator(client, max_review_rounds=1).run(REQUIREMENT)
        )
        self.assertEqual(result.status, RunStatus.DEGRADED)
        self.assertEqual(result.termination_reason, TerminationReason.MAX_REVIEW_ROUNDS)
        self.assertEqual(result.review_resolutions[0].status, "unresolved")

    def test_repeated_review_findings_terminate_as_no_progress(self) -> None:
        revised = deepcopy(initial_plan())
        revised["revision"] = 2
        revised["resources"][0]["high_availability"] = ["两个实例"]
        client = ScriptedModelClient([
            json.dumps(initial_plan(), ensure_ascii=False),
            json.dumps(REVIEW_REQUIRED, ensure_ascii=False),
            json.dumps(revised, ensure_ascii=False),
            json.dumps(REVIEW_REQUIRED, ensure_ascii=False),
            json.dumps(APPROVED, ensure_ascii=False),
        ])
        result = asyncio.run(
            ArchitectureOrchestrator(client, max_review_rounds=3).run(REQUIREMENT)
        )
        self.assertEqual(result.status, RunStatus.DEGRADED)
        self.assertEqual(result.termination_reason, TerminationReason.NO_PROGRESS)
        self.assertEqual(len(client.responses), 1)

    def test_timeout_has_distinct_terminal_state(self) -> None:
        orchestrator = ArchitectureOrchestrator(ScriptedModelClient(["unused"]))
        with patch.object(
            orchestrator,
            "_run_structured_agent",
            new=AsyncMock(side_effect=TimeoutError("deadline")),
        ):
            result = asyncio.run(orchestrator.run(REQUIREMENT))
        self.assertEqual(result.status, RunStatus.TIMEOUT)
        self.assertEqual(result.termination_reason, TerminationReason.TIMEOUT)


if __name__ == "__main__":
    unittest.main()
