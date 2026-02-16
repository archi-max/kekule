"""
Rule CRUD endpoints.

Rules are structured acceptance criteria that gate waypoints.
All rules belong to a project.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import CreateRuleRequest, Rule, UpdateRuleRequest

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _state(request: Request):
    return request.app.state.app_state


@router.get("", response_model=list[Rule])
async def list_rules(
    request: Request,
    project_id: str | None = Query(default=None, description="Filter by project ID"),
):
    """List all rules, optionally filtered by project."""
    return _state(request).list_rules(project_id=project_id)


@router.get("/{rule_id}", response_model=Rule)
async def get_rule(rule_id: str, request: Request):
    """Get a single rule by ID."""
    rule = _state(request).get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return rule


@router.post("", response_model=Rule, status_code=201)
async def create_rule(body: CreateRuleRequest, request: Request):
    """Create a new rule within a project."""
    state = _state(request)
    if state.get_project(body.project_id) is None:
        raise HTTPException(status_code=400, detail=f"Project {body.project_id} not found")

    rule = Rule(
        project_id=body.project_id,
        description=body.description,
        oracle_type=body.oracle_type,
        oracle_config=body.oracle_config,
        uncertainty=body.uncertainty,
        waypoint_id=body.waypoint_id,
    )
    return state.add_rule(rule)


@router.put("/{rule_id}", response_model=Rule)
async def update_rule(rule_id: str, body: UpdateRuleRequest, request: Request):
    """Update an existing rule."""
    updates = body.model_dump(exclude_none=True)
    rule = _state(request).update_rule(rule_id, updates)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, request: Request):
    """Delete a rule."""
    if not _state(request).delete_rule(rule_id):
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
