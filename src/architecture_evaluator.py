import json
import math
from collections import defaultdict

from .architecture_evaluation_dataset import ArchitectureFaultCase, ArchitectureRequirementCase
from .schemas import ArchitectureRunResult, RunStatus


def score_requirement_case(case: ArchitectureRequirementCase, result: ArchitectureRunResult) -> dict[str, object]:
    plan_text = (
        json.dumps(result.final_plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).casefold()
        if result.final_plan is not None
        else ""
    )
    point_scores = [
        all(term.casefold() in plan_text for term in point.required_terms)
        for point in case.gold_requirement_points
    ]
    resolutions = result.review_resolutions
    review_rate = (
        sum(item.status == "implemented" for item in resolutions) / len(resolutions)
        if resolutions
        else None
    )
    latency_ms = (result.finished_at - result.started_at).total_seconds() * 1000
    return {
        "caseId": case.case_id,
        "category": case.primary_category,
        "language": case.language,
        "structuredOutputSuccess": (
            result.final_plan is not None
            and result.status in {RunStatus.COMPLETED, RunStatus.DEGRADED}
        ),
        "requirementPointScores": point_scores,
        "requirementCoverage": sum(point_scores) / len(point_scores),
        "dependencyValid": result.final_plan is not None,
        "reviewImplementationRate": review_rate,
        "reviewRounds": result.review_rounds_completed,
        "agentCalls": len(result.messages),
        "latencyMs": latency_ms,
        "fallback": result.status is RunStatus.DEGRADED,
        "terminationReason": result.termination_reason.value,
    }


def score_fault_case(case: ArchitectureFaultCase, result: ArchitectureRunResult) -> dict[str, object]:
    return {
        "caseId": case.case_id,
        "faultType": case.fault_type,
        "expectedTerminal": result.status.value == case.expected_terminal,
        "boundedTermination": len(result.messages) <= case.expected_max_agent_calls,
        "agentCalls": len(result.messages),
        "actualTerminal": result.status.value,
        "terminationReason": result.termination_reason.value,
    }


def _mean_present(scores: list[dict[str, object]], key: str) -> float | None:
    values = [float(item[key]) for item in scores if item.get(key) is not None]
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_architecture_scores(scores: list[dict[str, object]]) -> dict[str, object]:
    latencies = [float(item["latencyMs"]) for item in scores]
    groups: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for item in scores:
        groups[str(item.get("category"))].append(item)
    return {
        "caseCount": len(scores),
        "structuredOutputSuccessRate": sum(bool(item["structuredOutputSuccess"]) for item in scores) / len(scores) if scores else 0.0,
        "requirementCoverage": _mean_present(scores, "requirementCoverage"),
        "dependencyValidityRate": sum(bool(item["dependencyValid"]) for item in scores) / len(scores) if scores else 0.0,
        "reviewImplementationRate": _mean_present(scores, "reviewImplementationRate"),
        "averageReviewRounds": _mean_present(scores, "reviewRounds"),
        "fallbackRate": sum(bool(item["fallback"]) for item in scores) / len(scores) if scores else 0.0,
        "latencyMs": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "byCategory": {
            name: {
                "caseCount": len(items),
                "requirementCoverage": _mean_present(items, "requirementCoverage"),
                "structuredOutputSuccessRate": sum(bool(item["structuredOutputSuccess"]) for item in items) / len(items),
            }
            for name, items in sorted(groups.items())
        },
    }


def ablation_arms() -> list[dict[str, object]]:
    return [
        {"name": "single_agent", "planner": True, "reviewer": False, "contract": True, "maxReviewRounds": 0},
        {"name": "planner_reviewer", "planner": True, "reviewer": True, "contract": True, "maxReviewRounds": 2},
        {"name": "no_contract", "planner": True, "reviewer": True, "contract": False, "maxReviewRounds": 2},
        {"name": "full_contract", "planner": True, "reviewer": True, "contract": True, "maxReviewRounds": 2},
        {"name": "max_rounds_1", "planner": True, "reviewer": True, "contract": True, "maxReviewRounds": 1},
        {"name": "max_rounds_3", "planner": True, "reviewer": True, "contract": True, "maxReviewRounds": 3},
    ]
