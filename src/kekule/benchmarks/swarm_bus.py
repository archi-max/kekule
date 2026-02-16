"""
In-memory message bus for inter-agent communication in the perturbation swarm.

Provides a shared, thread-safe (asyncio) message bus that agents can post to
and read from. Messages are cursor-based so each agent only sees new messages
since its last read. Also syncs messages to the filesystem ledger for persistence.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SwarmMessage:
    """A single message on the swarm bus."""

    agent_num: int
    role: str
    category: str  # e.g. "finding", "status", "file_activity", "broadcast"
    content: str
    timestamp: float = field(default_factory=time.time)
    seq: int = 0  # Set by SwarmBus on post


class SwarmBus:
    """
    Shared in-process message bus for swarm agents.

    All agents run concurrently in the same event loop (asyncio.gather),
    so a shared object with asyncio.Lock is safe.
    """

    def __init__(self, num_agents: int, ledger_dir: Path | None = None):
        self._messages: list[SwarmMessage] = []
        self._cursors: dict[int, int] = {}  # agent_num -> last read seq
        self._statuses: dict[int, str] = {}  # agent_num -> phase
        self._current_files: dict[int, str] = {}  # agent_num -> filepath
        self._roles: dict[int, str] = {}  # agent_num -> role name
        self._lock = asyncio.Lock()
        self._seq = 0
        self._num_agents = num_agents
        self._ledger_dir = ledger_dir

    def set_role(self, agent_num: int, role: str) -> None:
        """Register an agent's role name."""
        self._roles[agent_num] = role

    async def post(self, agent_num: int, category: str, content: str) -> None:
        """Broadcast a message from an agent."""
        async with self._lock:
            self._seq += 1
            msg = SwarmMessage(
                agent_num=agent_num,
                role=self._roles.get(agent_num, f"agent-{agent_num}"),
                category=category,
                content=content,
                seq=self._seq,
            )
            self._messages.append(msg)

        # Write to filesystem ledger (fire-and-forget)
        if self._ledger_dir:
            try:
                self._sync_to_ledger(msg)
            except Exception:
                pass  # Never let IO errors break the bus

    def _sync_to_ledger(self, msg: SwarmMessage) -> None:
        """Append a message to the shared BROADCAST.md ledger file."""
        broadcast_file = self._ledger_dir / "BROADCAST.md"
        with open(broadcast_file, "a") as f:
            f.write(
                f"\n[{msg.category}] agent-{msg.agent_num} ({msg.role}): "
                f"{msg.content}\n"
            )

    async def get_updates_for(self, agent_num: int) -> list[SwarmMessage]:
        """Get new messages from other agents since last read (cursor-based)."""
        async with self._lock:
            cursor = self._cursors.get(agent_num, 0)
            updates = [
                m
                for m in self._messages
                if m.seq > cursor and m.agent_num != agent_num
            ]
            if updates:
                self._cursors[agent_num] = updates[-1].seq
            return updates

    async def update_status(self, agent_num: int, status: str) -> None:
        """Track an agent's current phase."""
        async with self._lock:
            self._statuses[agent_num] = status

    async def set_current_file(self, agent_num: int, filepath: str) -> None:
        """Track what file an agent is currently working on."""
        async with self._lock:
            self._current_files[agent_num] = filepath

    async def get_swarm_summary(self, for_agent: int) -> str:
        """
        Build a formatted summary of all other agents' activity.

        Returns a string suitable for injection into additionalContext.
        """
        async with self._lock:
            cursor = self._cursors.get(for_agent, 0)
            new_messages = [
                m
                for m in self._messages
                if m.seq > cursor and m.agent_num != for_agent
            ]
            # Update cursor
            if new_messages:
                self._cursors[for_agent] = new_messages[-1].seq

        lines = ["## SWARM STATUS UPDATE\n"]

        # Agent statuses
        lines.append("### Agent Phases")
        for i in range(self._num_agents):
            if i == for_agent:
                continue
            status = self._statuses.get(i, "unknown")
            role = self._roles.get(i, f"agent-{i}")
            current_file = self._current_files.get(i, "")
            file_info = f" (working on: {current_file})" if current_file else ""
            lines.append(f"- agent-{i} ({role}): **{status}**{file_info}")

        # Recent messages
        if new_messages:
            lines.append("\n### Recent Activity")
            # Show last 15 messages to keep context manageable
            for msg in new_messages[-15:]:
                lines.append(
                    f"- [{msg.category}] agent-{msg.agent_num} ({msg.role}): "
                    f"{msg.content}"
                )

        lines.append("")
        return "\n".join(lines)
