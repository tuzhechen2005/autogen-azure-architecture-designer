"""Run one real local planner call and validate its structured architecture."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents import create_architecture_agents
from src.config import AppConfig, ConfigurationError
from src.local_model_client import LlamaCppChatCompletionClient
from src.output_parser import StructuredOutputError, parse_structured_output
from src.prompts import build_initial_plan_task, build_review_task
from src.schemas import ArchitecturePlan, ArchitectureReview


SAMPLE_REQUIREMENT = (
    "为一个部署在中国以外 Azure 区域的中小型电商 API 设计高可用架构："
    "Web 入口、Python API、PostgreSQL 数据库和对象存储，目标可用性 99.9%，"
    "无真实 Azure 部署操作。"
)


def _last_content(result: object) -> str:
    messages = getattr(result, "messages", [])
    if not messages:
        raise RuntimeError("AutoGen returned no agent messages")
    return str(getattr(messages[-1], "content", ""))


async def run_smoke(config: AppConfig) -> None:
    client = LlamaCppChatCompletionClient(config)
    agents = create_architecture_agents(client)
    try:
        plan_result = await agents.planner.run(
            task=build_initial_plan_task(SAMPLE_REQUIREMENT)
        )
        raw_plan = _last_content(plan_result)
        try:
            plan = parse_structured_output(raw_plan, ArchitecturePlan)
        except StructuredOutputError:
            print(f"Raw planner output:\n{raw_plan}", file=sys.stderr)
            raise
        review_result = await agents.reviewer.run(
            task=build_review_task(SAMPLE_REQUIREMENT, plan)
        )
        raw_review = _last_content(review_result)
        try:
            review = parse_structured_output(raw_review, ArchitectureReview)
        except StructuredOutputError:
            print(f"Raw reviewer output:\n{raw_review}", file=sys.stderr)
            raise
        print(
            "Planner/reviewer smoke test passed: "
            f"{len(plan.resources)} resources, review={review.decision.value}"
        )
    finally:
        await client.close()


def main() -> int:
    try:
        config = AppConfig.from_env()
        asyncio.run(run_smoke(config))
    except (ConfigurationError, StructuredOutputError, RuntimeError) as exc:
        print(f"Agent smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
