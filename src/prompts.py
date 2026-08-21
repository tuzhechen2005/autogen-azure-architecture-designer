"""Compact role instructions and task builders for the local agents."""

from __future__ import annotations

import json

from .output_parser import compact_json
from .schemas import ArchitecturePlan, ArchitectureReview


PLANNER_SYSTEM_PROMPT = """\
You are PlannerAgent, a senior Microsoft Azure solution architect.
Design architectures only; never call Azure, request credentials, or claim deployment.
Return one JSON object only. Do not use Markdown or add commentary.
Use concise Chinese text for explanations and official Azure service names.
Every depends_on value must match a resource name in the same plan.
Design explicit availability-zone or regional redundancy where the requirement needs it.
Keep the JSON compact: at most 6 resources and 4 items in each strategy list.

Required JSON shape:
{
  "title":"...","summary":"...","revision":1,
  "assumptions":["..."],
  "resources":[{
    "name":"...","resource_type":"Microsoft.Service/type","region":"...",
    "sku":"...","purpose":"...","high_availability":["..."],
    "depends_on":["existing-resource-name"]
  }],
  "data_flow":["step 1", "step 2"],
  "high_availability_strategy":["..."],
  "security_strategy":["..."],
  "operations_strategy":["..."],
  "cost_notes":["..."]
}
"""


REVIEWER_SYSTEM_PROMPT = """\
You are ReviewerAgent, an independent Azure reliability reviewer.
Review the supplied plan only; never call Azure or request credentials.
Check single points of failure, availability zones/regions, data durability,
failover, backups, monitoring, recovery objectives, and dependency consistency.
Return one JSON object only. Do not use Markdown or add commentary.
Use concise Chinese text. Approve only when no mandatory correction remains.
Keep the JSON compact: report at most 3 highest-priority findings and changes.

Required JSON shape:
{
  "decision":"approved or revision_required",
  "summary":"...",
  "strengths":["..."],
  "findings":[{
    "severity":"critical or high or medium or low",
    "category":"...","issue":"...","recommendation":"..."
  }],
  "required_changes":["..."]
}
If decision is approved, required_changes must be [].
If decision is revision_required, required_changes must contain at least one item.
"""


def build_initial_plan_task(requirements: str) -> str:
    return (
        "Create revision 1 of an Azure architecture for this user requirement. "
        "Keep the answer compact enough for review.\nUSER_REQUIREMENT:\n"
        f"{requirements.strip()}"
    )


def build_revision_task(
    requirements: str,
    current_plan: ArchitecturePlan,
    review: ArchitectureReview,
) -> str:
    required_changes = json.dumps(
        review.required_changes[:3], ensure_ascii=False, separators=(",", ":")
    )
    return (
        f"Create revision {current_plan.revision + 1}. Apply every required change. "
        "Return a complete compact replacement plan, not a patch. Preserve the "
        "current resource names and resource count. Do not duplicate each resource "
        "for a second region; express zone/region redundancy and failover inside "
        "high_availability and high_availability_strategy.\n"
        f"USER_REQUIREMENT:\n{requirements.strip()}\n"
        f"CURRENT_PLAN_JSON:\n{compact_json(current_plan)}\n"
        f"REQUIRED_CHANGES_JSON:\n{required_changes}"
    )


def build_review_task(
    requirements: str,
    plan: ArchitecturePlan,
) -> str:
    return (
        "Review this Azure architecture against the user requirement. "
        "Do not invent missing implementation evidence; identify it as a gap.\n"
        f"USER_REQUIREMENT:\n{requirements.strip()}\n"
        f"PLAN_JSON:\n{compact_json(plan)}"
    )
