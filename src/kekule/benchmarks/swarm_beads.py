"""
Beads (bd) integration for structured work item tracking in the swarm.

Wraps the `bd` CLI for creating, tracking, and resolving tasks with
dependency awareness. Also provides an SDK MCP server so agents can
interact with beads via tool calls (swarm_claim_task, swarm_ready, etc.).
"""

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from .swarm_bus import SwarmBus

logger = logging.getLogger(__name__)

# Map role dependency pairs to bd dep semantics.
# bd dep add A B  means "A depends on B" (B must finish before A can start).


class BeadsTracker:
    """
    Wraps the `bd` CLI for structured work item tracking.

    All commands run as async subprocesses so they don't block the event loop.
    """

    def __init__(self, repo_dir: Path):
        self._repo_dir = repo_dir
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        """Check if the bd binary is available on PATH."""
        return shutil.which("bd") is not None

    async def init(self, prefix: str = "swarm") -> bool:
        """Initialize beads in the workspace. Returns True on success."""
        if not self.available:
            logger.warning("[beads] bd binary not found on PATH, skipping init")
            return False

        async with self._lock:
            result = await self._run("init", "--prefix", prefix)
            if result is not None:
                self._initialized = True
                logger.info(f"[beads] Initialized with prefix '{prefix}'")
                return True
            return False

    async def create_task(
        self, title: str, description: str = ""
    ) -> dict[str, Any] | None:
        """Create a new beads task. Returns the JSON response or None."""
        args = ["create", title, "-t", "task", "-p", "0", "--json"]
        if description:
            args.extend([f"--description={description}"])
        return await self._run_json(*args)

    async def add_dependency(
        self, from_id: str, to_id: str, dep_type: str = "blocks"
    ) -> dict[str, Any] | None:
        """
        Add a dependency: from_id depends on to_id.

        This means to_id must complete before from_id can start.
        """
        return await self._run_json(
            "dep", "add", from_id, to_id, "--type", dep_type, "--json"
        )

    async def ready(self) -> list[dict[str, Any]]:
        """Get tasks that are unblocked and ready to work on."""
        result = await self._run_json("ready", "--json")
        if isinstance(result, list):
            return result
        return []

    async def blocked(self) -> list[dict[str, Any]]:
        """Get tasks that are blocked by other tasks."""
        result = await self._run_json("blocked", "--json")
        if isinstance(result, list):
            return result
        return []

    async def list_tasks(self) -> list[dict[str, Any]]:
        """List all open tasks."""
        result = await self._run_json("list", "--json")
        if isinstance(result, list):
            return result
        return []

    async def update_status(
        self, task_id: str, status: str
    ) -> dict[str, Any] | None:
        """Update a task's status (e.g. 'in_progress')."""
        return await self._run_json(
            "update", task_id, "--status", status, "--json"
        )

    async def close_task(
        self, task_id: str, reason: str = "done"
    ) -> dict[str, Any] | None:
        """Close a task with a reason. Uses --force to bypass dep checks."""
        return await self._run_json(
            "close", task_id, "--reason", reason, "--force", "--json"
        )

    async def _run(self, *args: str) -> str | None:
        """Run a bd command and return stdout, or None on failure."""
        cmd = ["bd", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._repo_dir),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30
            )
            stdout_str = stdout.decode().strip() if stdout else ""
            if proc.returncode != 0:
                stderr_str = stderr.decode().strip() if stderr else ""
                logger.debug(
                    f"[beads] Command failed: {' '.join(cmd)} -> {stderr_str}"
                )
                return None
            return stdout_str
        except asyncio.TimeoutError:
            logger.warning(f"[beads] Timeout running: {' '.join(cmd)}")
            return None
        except Exception as e:
            logger.warning(f"[beads] Error running {' '.join(cmd)}: {e}")
            return None

    async def _run_json(self, *args: str) -> Any:
        """Run a bd command and parse JSON output."""
        raw = await self._run(*args)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Some bd commands emit warnings before JSON; try to find JSON
            for line_start in range(len(raw)):
                if raw[line_start] in ("{", "["):
                    try:
                        return json.loads(raw[line_start:])
                    except json.JSONDecodeError:
                        continue
            logger.debug(f"[beads] Could not parse JSON from: {raw[:200]}")
            return None


