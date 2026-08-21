"""Bounded AutoGen collaboration loop for local Azure architecture design."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TypeVar
from uuid import uuid4

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from pydantic import BaseModel

from .agents import create_architecture_agents
from .output_parser import StructuredOutputError, parse_structured_output
from .prompts import build_initial_plan_task, build_revision_task, build_review_task
from .schemas import (
    AgentRole,
    ArchitecturePlan,
    ArchitectureRequest,
    ArchitectureReview,
    ArchitectureRunResult,
    MessagePhase,
    ReviewDecision,
    RunStatus,
    TerminationReason,
    TranscriptMessage,
)


SchemaT = TypeVar("SchemaT", bound=BaseModel)
EventSink = Callable[["CollaborationEvent"], None]


class EventType(str, Enum):
    STATUS = "status"
    AGENT_MESSAGE = "agent_message"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CollaborationEvent:
    """A safe, UI-facing event emitted at orchestration boundaries."""

    event_type: EventType
    text: str
    review_round: int = 0
    message: TranscriptMessage | None = None
    result: ArchitectureRunResult | None = None


class ArchitectureOrchestrator:
    """Coordinates planner/reviewer turns using explicit validated context."""

    def __init__(
        self,
        model_client: ChatCompletionClient,
        *,
        max_review_rounds: int = 2,
        max_parse_retries: int = 1,
        event_sink: EventSink | None = None,
    ) -> None:
        if not 1 <= max_review_rounds <= 5:
            raise ValueError("max_review_rounds must be between 1 and 5")
        if not 0 <= max_parse_retries <= 2:
            raise ValueError("max_parse_retries must be between 0 and 2")
        self._model_client = model_client
        self._max_review_rounds = max_review_rounds
        self._max_parse_retries = max_parse_retries
        self._event_sink = event_sink

    def _emit(self, event: CollaborationEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def _fresh_agent(self, role: AgentRole) -> AssistantAgent:
        agents = create_architecture_agents(self._model_client)
        return agents.planner if role is AgentRole.PLANNER else agents.reviewer

    @staticmethod
    def _last_content(result: object) -> str:
        messages = getattr(result, "messages", [])
        if not messages:
            raise RuntimeError("AutoGen returned no agent messages")
        content = str(getattr(messages[-1], "content", "")).strip()
        if not content:
            raise RuntimeError("AutoGen returned an empty agent message")
        return content

    async def _run_structured_agent(
        self,
        *,
        agent: AssistantAgent,
        task: str,
        schema: type[SchemaT],
        role: AgentRole,
        phase: MessagePhase,
        review_round: int,
        transcript: list[TranscriptMessage],
        expected_revision: int | None = None,
    ) -> SchemaT:
        next_task = task
        last_error: StructuredOutputError | None = None
        for attempt in range(self._max_parse_retries + 1):
            result = await agent.run(task=next_task)
            raw_content = self._last_content(result)
            try:
                parsed = parse_structured_output(raw_content, schema)
                if (
                    expected_revision is not None
                    and isinstance(parsed, ArchitecturePlan)
                    and parsed.revision != expected_revision
                ):
                    raise StructuredOutputError(
                        "schema validation failed: revision must equal "
                        f"{expected_revision}, got {parsed.revision}"
                    )
            except StructuredOutputError as exc:
                last_error = exc
                failed_message = TranscriptMessage(
                    sequence=len(transcript) + 1,
                    review_round=review_round,
                    role=role,
                    phase=phase,
                    raw_content=raw_content,
                    parsed_content=None,
                    created_at=datetime.now(timezone.utc),
                )
                transcript.append(failed_message)
                self._emit(
                    CollaborationEvent(
                        event_type=EventType.AGENT_MESSAGE,
                        text=f"{role.value} returned invalid structured output",
                        review_round=review_round,
                        message=failed_message,
                    )
                )
                if attempt >= self._max_parse_retries:
                    raise StructuredOutputError(
                        f"{role.value}/{phase.value} failed after "
                        f"{attempt + 1} attempt(s): {exc}"
                    ) from exc
                agent = self._fresh_agent(role)
                next_task = (
                    f"{task}\nPREVIOUS_OUTPUT_ERROR: {exc}\n"
                    "Start again and return one corrected complete JSON object only."
                )
                continue

            message = TranscriptMessage(
                sequence=len(transcript) + 1,
                review_round=review_round,
                role=role,
                phase=phase,
                raw_content=raw_content,
                parsed_content=parsed.model_dump(mode="json"),
                created_at=datetime.now(timezone.utc),
            )
            transcript.append(message)
            self._emit(
                CollaborationEvent(
                    event_type=EventType.AGENT_MESSAGE,
                    text=f"{role.value} completed {phase.value}",
                    review_round=review_round,
                    message=message,
                )
            )
            return parsed

        raise last_error or StructuredOutputError("structured generation failed")

    async def run(self, requirements: str) -> ArchitectureRunResult:
        """Run planning and review until approval or the configured round limit."""

        request = ArchitectureRequest(requirements=requirements)
        run_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        transcript: list[TranscriptMessage] = []
        plan: ArchitecturePlan | None = None
        review: ArchitectureReview | None = None
        rounds_completed = 0

        self._emit(
            CollaborationEvent(
                event_type=EventType.STATUS,
                text="Planner is creating the initial architecture.",
            )
        )

        try:
            agents = create_architecture_agents(self._model_client)
            plan = await self._run_structured_agent(
                agent=agents.planner,
                task=build_initial_plan_task(request.requirements),
                schema=ArchitecturePlan,
                role=AgentRole.PLANNER,
                phase=MessagePhase.INITIAL_PLAN,
                review_round=0,
                transcript=transcript,
                expected_revision=1,
            )

            for review_round in range(1, self._max_review_rounds + 1):
                self._emit(
                    CollaborationEvent(
                        event_type=EventType.STATUS,
                        text=f"Reviewer is checking round {review_round}.",
                        review_round=review_round,
                    )
                )
                round_agents = create_architecture_agents(self._model_client)
                review = await self._run_structured_agent(
                    agent=round_agents.reviewer,
                    task=build_review_task(request.requirements, plan),
                    schema=ArchitectureReview,
                    role=AgentRole.REVIEWER,
                    phase=MessagePhase.REVIEW,
                    review_round=review_round,
                    transcript=transcript,
                )
                rounds_completed = review_round

                if review.decision is ReviewDecision.APPROVED:
                    result = self._build_result(
                        run_id=run_id,
                        request=request,
                        status=RunStatus.COMPLETED,
                        termination_reason=TerminationReason.APPROVED,
                        plan=plan,
                        review=review,
                        transcript=transcript,
                        rounds_completed=rounds_completed,
                        started_at=started_at,
                    )
                    self._emit(
                        CollaborationEvent(
                            event_type=EventType.COMPLETED,
                            text=(
                                "Architecture approved in "
                                f"{rounds_completed} review round(s)."
                            ),
                            review_round=rounds_completed,
                            result=result,
                        )
                    )
                    return result

                if review_round < self._max_review_rounds:
                    self._emit(
                        CollaborationEvent(
                            event_type=EventType.STATUS,
                            text=f"Planner is preparing revision {plan.revision + 1}.",
                            review_round=review_round,
                        )
                    )
                    revision_agents = create_architecture_agents(self._model_client)
                    plan = await self._run_structured_agent(
                        agent=revision_agents.planner,
                        task=build_revision_task(request.requirements, plan, review),
                        schema=ArchitecturePlan,
                        role=AgentRole.PLANNER,
                        phase=MessagePhase.REVISION,
                        review_round=review_round,
                        transcript=transcript,
                        expected_revision=plan.revision + 1,
                    )

            result = self._build_result(
                run_id=run_id,
                request=request,
                status=RunStatus.COMPLETED,
                termination_reason=TerminationReason.MAX_REVIEW_ROUNDS,
                plan=plan,
                review=review,
                transcript=transcript,
                rounds_completed=rounds_completed,
                started_at=started_at,
            )
            self._emit(
                CollaborationEvent(
                    event_type=EventType.COMPLETED,
                    text=(
                        "Maximum review rounds reached; returning the latest "
                        "validated plan with unresolved findings."
                    ),
                    review_round=rounds_completed,
                    result=result,
                )
            )
            return result
        except Exception as exc:
            result = self._build_result(
                run_id=run_id,
                request=request,
                status=RunStatus.FAILED,
                termination_reason=TerminationReason.ERROR,
                plan=plan,
                review=review,
                transcript=transcript,
                rounds_completed=rounds_completed,
                started_at=started_at,
                error=f"{type(exc).__name__}: {exc}",
            )
            self._emit(
                CollaborationEvent(
                    event_type=EventType.ERROR,
                    text=result.error or "Architecture run failed.",
                    review_round=rounds_completed,
                    result=result,
                )
            )
            return result

    @staticmethod
    def _build_result(
        *,
        run_id: str,
        request: ArchitectureRequest,
        status: RunStatus,
        termination_reason: TerminationReason,
        plan: ArchitecturePlan | None,
        review: ArchitectureReview | None,
        transcript: list[TranscriptMessage],
        rounds_completed: int,
        started_at: datetime,
        error: str | None = None,
    ) -> ArchitectureRunResult:
        return ArchitectureRunResult(
            run_id=run_id,
            request=request,
            status=status,
            termination_reason=termination_reason,
            final_plan=plan,
            final_review=review,
            messages=list(transcript),
            review_rounds_completed=rounds_completed,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            error=error,
        )
