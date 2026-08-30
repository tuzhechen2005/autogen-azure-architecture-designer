"""Validated data contracts shared by agents, orchestration, and the web UI."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects invented fields, coercion, and unsafe whitespace."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )


class ArchitectureRequest(StrictModel):
    """A user's local architecture-design request."""

    requirements: str = Field(min_length=10, max_length=6000)

    @field_validator("requirements", mode="before")
    @classmethod
    def normalize_visible_requirements(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = unicodedata.normalize("NFKC", value)
        allowed_controls = {"\n", "\r", "\t"}
        for character in normalized:
            if (
                unicodedata.category(character) in {"Cc", "Cf", "Cs"}
                and character not in allowed_controls
            ):
                raise ValueError("requirements contain disallowed control characters")
        if not any(not character.isspace() for character in normalized):
            raise ValueError("requirements must contain visible characters")
        return normalized


class AzureResource(StrictModel):
    """One proposed Azure resource without any deployment credentials."""

    name: str = Field(min_length=2, max_length=80)
    resource_type: str = Field(min_length=3, max_length=120)
    region: str = Field(min_length=2, max_length=60)
    sku: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=2, max_length=500)
    high_availability: list[str] = Field(max_length=8)
    depends_on: list[str] = Field(max_length=12)


class ArchitecturePlan(StrictModel):
    """The planner's complete, display-ready Azure architecture proposal."""

    title: str = Field(min_length=3, max_length=160)
    summary: str = Field(min_length=10, max_length=1200)
    revision: int = Field(ge=1, le=10)
    assumptions: list[str] = Field(max_length=12)
    resources: list[AzureResource] = Field(min_length=1, max_length=24)
    data_flow: list[str] = Field(min_length=1, max_length=16)
    high_availability_strategy: list[str] = Field(min_length=1, max_length=16)
    security_strategy: list[str] = Field(max_length=16)
    operations_strategy: list[str] = Field(max_length=16)
    cost_notes: list[str] = Field(max_length=12)

    @model_validator(mode="after")
    def dependency_graph_is_valid(self) -> "ArchitecturePlan":
        names = [resource.name for resource in self.resources]
        if len(names) != len(set(names)):
            raise ValueError("resource names must be unique")

        known_names = set(names)
        graph: dict[str, tuple[str, ...]] = {}
        for resource in self.resources:
            dependencies = tuple(resource.depends_on)
            if len(dependencies) != len(set(dependencies)):
                raise ValueError(
                    f"resource {resource.name} contains duplicate dependencies"
                )
            if resource.name in dependencies:
                raise ValueError(
                    f"resource {resource.name} cannot depend on itself"
                )
            unknown = set(dependencies) - known_names
            if unknown:
                raise ValueError(
                    f"resource {resource.name} has unknown dependencies: "
                    f"{sorted(unknown)}"
                )
            graph[resource.name] = dependencies

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visiting:
                raise ValueError("resource dependency graph contains a cycle")
            if name in visited:
                return
            visiting.add(name)
            for dependency in graph[name]:
                visit(dependency)
            visiting.remove(name)
            visited.add(name)

        for name in names:
            visit(name)
        return self


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    REVISION_REQUIRED = "revision_required"


ReviewSeverity = Literal["critical", "high", "medium", "low"]
RevisionTargetField = Literal[
    "resource.high_availability",
    "resource.sku",
    "resource.region",
    "resource.purpose",
    "plan.high_availability_strategy",
    "plan.security_strategy",
    "plan.operations_strategy",
]
RequiredTerm = Annotated[str, Field(min_length=1, max_length=80)]


class ReviewFinding(StrictModel):
    """One evidence-linked architecture issue and its concrete correction."""

    severity: ReviewSeverity
    category: str = Field(min_length=2, max_length=80)
    issue: str = Field(min_length=5, max_length=600)
    recommendation: str = Field(min_length=5, max_length=600)


class RequiredChange(StrictModel):
    """A reviewer correction with a bounded, machine-verifiable plan target."""

    description: str = Field(min_length=5, max_length=600)
    target_field: RevisionTargetField
    resource_name: str | None
    required_terms: list[RequiredTerm] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def target_matches_resource_scope(self) -> "RequiredChange":
        targets_resource = self.target_field.startswith("resource.")
        if targets_resource and self.resource_name is None:
            raise ValueError("resource targets require resource_name")
        if not targets_resource and self.resource_name is not None:
            raise ValueError("plan targets cannot contain resource_name")
        return self


class ArchitectureReview(StrictModel):
    """The reviewer's structured high-availability verdict."""

    decision: ReviewDecision
    summary: str = Field(min_length=10, max_length=1000)
    strengths: list[str] = Field(max_length=12)
    findings: list[ReviewFinding] = Field(max_length=16)
    required_changes: list[RequiredChange] = Field(max_length=3)

    @model_validator(mode="after")
    def decision_matches_required_changes(self) -> "ArchitectureReview":
        if self.decision is ReviewDecision.APPROVED and self.findings:
            raise ValueError("approved reviews cannot contain findings")
        if self.decision is ReviewDecision.APPROVED and self.required_changes:
            raise ValueError("approved reviews cannot contain required_changes")
        if (
            self.decision is ReviewDecision.REVISION_REQUIRED
            and not self.required_changes
        ):
            raise ValueError("revision_required reviews need at least one required change")
        return self


class AgentRole(str, Enum):
    PLANNER = "planner"
    REVIEWER = "reviewer"


class MessagePhase(str, Enum):
    INITIAL_PLAN = "initial_plan"
    REVIEW = "review"
    REVISION = "revision"


class TranscriptMessage(StrictModel):
    """One visible agent message; no hidden chain-of-thought is requested or stored."""

    sequence: int = Field(ge=1)
    review_round: int = Field(ge=0, le=5)
    role: AgentRole
    phase: MessagePhase
    raw_content: str = Field(min_length=1)
    parsed_content: dict[str, object] | None = None
    input_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_ms: float = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    validation_status: Literal["valid", "invalid"]
    created_at: datetime


class RunStatus(str, Enum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    TIMEOUT = "timeout"
    FAILED = "failed"


class TerminationReason(str, Enum):
    APPROVED = "approved"
    MAX_REVIEW_ROUNDS = "max_review_rounds"
    NO_PROGRESS = "no_progress"
    TIMEOUT = "timeout"
    ERROR = "error"


class ReviewResolution(StrictModel):
    """Machine-verifiable disposition for one reviewer-required change."""

    required_change_index: int = Field(ge=0, le=2)
    description: str = Field(min_length=5, max_length=600)
    status: Literal["implemented", "unresolved"]
    evidence_field: RevisionTargetField


class ArchitectureRunResult(StrictModel):
    """Complete local output returned to Streamlit and optional trace storage."""

    run_id: str = Field(min_length=8, max_length=80)
    request: ArchitectureRequest | None
    status: RunStatus
    termination_reason: TerminationReason
    final_plan: ArchitecturePlan | None = None
    final_review: ArchitectureReview | None = None
    review_resolutions: list[ReviewResolution] = Field(default_factory=list)
    messages: list[TranscriptMessage] = Field(default_factory=list)
    review_rounds_completed: int = Field(ge=0, le=5)
    started_at: datetime
    finished_at: datetime
    error: str | None = None

    @model_validator(mode="after")
    def completed_run_has_request(self) -> "ArchitectureRunResult":
        if self.status is RunStatus.COMPLETED and self.request is None:
            raise ValueError("completed runs require a validated request")
        return self
