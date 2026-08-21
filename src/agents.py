"""Construction of the two independent AutoGen architecture agents."""

from __future__ import annotations

from dataclasses import dataclass

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient

from .prompts import PLANNER_SYSTEM_PROMPT, REVIEWER_SYSTEM_PROMPT


@dataclass(slots=True)
class ArchitectureAgents:
    """The explicitly separated planning and high-availability review roles."""

    planner: AssistantAgent
    reviewer: AssistantAgent


def create_architecture_agents(
    model_client: ChatCompletionClient,
) -> ArchitectureAgents:
    """Create fresh agents that share a model runtime but not conversation context."""

    planner = AssistantAgent(
        name="planner_agent",
        description="Generates and revises structured Azure architecture plans.",
        model_client=model_client,
        system_message=PLANNER_SYSTEM_PROMPT,
        model_client_stream=False,
    )
    reviewer = AssistantAgent(
        name="reviewer_agent",
        description="Independently reviews Azure high availability and resilience.",
        model_client=model_client,
        system_message=REVIEWER_SYSTEM_PROMPT,
        model_client_stream=False,
    )
    return ArchitectureAgents(planner=planner, reviewer=reviewer)
