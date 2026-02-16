"""
Swarm monitoring endpoints.

Reads real-time agent status and messages from the live SwarmBus.
"""

from fastapi import APIRouter, Request

from ..models import AgentStatus, SwarmMessageOut

router = APIRouter(prefix="/api/swarm", tags=["swarm"])


def _state(request: Request):
    return request.app.state.app_state


@router.get("/status", response_model=list[AgentStatus])
async def get_swarm_status(request: Request):
    """Get current status of all swarm agents."""
    state = _state(request)
    if not state.bus_connected:
        return []
    return [AgentStatus(**a) for a in state.get_agent_statuses()]


@router.get("/messages", response_model=list[SwarmMessageOut])
async def get_swarm_messages(request: Request, since: int = 0, limit: int = 100):
    """Get recent SwarmBus messages with cursor-based pagination."""
    state = _state(request)
    if not state.bus_connected:
        return []
    return [SwarmMessageOut(**m) for m in state.get_swarm_messages(since=since, limit=limit)]


@router.get("/connected")
async def get_connection_status(request: Request):
    """Check if SwarmBus and BeadsTracker are connected."""
    state = _state(request)
    return {
        "bus_connected": state.bus_connected,
        "tracker_connected": state.tracker_connected,
    }
