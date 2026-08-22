"""Deterministic and optional real-model checks for the collaboration loop."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import AsyncGenerator, Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autogen_core import CancellationToken
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    ModelCapabilities,
    ModelInfo,
    RequestUsage,
)

from src.config import AppConfig
from src.local_model_client import LlamaCppChatCompletionClient
from src.orchestrator import ArchitectureOrchestrator, CollaborationEvent
from src.schemas import RunStatus, TerminationReason


REQUIREMENT = (
    "为中小型电商 API 设计 Azure 高可用架构，包含 Web 入口、Python API、"
    "PostgreSQL 和对象存储，可用性目标 99.9%，不执行真实部署。"
)

PLAN_1 = """{
"title":"E-commerce API","summary":"A first revision with one API instance.",
"revision":1,"assumptions":[],"resources":[
{"name":"api","resource_type":"Microsoft.Web/sites","region":"East US",
"sku":"P1v3","purpose":"Run API","high_availability":[],"depends_on":[]}],
"data_flow":["Client to API"],"high_availability_strategy":["Single instance"],
"security_strategy":[],"operations_strategy":[],"cost_notes":[]}
"""

REVIEW_1 = """{
"decision":"revision_required","summary":"The API has a single point of failure.",
"strengths":[],"findings":[{"severity":"high","category":"compute",
"issue":"Only one API instance is present.","recommendation":"Use two instances."}],
"required_changes":[{"description":"Use at least two API instances",
"target_field":"resource.high_availability","resource_name":"api",
"required_terms":["two instances"]}]}
"""

PLAN_2 = """{
"title":"E-commerce API","summary":"A revised zone-aware API architecture.",
"revision":2,"assumptions":[],"resources":[
{"name":"api","resource_type":"Microsoft.Web/sites","region":"East US",
"sku":"P1v3","purpose":"Run API","high_availability":["two instances"],
"depends_on":[]}],"data_flow":["Client to API"],
"high_availability_strategy":["Use two instances across zones"],
"security_strategy":[],"operations_strategy":[],"cost_notes":[]}
"""

REVIEW_2 = """{
"decision":"approved","summary":"The mandatory availability gap is resolved.",
"strengths":["Two API instances"],"findings":[],"required_changes":[]}
"""


class ScriptedModelClient(ChatCompletionClient):
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.usage = RequestUsage(prompt_tokens=0, completion_tokens=0)

    @property
    def model_info(self) -> ModelInfo:
        return {
            "vision": False,
            "function_calling": False,
            "json_output": False,
            "family": "unknown",
            "structured_output": False,
        }

    @property
    def capabilities(self) -> ModelCapabilities:
        return {"vision": False, "function_calling": False, "json_output": False}

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = (),
        tool_choice: Any = "auto",
        json_output: bool | type[Any] | None = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: CancellationToken | None = None,
    ) -> CreateResult:
        if not self.responses:
            raise RuntimeError("scripted responses exhausted")
        content = self.responses.pop(0)
        self.usage = RequestUsage(prompt_tokens=10, completion_tokens=10)
        return CreateResult(
            finish_reason="stop", content=content, usage=self.usage, cached=False
        )

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = (),
        tool_choice: Any = "auto",
        json_output: bool | type[Any] | None = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncGenerator[str | CreateResult, None]:
        yield await self.create(messages)

    async def close(self) -> None:
        return None

    def actual_usage(self) -> RequestUsage:
        return self.usage

    def total_usage(self) -> RequestUsage:
        return self.usage

    def count_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = ()
    ) -> int:
        return 10

    def remaining_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = ()
    ) -> int:
        return 4086


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use PHI3_MODEL_PATH and run the real local model instead of fixtures.",
    )
    return parser.parse_args()


async def run_scripted() -> None:
    events: list[CollaborationEvent] = []
    client = ScriptedModelClient([PLAN_1, REVIEW_1, PLAN_2, REVIEW_2])
    orchestrator = ArchitectureOrchestrator(
        client, max_review_rounds=2, event_sink=events.append
    )
    result = await orchestrator.run(REQUIREMENT)
    assert result.status is RunStatus.COMPLETED
    assert result.termination_reason is TerminationReason.APPROVED
    assert result.final_plan is not None and result.final_plan.revision == 2
    assert result.review_rounds_completed == 2
    assert [message.role.value for message in result.messages] == [
        "planner",
        "reviewer",
        "planner",
        "reviewer",
    ]
    assert events[-1].result is result
    print("Scripted orchestration passed: plan -> review -> revision -> approval")


async def run_real() -> None:
    config = AppConfig.from_env()
    client = LlamaCppChatCompletionClient(config)
    events: list[CollaborationEvent] = []
    orchestrator = ArchitectureOrchestrator(
        client, max_review_rounds=2, event_sink=events.append
    )
    try:
        result = await orchestrator.run(REQUIREMENT)
        if result.status is RunStatus.FAILED:
            for message in result.messages:
                if message.parsed_content is None:
                    print(
                        f"Invalid {message.role.value}/{message.phase.value} output:\n"
                        f"{message.raw_content}",
                        file=sys.stderr,
                    )
            raise RuntimeError(result.error or "real orchestration failed")
        if len(result.messages) < 2:
            raise RuntimeError("real orchestration did not produce both agent roles")
        print(
            "Real orchestration passed: "
            f"termination={result.termination_reason.value}, "
            f"messages={len(result.messages)}"
        )
    finally:
        await client.close()


def main() -> int:
    args = parse_args()
    try:
        asyncio.run(run_real() if args.real else run_scripted())
    except Exception as exc:
        print(f"Orchestrator smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
