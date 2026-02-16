"""
Oracle endpoints.

Integrates with kekule.oracle for:
  - Generating oracle artifacts (pytest tests) from rules via Claude Agent SDK
  - Running oracles in Docker containers
  - Eliciting rules from a codebase
  - User overrides with audit trail
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from ..models import (
    CreateOverrideRequest,
    ElicitRulesRequest,
    OracleResult,
    Override,
    Rule,
    RunOracleRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oracle", tags=["oracle"])


def _state(request: Request):
    return request.app.state.app_state


@router.get("/{waypoint_id}", response_model=list[OracleResult])
async def get_oracle_results(waypoint_id: str, request: Request):
    """Get oracle results for a specific waypoint."""
    state = _state(request)
    if state.get_waypoint(waypoint_id) is None:
        raise HTTPException(status_code=404, detail=f"Waypoint {waypoint_id} not found")
    return state.get_oracle_results(waypoint_id)


@router.post("/{waypoint_id}/run")
async def run_oracle_battery(
    waypoint_id: str, body: RunOracleRequest, request: Request
):
    """
    Generate oracle artifacts and run them in Docker for a waypoint.

    This calls kekule.oracle.agent.generate_all_oracles() to create pytest
    test files from the waypoint's rules, then kekule.oracle.runner.run_oracles()
    to execute them in isolated Docker containers.

    Requires Docker to be available on the host.
    """
    state = _state(request)
    wp = state.get_waypoint(waypoint_id)
    if wp is None:
        raise HTTPException(status_code=404, detail=f"Waypoint {waypoint_id} not found")

    if not wp.rule_ids:
        raise HTTPException(
            status_code=400, detail=f"Waypoint {waypoint_id} has no rules"
        )

    # Gather the oracle Rule objects for this waypoint
    oracle_rules = []
    for rid in wp.rule_ids:
        rule = state.get_rule(rid)
        if rule is None:
            raise HTTPException(status_code=400, detail=f"Rule {rid} not found")
        oracle_rules.append(rule.to_oracle_rule())

    from kekule.oracle.agent import generate_all_oracles
    from kekule.oracle.runner import run_oracles
    from kekule.oracle.schemas import OracleRunRequest as OracleRunReq

    # Step 1: Generate oracle artifacts
    logger.info(
        f"Generating oracle artifacts for waypoint {waypoint_id} "
        f"({len(oracle_rules)} rules)..."
    )
    try:
        artifact_paths = await generate_all_oracles(
            rules=oracle_rules,
            repo_path=body.repo_path,
            model=body.model,
            max_parallel=body.max_parallel,
        )
    except Exception as e:
        logger.error(f"Oracle generation failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Oracle generation failed: {e}"
        )

    if not artifact_paths:
        raise HTTPException(
            status_code=500,
            detail="No oracle artifacts were generated",
        )

    # Step 2: Run oracles in Docker
    logger.info(f"Running {len(artifact_paths)} oracles in Docker...")
    run_request = OracleRunReq(
        repo_path=body.repo_path,
        git_commit=body.git_commit,
        rules=oracle_rules,
        docker_image=body.docker_image,
        timeout_s=body.timeout_s,
    )

    try:
        raw_results = await run_oracles(
            request=run_request,
            artifact_paths=artifact_paths,
            max_parallel=body.max_parallel,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Step 3: Convert and store results
    results = []
    for raw in raw_results:
        result = OracleResult.from_oracle_result(raw, waypoint_id)
        state.add_oracle_result(result)
        results.append(result)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    return {
        "waypoint_id": waypoint_id,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": [r.model_dump(mode="json") for r in results],
    }


@router.post("/elicit", response_model=list[Rule], status_code=201)
async def elicit_rules_endpoint(body: ElicitRulesRequest, request: Request):
    """
    Elicit rules from a codebase using Claude Agent SDK.

    The elicitor agent explores the repo, understands the codebase, and
    proposes concrete verification rules. Results are saved to the project.
    """
    state = _state(request)
    if state.get_project(body.project_id) is None:
        raise HTTPException(
            status_code=400, detail=f"Project {body.project_id} not found"
        )

    logger.info(
        f"Eliciting rules for project {body.project_id} "
        f"from {body.repo_path}..."
    )

    from kekule.oracle.elicitor import elicit_rules

    try:
        oracle_rules = await elicit_rules(
            repo_path=body.repo_path,
            user_intent=body.user_intent,
            model=body.model,
        )
    except Exception as e:
        logger.error(f"Rule elicitation failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Rule elicitation failed: {e}"
        )

    # Convert oracle rules to UI rules and save
    saved_rules = []
    for oracle_rule in oracle_rules:
        rule = Rule(
            id=oracle_rule.id,
            project_id=body.project_id,
            description=oracle_rule.description,
            oracle_type=oracle_rule.oracle_type.value,
            oracle_config=oracle_rule.oracle_config,
            uncertainty=oracle_rule.uncertainty,
            status=oracle_rule.status.value,
        )
        state.add_rule(rule)
        saved_rules.append(rule)

    return saved_rules


@router.post("/override", response_model=Override, status_code=201)
async def create_override(body: CreateOverrideRequest, request: Request):
    """Create a user override for an oracle result (audit trail)."""
    state = _state(request)

    if state.get_rule(body.rule_id) is None:
        raise HTTPException(status_code=400, detail=f"Rule {body.rule_id} not found")
    if state.get_waypoint(body.waypoint_id) is None:
        raise HTTPException(
            status_code=400, detail=f"Waypoint {body.waypoint_id} not found"
        )

    override = Override(
        rule_id=body.rule_id,
        waypoint_id=body.waypoint_id,
        rationale=body.rationale,
        user=body.user,
    )
    return state.add_override(override)


@router.get("/overrides/all", response_model=list[Override])
async def list_overrides(request: Request):
    """List all user overrides (audit trail)."""
    return _state(request).list_overrides()
