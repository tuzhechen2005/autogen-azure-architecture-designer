"""Bounded AutoGen collaboration loop for local Azure architecture design."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from time import monotonic
from typing import TypeVar
from uuid import uuid4

from autogen_agentchat.agents import AssistantAgent
from autogen_core import CancellationToken
from autogen_core.models import ChatCompletionClient
from pydantic import BaseModel, ValidationError

from .agents import create_architecture_agents
from .output_parser import StructuredOutputError, parse_structured_output
from .prompts import build_initial_plan_task, build_revision_task, build_review_task
from .progress_guard import ProgressGuard, resolve_review_changes
from .run_log import log_attempt_failure, log_run_failure
from .topology_contract import TopologyContractError, validate_topology_policy
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


def _revision_target_text(
    plan: ArchitecturePlan,
    target_field: str,
    resource_name: str | None,
) -> str:
    scope, field_name = target_field.split(".", 1)
    if scope == "resource":
        resource = next(
            (
                candidate
                for candidate in plan.resources
                if candidate.name == resource_name
            ),
            None,
        )
        if resource is None:
            raise StructuredOutputError(
                f"revision constraint targets unknown resource: {resource_name}"
            )
        value = getattr(resource, field_name)
    else:
        value = getattr(plan, field_name)
    if isinstance(value, list):
        return "\n".join(value).casefold()
    return str(value).casefold()


def validate_revision_transition(
    previous: ArchitecturePlan,
    revised: ArchitecturePlan,
    review: ArchitectureReview,
) -> None:
    """Enforce immutable identity and every machine-verifiable review change."""

    if revised.revision != previous.revision + 1:
        raise StructuredOutputError(
            "schema validation failed: revision must increment by exactly one"
        )

    previous_by_name = {resource.name: resource for resource in previous.resources}
    revised_by_name = {resource.name: resource for resource in revised.resources}
    if previous_by_name.keys() != revised_by_name.keys():
        raise StructuredOutputError(
            "revision must preserve the resource names and resource count"
        )

    for name, previous_resource in previous_by_name.items():
        revised_resource = revised_by_name[name]
        if revised_resource.resource_type != previous_resource.resource_type:
            raise StructuredOutputError(
                f"revision must preserve resource type for {name}"
            )
        if set(revised_resource.depends_on) != set(previous_resource.depends_on):
            raise StructuredOutputError(
                f"revision must preserve dependency relationships for {name}"
            )

    if previous.model_dump(exclude={"revision"}) == revised.model_dump(
        exclude={"revision"}
    ):
        raise StructuredOutputError(
            "revision must make a substantive change beyond its revision number"
        )

    for change in review.required_changes:
        target_text = _revision_target_text(
            revised,
            change.target_field,
            change.resource_name,
        )
        missing_terms = [
            term for term in change.required_terms if term.casefold() not in target_text
        ]
        if missing_terms:
            raise StructuredOutputError(
                f"revision did not satisfy required change: {change.description}"
            )


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
        max_run_seconds: float = 600.0,
        event_sink: EventSink | None = None,
    ) -> None:
        if not 1 <= max_review_rounds <= 5:
            raise ValueError("max_review_rounds must be between 1 and 5")
        if not 0 <= max_parse_retries <= 2:
            raise ValueError("max_parse_retries must be between 0 and 2")
        if not 0.01 <= max_run_seconds <= 3600.0:
            raise ValueError("max_run_seconds must be between 0.01 and 3600")
        self._model_client = model_client
        self._max_review_rounds = max_review_rounds
        self._max_parse_retries = max_parse_retries
        self._max_run_seconds = max_run_seconds
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
        run_id: str,
        role: AgentRole,
        phase: MessagePhase,
        review_round: int,
        transcript: list[TranscriptMessage],
        expected_revision: int | None = None,
        previous_plan: ArchitecturePlan | None = None,
        prior_review: ArchitectureReview | None = None,
        run_deadline: float,
    ) -> SchemaT:
        next_task = task
        last_error: StructuredOutputError | None = None
        for attempt in range(self._max_parse_retries + 1):
            remaining_seconds = run_deadline - monotonic()
            if remaining_seconds <= 0:
                raise TimeoutError("Architecture run exceeded its wall-clock timeout")
            cancellation_token = CancellationToken()
            input_summary_sha256 = hashlib.sha256(next_task.encode()).hexdigest()
            attempt_started = monotonic()
            try:
                result = await asyncio.wait_for(
                    agent.run(
                        task=next_task,
                        cancellation_token=cancellation_token,
                    ),
                    timeout=remaining_seconds,
                )
            except TimeoutError as exc:
                cancellation_token.cancel()
                raise TimeoutError(
                    "Architecture run exceeded its wall-clock timeout"
                ) from exc
            raw_content = self._last_content(result)
            duration_ms = (monotonic() - attempt_started) * 1000
            result_messages = getattr(result, "messages", [])
            last_result_message = result_messages[-1] if result_messages else None
            usage = getattr(last_result_message, "models_usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            raw_output_sha256 = hashlib.sha256(raw_content.encode()).hexdigest()
            try:
                parsed = parse_structured_output(raw_content, schema)
                if isinstance(parsed, ArchitecturePlan):
                    try:
                        validate_topology_policy(parsed)
                    except TopologyContractError as exc:
                        raise StructuredOutputError(
                            f"topology policy failed: {exc}"
                        ) from exc
                if (
                    expected_revision is not None
                    and isinstance(parsed, ArchitecturePlan)
                    and parsed.revision != expected_revision
                ):
                    raise StructuredOutputError(
                        "schema validation failed: revision must equal "
                        f"{expected_revision}, got {parsed.revision}"
                    )
                if previous_plan is not None and prior_review is not None:
                    if not isinstance(parsed, ArchitecturePlan):
                        raise StructuredOutputError(
                            "revision transition requires an architecture plan"
                        )
                    validate_revision_transition(previous_plan, parsed, prior_review)
            except StructuredOutputError as exc:
                last_error = exc
                log_attempt_failure(
                    run_id=run_id,
                    role=role.value,
                    phase=phase.value,
                    review_round=review_round,
                    attempt=attempt + 1,
                    max_attempts=self._max_parse_retries + 1,
                    error=exc,
                    raw_output=raw_content,
                )
                failed_message = TranscriptMessage(
                    sequence=len(transcript) + 1,
                    review_round=review_round,
                    role=role,
                    phase=phase,
                    raw_content=raw_content,
                    parsed_content=None,
                    input_summary_sha256=input_summary_sha256,
                    raw_output_sha256=raw_output_sha256,
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    validation_status="invalid",
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
                input_summary_sha256=input_summary_sha256,
                raw_output_sha256=raw_output_sha256,
                duration_ms=duration_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                validation_status="valid",
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

        run_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        run_deadline = monotonic() + self._max_run_seconds
        request: ArchitectureRequest | None = None
        transcript: list[TranscriptMessage] = []
        plan: ArchitecturePlan | None = None
        review: ArchitectureReview | None = None
        rounds_completed = 0
        progress_guard = ProgressGuard()

        try:
            request = ArchitectureRequest(requirements=requirements)
            self._emit(
                CollaborationEvent(
                    event_type=EventType.STATUS,
                    text="Planner is creating the initial architecture.",
                )
            )
            agents = create_architecture_agents(self._model_client)
            plan = await self._run_structured_agent(
                agent=agents.planner,
                task=build_initial_plan_task(request.requirements),
                schema=ArchitecturePlan,
                run_id=run_id,
                role=AgentRole.PLANNER,
                phase=MessagePhase.INITIAL_PLAN,
                review_round=0,
                transcript=transcript,
                expected_revision=1,
                run_deadline=run_deadline,
            )
            progress_guard.observe_plan(plan)

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
                    run_id=run_id,
                    role=AgentRole.REVIEWER,
                    phase=MessagePhase.REVIEW,
                    review_round=review_round,
                    transcript=transcript,
                    run_deadline=run_deadline,
                )
                rounds_completed = review_round

                review_is_new = progress_guard.observe_review(review)
                if (
                    review.decision is ReviewDecision.REVISION_REQUIRED
                    and not review_is_new
                ):
                    result = self._build_result(
                        run_id=run_id,
                        request=request,
                        status=RunStatus.DEGRADED,
                        termination_reason=TerminationReason.NO_PROGRESS,
                        plan=plan,
                        review=review,
                        transcript=transcript,
                        rounds_completed=rounds_completed,
                        started_at=started_at,
                    )
                    self._emit(
                        CollaborationEvent(
                            event_type=EventType.COMPLETED,
                            text="Repeated reviewer requirements detected; returning the latest validated plan.",
                            review_round=rounds_completed,
                            result=result,
                        )
                    )
                    return result

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
                        run_id=run_id,
                        role=AgentRole.PLANNER,
                        phase=MessagePhase.REVISION,
                        review_round=review_round,
                        transcript=transcript,
                        expected_revision=plan.revision + 1,
                        previous_plan=plan,
                        prior_review=review,
                        run_deadline=run_deadline,
                    )
                    progress_guard.observe_plan(plan)

            result = self._build_result(
                run_id=run_id,
                request=request,
                status=RunStatus.DEGRADED,
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
        except TimeoutError as exc:
            log_run_failure(
                run_id=run_id,
                error=exc,
                review_rounds_completed=rounds_completed,
            )
            result = self._build_result(
                run_id=run_id,
                request=request,
                status=RunStatus.TIMEOUT,
                termination_reason=TerminationReason.TIMEOUT,
                plan=plan,
                review=review,
                transcript=transcript,
                rounds_completed=rounds_completed,
                started_at=started_at,
                error=f"TimeoutError: {exc}",
            )
            self._emit(
                CollaborationEvent(
                    event_type=EventType.ERROR,
                    text=result.error or "Architecture run timed out.",
                    review_round=rounds_completed,
                    result=result,
                )
            )
            return result
        except Exception as exc:
            log_run_failure(
                run_id=run_id,
                error=exc,
                review_rounds_completed=rounds_completed,
            )
            error = (
                "Invalid architecture requirements"
                if request is None and isinstance(exc, ValidationError)
                else f"{type(exc).__name__}: {exc}"
            )
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
                error=error,
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
        request: ArchitectureRequest | None,
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
            review_resolutions=(
                resolve_review_changes(review, plan)
                if review is not None and plan is not None
                else []
            ),
            messages=list(transcript),
            review_rounds_completed=rounds_completed,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            error=error,
        )
