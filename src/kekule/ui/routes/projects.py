"""
Project CRUD endpoints.

Projects are the top-level grouping for rules, waypoints, and swarm runs.
"""

from fastapi import APIRouter, HTTPException, Request

from ..models import CreateProjectRequest, Project, UpdateProjectRequest

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _state(request: Request):
    return request.app.state.app_state


@router.get("", response_model=list[Project])
async def list_projects(request: Request):
    """List all projects."""
    return _state(request).list_projects()


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, request: Request):
    """Get a single project by ID."""
    project = _state(request).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@router.post("", response_model=Project, status_code=201)
async def create_project(body: CreateProjectRequest, request: Request):
    """Create a new project."""
    project = Project(name=body.name, description=body.description)
    return _state(request).add_project(project)


@router.put("/{project_id}", response_model=Project)
async def update_project(project_id: str, body: UpdateProjectRequest, request: Request):
    """Update an existing project."""
    updates = body.model_dump(exclude_none=True)
    project = _state(request).update_project(project_id, updates)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, request: Request):
    """Delete a project."""
    if not _state(request).delete_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