async def create_role_tasks(
    tracker: BeadsTracker,
    roles: list[dict],
    dependencies: list[list[str]] | None = None,
) -> dict[str, str]:
    """
    Create beads tasks from planner roles and wire up dependencies.

    Args:
        tracker: BeadsTracker instance
        roles: List of role dicts with 'name' and 'goal' keys
        dependencies: List of [from_role, to_role] pairs meaning
                      from_role depends on to_role (to_role must finish first)

    Returns:
        Mapping of role_name -> beads task ID
    """
    role_to_id: dict[str, str] = {}

    for role in roles:
        result = await tracker.create_task(
            title=role["goal"],
            description=f"Role: {role['name']}",
        )
        if result and "id" in result:
            role_to_id[role["name"]] = result["id"]
            logger.info(
                f"[beads] Created task {result['id']} for role '{role['name']}'"
            )

    # Wire up dependencies
    if dependencies:
        for from_role, to_role in dependencies:
            from_id = role_to_id.get(from_role)
            to_id = role_to_id.get(to_role)
            if from_id and to_id:
                await tracker.add_dependency(from_id, to_id)
                logger.info(
                    f"[beads] {from_role} ({from_id}) depends on "
                    f"{to_role} ({to_id})"
                )

    return role_to_id


def build_swarm_mcp_server(
    bus: SwarmBus,
    tracker: BeadsTracker,
    agent_num: int,
) -> Any:
    """
    Build an SDK MCP server with swarm communication + beads tools.

    Tools provided:
      - swarm_broadcast: Post a message to the SwarmBus
      - swarm_read_updates: Read new messages from the bus
      - swarm_claim_task: Claim a beads task (set to in_progress)
      - swarm_create_task: Create a new beads task
      - swarm_add_dep: Add a dependency between beads tasks
      - swarm_ready: List unblocked beads tasks
      - swarm_blocked: List blocked beads tasks
      - swarm_complete_task: Close a beads task

    Returns:
        McpSdkServerConfig dict for use in ClaudeAgentOptions.mcp_servers
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool

    @tool(
        "swarm_broadcast",
        "Broadcast an important message to all other agents in the swarm. "
        "Use this for findings, status updates, and coordination.",
        {"message": str, "category": str},
    )
    async def swarm_broadcast(args: dict) -> dict:
        message = args.get("message", "")
        category = args.get("category", "broadcast")
        await bus.post(agent_num, category, message)
        return {
            "content": [
                {"type": "text", "text": f"Broadcast sent: [{category}] {message}"}
            ]
        }

    @tool(
        "swarm_read_updates",
        "Read new messages from other agents since your last read. "
        "Returns recent activity from teammates.",
        {"type": "object", "properties": {}, "required": []},
    )
    async def swarm_read_updates(args: dict) -> dict:
        updates = await bus.get_updates_for(agent_num)
        if not updates:
            return {
                "content": [{"type": "text", "text": "No new updates from teammates."}]
            }
        lines = []
        for msg in updates:
            lines.append(
                f"[{msg.category}] agent-{msg.agent_num} ({msg.role}): {msg.content}"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "swarm_claim_task",
        "Claim a beads work item by setting its status to in_progress. "
        "This tells other agents you own this task.",
        {"task_id": str},
    )
    async def swarm_claim_task(args: dict) -> dict:
        task_id = args.get("task_id", "")
        result = await tracker.update_status(task_id, "in_progress")
        if result:
            await bus.post(
                agent_num, "status", f"Claimed task {task_id}"
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Claimed task {task_id}. You own this work item.",
                    }
                ]
            }
        return {
            "content": [
                {"type": "text", "text": f"Failed to claim task {task_id}."}
            ],
            "is_error": True,
        }

    @tool(
        "swarm_create_task",
        "Create a new beads work item when you discover additional work needed.",
        {"title": str, "description": str},
    )
    async def swarm_create_task(args: dict) -> dict:
        title = args.get("title", "")
        description = args.get("description", "")
        result = await tracker.create_task(title, description)
        if result and "id" in result:
            await bus.post(
                agent_num,
                "task",
                f"Created task {result['id']}: {title}",
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Created task {result['id']}: {title}",
                    }
                ]
            }
        return {
            "content": [
                {"type": "text", "text": f"Failed to create task: {title}"}
            ],
            "is_error": True,
        }

    @tool(
        "swarm_add_dep",
        "Add a dependency between beads tasks. "
        "from_task depends on to_task (to_task must finish first).",
        {"from_task": str, "to_task": str},
    )
    async def swarm_add_dep(args: dict) -> dict:
        from_task = args.get("from_task", "")
        to_task = args.get("to_task", "")
        result = await tracker.add_dependency(from_task, to_task)
        if result:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Dependency added: {from_task} depends on {to_task}",
                    }
                ]
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Failed to add dependency: {from_task} -> {to_task}",
                }
            ],
            "is_error": True,
        }

    @tool(
        "swarm_ready",
        "List beads tasks that are unblocked and ready to work on. "
        "Check this before starting new work.",
        {"type": "object", "properties": {}, "required": []},
    )
    async def swarm_ready(args: dict) -> dict:
        tasks = await tracker.ready()
        if not tasks:
            return {
                "content": [
                    {"type": "text", "text": "No unblocked tasks available."}
                ]
            }
        lines = []
        for t in tasks:
            lines.append(
                f"- {t['id']}: {t.get('title', '?')} "
                f"[{t.get('status', '?')}]"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "swarm_blocked",
        "List beads tasks that are blocked by other tasks. "
        "Shows what's waiting and what blocks it.",
        {"type": "object", "properties": {}, "required": []},
    )
    async def swarm_blocked(args: dict) -> dict:
        tasks = await tracker.blocked()
        if not tasks:
            return {
                "content": [
                    {"type": "text", "text": "No blocked tasks."}
                ]
            }
        lines = []
        for t in tasks:
            blocked_by = t.get("blocked_by", [])
            lines.append(
                f"- {t['id']}: {t.get('title', '?')} "
                f"[blocked by: {', '.join(blocked_by)}]"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "swarm_complete_task",
        "Mark a beads task as completed. This unblocks dependent tasks. "
        "Only use when the work is truly done.",
        {"task_id": str, "reason": str},
    )
    async def swarm_complete_task(args: dict) -> dict:
        task_id = args.get("task_id", "")
        reason = args.get("reason", "done")
        result = await tracker.close_task(task_id, reason)
        if result:
            await bus.post(
                agent_num,
                "status",
                f"Completed task {task_id}: {reason}",
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Task {task_id} closed ({reason}). "
                            "Dependent tasks may now be unblocked."
                        ),
                    }
                ]
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Failed to close task {task_id}.",
                }
            ],
            "is_error": True,
        }

    server = create_sdk_mcp_server(
        name="swarm",
        version="1.0.0",
        tools=[
            swarm_broadcast,
            swarm_read_updates,
            swarm_claim_task,
            swarm_create_task,
            swarm_add_dep,
            swarm_ready,
            swarm_blocked,
            swarm_complete_task,
        ],
    )

    return server


# Tool names for allowed_tools (without mcp__swarm__ prefix — the SDK adds it)
SWARM_MCP_TOOL_NAMES = [
    "mcp__swarm__swarm_broadcast",
    "mcp__swarm__swarm_read_updates",
    "mcp__swarm__swarm_claim_task",
    "mcp__swarm__swarm_create_task",
    "mcp__swarm__swarm_add_dep",
    "mcp__swarm__swarm_ready",
    "mcp__swarm__swarm_blocked",
    "mcp__swarm__swarm_complete_task",
]
