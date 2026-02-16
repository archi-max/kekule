"""Schemas for the multi-agent rule elicitation pipeline."""

from enum import Enum

from pydantic import BaseModel, Field

from ..schemas import Rule


class Priority(str, Enum):
    """Priority level for a requirement."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Requirement(BaseModel):
    """A single user requirement before it becomes a Rule."""

    description: str = Field(..., description="What the user wants verified")
    priority: Priority = Field(
        default=Priority.MEDIUM, description="How important this is"
    )
    area: str = Field(
        default="", description="Which part of the codebase (e.g., 'auth', 'database')"
    )
    measurable: bool = Field(
        default=False,
        description="Whether this has concrete pass/fail criteria yet",
    )


class Intent(BaseModel):
    """Structured output from the conversation phase."""

    summary: str = Field(
        ..., description="What the user wants verified overall"
    )
    priorities: list[str] = Field(
        default_factory=list, description="Ordered list of what matters most"
    )
    requirements: list[Requirement] = Field(
        default_factory=list, description="Concrete things to verify"
    )
    context: str = Field(
        default="", description="Relevant background the user provided"
    )


class ReviewQuestion(BaseModel):
    """A gap found by the reviewer."""

    rule_id: str = Field(..., description="Which rule has the gap")
    question: str = Field(..., description="What's missing or ambiguous")
    category: str = Field(
        default="general",
        description="Gap type: missing_threshold, ambiguous_scope, no_boundary, conflicting",
    )
    auto_resolvable: bool = Field(
        default=False,
        description="Can the rule agent figure this out from code?",
    )
    suggested_resolution: str | None = Field(
        default=None,
        description="Reviewer's best guess if auto_resolvable",
    )


class ReviewResult(BaseModel):
    """Output from the review phase."""

    approved_rules: list[Rule] = Field(
        default_factory=list, description="Rules that passed review"
    )
    questions: list[ReviewQuestion] = Field(
        default_factory=list, description="Gaps that need resolution"
    )
    auto_resolved: list[str] = Field(
        default_factory=list,
        description="Rule IDs that were improved automatically",
    )
