import unittest
from datetime import datetime, timedelta, timezone

from src.architecture_evaluation_dataset import ArchitectureFaultCase, ArchitectureRequirementCase, RequirementPoint
from src.architecture_evaluator import ablation_arms, score_fault_case, score_requirement_case, summarize_architecture_scores
from src.schemas import ArchitecturePlan, ArchitectureRequest, ArchitectureRunResult, RunStatus, TerminationReason
from tests.test_orchestrator_revision import initial_plan


class ArchitectureEvaluatorTests(unittest.TestCase):
    def _result(self) -> ArchitectureRunResult:
        start = datetime(2026, 8, 30, tzinfo=timezone.utc)
        return ArchitectureRunResult(
            run_id="run-12345678",
            request=ArchitectureRequest(requirements="Design a highly available API with zone redundancy."),
            status=RunStatus.COMPLETED,
            termination_reason=TerminationReason.APPROVED,
            final_plan=ArchitecturePlan.model_validate(initial_plan()),
            final_review=None,
            messages=[], review_rounds_completed=1,
            started_at=start, finished_at=start + timedelta(seconds=2), error=None,
        )

    def test_requirement_coverage_is_machine_derived(self) -> None:
        case = ArchitectureRequirementCase(
            case_id="case-one", split="frozen_test", language="en",
            primary_category="availability",
            requirements="Design a highly available API with zone redundancy.",
            gold_requirement_points=[
                RequirementPoint(point_id="ha-1", category="availability", required_terms=["可用区", "冗余"]),
                RequirementPoint(point_id="missing", category="availability", required_terms=["multi-region"]),
            ],
        )
        score = score_requirement_case(case, self._result())
        self.assertEqual(score["requirementCoverage"], 0.5)
        self.assertTrue(score["dependencyValid"])
        self.assertEqual(score["latencyMs"], 2000.0)

    def test_fault_score_enforces_terminal_and_call_bound(self) -> None:
        case = ArchitectureFaultCase(
            case_id="fault-one", split="fault", fault_type="timeout",
            injection_round=1, expected_terminal="timeout", expected_max_agent_calls=2,
        )
        result = self._result().model_copy(update={
            "status": RunStatus.TIMEOUT,
            "termination_reason": TerminationReason.TIMEOUT,
        })
        score = score_fault_case(case, result)
        self.assertTrue(score["boundedTermination"])
        self.assertTrue(score["expectedTerminal"])

    def test_summary_reports_quality_rounds_latency_and_fallback(self) -> None:
        scores = [
            {"structuredOutputSuccess": True, "requirementCoverage": 1.0, "dependencyValid": True,
             "reviewImplementationRate": 1.0, "reviewRounds": 1, "latencyMs": 10.0,
             "fallback": False, "category": "scale"},
            {"structuredOutputSuccess": True, "requirementCoverage": 0.5, "dependencyValid": True,
             "reviewImplementationRate": None, "reviewRounds": 2, "latencyMs": 30.0,
             "fallback": True, "category": "budget"},
        ]
        summary = summarize_architecture_scores(scores)
        self.assertEqual(summary["structuredOutputSuccessRate"], 1.0)
        self.assertEqual(summary["requirementCoverage"], 0.75)
        self.assertEqual(summary["averageReviewRounds"], 1.5)
        self.assertEqual(summary["fallbackRate"], 0.5)
        self.assertEqual(summary["latencyMs"]["p50"], 20.0)

    def test_ablation_catalog_contains_pre_registered_arms(self) -> None:
        arms = ablation_arms()
        names = {arm["name"] for arm in arms}
        required = {"single_agent", "planner_reviewer", "no_contract", "full_contract", "max_rounds_1", "max_rounds_3"}
        self.assertTrue(required.issubset(names))
        self.assertEqual(len(names), len(arms))


if __name__ == "__main__":
    unittest.main()
