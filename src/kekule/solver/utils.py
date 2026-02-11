"""
Utility functions for the Expert Solver Agent.
"""

import os
import json
from pathlib import Path
from datetime import datetime


def get_env_path(env_var: str, default: str) -> Path:
    """Get a path from environment variable or use default."""
    return Path(os.environ.get(env_var, default))


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_input_dir() -> Path:
    return get_env_path("EXPERT_SOLVER_INPUT_DIR", "./input")


def get_output_dir() -> Path:
    return ensure_dir(get_env_path("EXPERT_SOLVER_OUTPUT_DIR", "./output"))


def get_status_dir() -> Path:
    return ensure_dir(get_env_path("EXPERT_SOLVER_STATUS_DIR", "./status"))


def get_workspace_dir() -> Path:
    return ensure_dir(get_env_path("EXPERT_SOLVER_WORKSPACE_DIR", "./workspace"))


def get_config_path() -> Path:
    return get_env_path("EXPERT_SOLVER_CONFIG", "./config/mcp_servers.json")


def load_mcp_config() -> dict:
    """Load MCP server configuration."""
    config_path = get_config_path()
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {"mcpServers": {}}


def update_status(status: str, details: dict | None = None) -> None:
    """Update the runtime status file."""
    status_file = get_status_dir() / "STATUS.md"
    timestamp = datetime.now().isoformat()

    content = [
        "# Expert Solver - Runtime Status",
        "",
        f"**Last Updated**: {timestamp}",
        f"**Status**: {status}",
        "",
    ]

    if details:
        content.append("## Details")
        content.append("")
        for key, value in details.items():
            content.append(f"- **{key}**: {value}")
        content.append("")

    with open(status_file, "w") as f:
        f.write("\n".join(content))


def log_step(step: str) -> None:
    """Append a step to the status log."""
    status_file = get_status_dir() / "STATUS.md"
    timestamp = datetime.now().strftime("%H:%M:%S")

    with open(status_file, "a") as f:
        f.write(f"\n- [{timestamp}] {step}")
