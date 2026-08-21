"""Validated data contracts shared by agents, orchestration, and the web UI."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects invented fields and normalizes whitespace."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ArchitectureRequest(StrictModel):
    """A user's local architecture-design request."""

    requirements: str = Field(min_length=10, max_length=6000)


class AzureResource(StrictModel):
    """One proposed Azure resource without any deployment credentials."""

    name: str = Field(min_length=2, max_length=80)
    resource_type: str = Field(min_length=3, max_length=120)
    region: str = Field(min_length=2, max_length=60)
    sku: str = Field(default="TBD", min_length=1, max_length=80)
    purpose: str = Field(min_length=2, max_length=500)
    high_availability: list[str] = Field(default_factory=list, max_length=8)
    depends_on: list[str] = Field(default_factory=list, max_length=12)


class ArchitecturePlan(StrictModel):
    """The planner's complete, display-ready Azure architecture proposal."""

    title: str = Field(min_length=3, max_length=160)
    summary: str = Field(min_length=10, max_length=1200)
    revision: int = Field(default=1, ge=1, le=10)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    resources: list[AzureResource] = Field(min_length=1, max_length=24)
    data_flow: list[str] = Field(min_length=1, max_length=16)
    high_availability_strategy: list[str] = Field(min_length=1, max_length=16)
    security_strategy: list[str] = Field(default_factory=list, max_length=16)
    operations_strategy: list[str] = Field(default_factory=list, max_length=16)
    cost_notes: list[str] = Field(default_factory=list, max_length=12)


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    REVISION_REQUIRED = "revision_required"


ReviewSeverity = Literal["critical", "high", "medium", "low"]


class ReviewFinding(StrictModel):
    """One evidence-linked architecture issue and its concrete correction."""

    severity: ReviewSeverity
    category: str = Field(min_length=2, max_length=80)
    issue: str = Field(min_length=5, max_length=600)
    recommendation: str = Field(min_length=5, max_length=600)


class ArchitectureReview(StrictModel):
    """The reviewer's structured high-availability verdict."""

    decision: ReviewDecision
    summary: str = Field(min_length=10, max_length=1000)
    strengths: list[str] = Field(default_factory=list, max_length=12)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=16)
    required_changes: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def decision_matches_required_changes(self) -> "ArchitectureReview":
        if self.decision is ReviewDecision.APPROVED and self.required_changes:
            raise ValueError("approved reviews cannot contain required_changes")
        if (
            self.decision is ReviewDecision.REVISION_REQUIRED
            and not self.required_changes
        ):
            raise ValueError("revision_required reviews need at least one required change")
        return self
