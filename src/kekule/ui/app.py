"""
Oracle Dashboard FastAPI application.

Provides the REST API layer over kekule.oracle (generation + execution),
SwarmBus, BeadsTracker, and the rules/waypoints/oracle data stores.

Usage:
    cd /workspaces/kekule
    python3 -m uvicorn kekule.ui.app:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .state import AppState
from .routes import benchmarks, experiments, projects, rules, waypoints, swarm, oracle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down application state."""
    logger.info("Oracle Dashboard backend starting...")
    app.state.app_state = AppState()
    logger.info(
        f"State initialized: "
        f"{len(app.state.app_state.projects)} projects, "
        f"{len(app.state.app_state.rules)} rules, "
        f"{len(app.state.app_state.waypoints)} waypoints loaded"
    )
    yield
    logger.info("Oracle Dashboard backend shutting down")


app = FastAPI(
    title="Oracle Dashboard API",
    description=(
        "REST API for the Kekule Oracle Dashboard. "
        "Provides project management, rule elicitation, waypoint tracking, "
        "swarm monitoring, and oracle generation + execution endpoints. "
        "Integrates with kekule.oracle for Claude Agent SDK-powered "
        "verification artifact generation and Docker-based execution."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(benchmarks.router)
app.include_router(experiments.router)
app.include_router(projects.router)
app.include_router(rules.router)
app.include_router(waypoints.router)
app.include_router(swarm.router)
app.include_router(oracle.router)


@app.get("/", include_in_schema=False)
async def root_redirect():
    """Redirect root to benchmarks dashboard."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/benchmarks")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    state = app.state.app_state
    return {
        "status": "ok",
        "projects_count": len(state.projects),
        "rules_count": len(state.rules),
        "waypoints_count": len(state.waypoints),
        "bus_connected": state.bus_connected,
        "tracker_connected": state.tracker_connected,
    }
