"""
Waypoint endpoints.

Waypoints are intermediate verifiable checkpoints in the development path.
All waypoints belong to a project.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import (
    ApproveWaypointRequest,
    CreateWaypointRequest,
    RejectWaypointRequest,
    Waypoint,
    WaypointStatus,
)

router = APIRouter(prefix="/api/waypoints", tags=["waypoints"])


def _state(request: Request):
    return request.app.state.app_state


@router.get("", response_model=list[Waypoint])
async def list_waypoints(
    request: Request,
    project_id: str | None = Query(default=None, description="Filter by project ID"),
):
    """Get the waypoint DAG, optionally filtered by project."""
    return _state(request).list_waypoints(project_id=project_id)


@router.get("/{waypoint_id}", response_model=Waypoint)
async def get_waypoint(waypoint_id: str, request: Request):
    """Get a single waypoint with its rules and status."""
    wp = _state(request).get_waypoint(waypoint_id)
    if wp is None:
        raise HTTPException(status_code=404, detail=f"Waypoint {waypoint_id} not found")
    return wp


@router.post("", response_model=Waypoint, status_code=201)
async def create_waypoint(body: CreateWaypointRequest, request: Request):
    """Create a new waypoint within a project."""
    state = _state(request)

    if state.get_project(body.project_id) is None:
        raise HTTPException(status_code=400, detail=f"Project {body.project_id} not found")

    for rid in body.rule_ids:
        if state.get_rule(rid) is None:
            raise HTTPException(status_code=400, detail=f"Rule {rid} not found")

    if body.parent_waypoint_id and state.get_waypoint(body.parent_waypoint_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Parent waypoint {body.parent_waypoint_id} not found",
        )

    waypoint = Waypoint(
        project_id=body.project_id,
        description=body.description,
        rule_ids=body.rule_ids,
        parent_waypoint_id=body.parent_waypoint_id,
    )

    if state.tracker_connected:
        try:
            result = await state.tracker.create_task(
                title=body.description,
                description=f"Waypoint: {waypoint.id}",
            )
            if result and "id" in result:
                waypoint.beads_task_id = result["id"]
        except Exception:
            pass

    return state.add_waypoint(waypoint)


@router.post("/{waypoint_id}/approve", response_model=Waypoint)
async def approve_waypoint(
    waypoint_id: str, body: ApproveWaypointRequest, request: Request
):
    """Approve a waypoint gate, optionally recording the git ref."""
    state = _state(request)
    updates = {"status": WaypointStatus.passed}
    if body.git_ref:
        updates["git_ref"] = body.git_ref

    wp = state.update_waypoint(waypoint_id, updates)
    if wp is None:
        raise HTTPException(status_code=404, detail=f"Waypoint {waypoint_id} not found")
    return wp


@router.post("/{waypoint_id}/reject", response_model=Waypoint)
async def reject_waypoint(
    waypoint_id: str, body: RejectWaypointRequest, request: Request
):
    """Reject a waypoint, triggering re-work."""
    state = _state(request)
    wp = state.update_waypoint(waypoint_id, {"status": WaypointStatus.failed})
    if wp is None:
        raise HTTPException(status_code=404, detail=f"Waypoint {waypoint_id} not found")
    return wp
