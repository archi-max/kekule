"""
Schemas for the Oracle Generator.

Pydantic models for Rules (structured acceptance criteria), OracleResults
(pass/fail with evidence), and OracleRunRequests (orchestration input).
"""

from enum import Enum

from pydantic import BaseModel, Field


class OracleType(str, Enum):
    """Supported oracle artifact types."""

    PYTEST = "pytest"


class RuleStatus(str, Enum):
    """Lifecycle status of a Rule."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    VERIFIED = "verified"


class Rule(BaseModel):
    """A single verification rule -- structured acceptance criteria
    that the oracle agent transforms into an executable test."""

    id: str = Field(..., description="Unique rule identifier")
    description: str = Field(
        ..., description="Human-readable description of what to verify"
    )
    oracle_type: OracleType = Field(
        default=OracleType.PYTEST,
        description="Type of oracle artifact to generate",
    )
    oracle_config: dict = Field(
        default_factory=dict,
        description="Type-specific configuration (e.g., target module, fixtures needed)",
    )
    uncertainty: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in rule clarity: 0.0 = certain, 1.0 = vague",
    )
    status: RuleStatus = Field(
        default=RuleStatus.DRAFT,
        description="Lifecycle status of this rule",
    )


class OracleResult(BaseModel):
    """Result of executing a single oracle artifact against a codebase."""

    rule_id: str = Field(..., description="The rule this result corresponds to")
    passed: bool = Field(..., description="Whether the oracle passed")
    evidence: str = Field(
        default="", description="Combined stdout/stderr from execution"
    )
    artifact_path: str = Field(
        default="", description="Path to the test file that was executed"
    )
    execution_time_s: float = Field(
        default=0.0, description="Wall-clock execution time in seconds"
    )
    exit_code: int = Field(default=-1, description="Process exit code (0 = pass)")


class OracleRunRequest(BaseModel):
    """Request to generate and/or run oracles against a codebase."""

    repo_url: str | None = Field(
        default=None, description="Git remote URL (cloned if provided)"
    )
    repo_path: str | None = Field(
        default=None, description="Local path to repo (used as-is)"
    )
    git_commit: str | None = Field(
        default=None,
        description="Git commit SHA to checkout (required if repo_url is provided)",
    )
    rules: list[Rule] = Field(..., description="Rules to generate oracles for")
    docker_image: str = Field(
        default="python:3.11-slim",
        description="Base Docker image for oracle execution",
    )
    timeout_s: int = Field(
        default=300, description="Max seconds per oracle container"
    )
