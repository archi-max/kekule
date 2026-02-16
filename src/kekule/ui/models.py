"""
Pydantic models for the Oracle Dashboard API.

Reuses Rule, OracleResult, OracleRunRequest from kekule.oracle.schemas.
Defines UI-specific models: Project, Waypoint, Override, and request wrappers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# Re-export oracle schemas so routes can import everything from here
from kekule.oracle.schemas import (
    OracleResult as OracleOracleResult,
    OracleRunRequest,
    OracleType,
    Rule as OracleRule,
    RuleStatus,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProjectStatus(str, Enum):
    setup = "setup"
    active = "active"
    completed = "completed"
    archived = "archived"


class WaypointStatus(str, Enum):
    pending = "pending"
    active = "active"
    passed = "passed"
    failed = "failed"


# ---------------------------------------------------------------------------
# Core domain models (UI-specific)
# ---------------------------------------------------------------------------


class Project(BaseModel):
    """A top-level project that groups rules, waypoints, and swarm runs."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.setup
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Rule(BaseModel):
    """UI Rule model extending the oracle Rule with project scoping.

    Wraps kekule.oracle.schemas.Rule fields and adds project_id + waypoint_id.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_id: str
    description: str
    oracle_type: str = "pytest"
    oracle_config: dict[str, Any] = Field(default_factory=dict)
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    waypoint_id: str | None = None
    status: str = "draft"

    def to_oracle_rule(self) -> OracleRule:
        """Convert to kekule.oracle.schemas.Rule for oracle generation/running."""
        return OracleRule(
            id=self.id,
            description=self.description,
            oracle_type=self.oracle_type,
            oracle_config=self.oracle_config,
            uncertainty=self.uncertainty,
            status=self.status,
        )


class Waypoint(BaseModel):
    """An intermediate verifiable checkpoint in the development path."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_id: str
    description: str
    rule_ids: list[str] = Field(default_factory=list)
    beads_task_id: str | None = None
    git_ref: str | None = None
    status: WaypointStatus = WaypointStatus.pending
    parent_waypoint_id: str | None = None


class OracleResult(BaseModel):
    """Result of running an oracle against a waypoint (UI view)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    rule_id: str
    waypoint_id: str
    passed: bool
    oracle_type: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str = ""
    execution_time_s: float = 0.0
    exit_code: int = -1
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_oracle_result(
        cls, oracle_result: OracleOracleResult, waypoint_id: str
    ) -> "OracleResult":
        """Convert from kekule.oracle.schemas.OracleResult."""
        return cls(
            rule_id=oracle_result.rule_id,
            waypoint_id=waypoint_id,
            passed=oracle_result.passed,
            oracle_type="pytest",
            evidence={
                "output": oracle_result.evidence,
                "exit_code": oracle_result.exit_code,
            },
            artifact_path=oracle_result.artifact_path,
            execution_time_s=oracle_result.execution_time_s,
            exit_code=oracle_result.exit_code,
        )


class Override(BaseModel):
    """User override of an oracle result with rationale (audit trail)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    rule_id: str
    waypoint_id: str
    rationale: str
    user: str = "engineer"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Swarm-related output models
# ---------------------------------------------------------------------------


class AgentStatus(BaseModel):
    """Current status of a single swarm agent."""

    agent_num: int
    role: str
    status: str
    current_file: str = ""


class SwarmMessageOut(BaseModel):
    """Serializable representation of a SwarmBus message."""

    seq: int
    agent_num: int
    role: str
    category: str
    content: str
    timestamp: float


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None


class CreateRuleRequest(BaseModel):
    project_id: str
    description: str
    oracle_type: str = "pytest"
    oracle_config: dict[str, Any] = Field(default_factory=dict)
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    waypoint_id: str | None = None


class UpdateRuleRequest(BaseModel):
    description: str | None = None
    oracle_type: str | None = None
    oracle_config: dict[str, Any] | None = None
    uncertainty: float | None = Field(default=None, ge=0.0, le=1.0)
    waypoint_id: str | None = None
    status: str | None = None


class CreateWaypointRequest(BaseModel):
    project_id: str
    description: str
    rule_ids: list[str] = Field(default_factory=list)
    parent_waypoint_id: str | None = None


class ApproveWaypointRequest(BaseModel):
    git_ref: str | None = None


class RejectWaypointRequest(BaseModel):
    reason: str = ""


class CreateOverrideRequest(BaseModel):
    rule_id: str
    waypoint_id: str
    rationale: str
    user: str = "engineer"


class RunOracleRequest(BaseModel):
    """Request to trigger oracle generation + execution for a waypoint."""

    repo_path: str
    git_commit: str | None = None
    docker_image: str = "python:3.11-slim"
    timeout_s: int = 300
    model: str = "claude-sonnet-4-5"
    max_parallel: int = 3


class ElicitRulesRequest(BaseModel):
    """Request to elicit rules from a repo using Claude Agent SDK."""

    project_id: str
    repo_path: str
    user_intent: str = ""
    model: str = "claude-sonnet-4-5"


# ---------------------------------------------------------------------------
# Benchmark-related models
# ---------------------------------------------------------------------------


class TestStatusBreakdown(BaseModel):
    """Breakdown of test results for a category (e.g., FAIL_TO_PASS)."""

    success: list[str] = Field(default_factory=list)
    failure: list[str] = Field(default_factory=list)


class TaskResultOut(BaseModel):
    """API response for a single task within a benchmark run."""

    instance_id: str
    resolved: bool
    patch_applied: bool
    patch_exists: bool
    fail_to_pass: TestStatusBreakdown = Field(default_factory=TestStatusBreakdown)
    pass_to_pass: TestStatusBreakdown = Field(default_factory=TestStatusBreakdown)
    fail_to_fail: TestStatusBreakdown = Field(default_factory=TestStatusBreakdown)
    pass_to_fail: TestStatusBreakdown = Field(default_factory=TestStatusBreakdown)
    has_test_output: bool = False
    has_agent_logs: bool = False


class BenchmarkRunOut(BaseModel):
    """API response for a benchmark run summary."""

    run_id: str
    model: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    swarm_design: str | None = None
    roles: list[str] | None = None
    perturbation_intensity: float | None = None
    solver: str | None = None
    cost_usd: float | None = None
    duration_s: float | None = None
    tasks: list[TaskResultOut] = Field(default_factory=list)
