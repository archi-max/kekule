"""
PostToolUse hooks for swarm agent communication.

Builds Claude Agent SDK hooks that:
  1. Auto-detect what an agent did (Read, Edit, Bash, etc.) and post to SwarmBus
  2. Periodically inject a SWARM STATUS UPDATE into the agent's context via
     additionalContext so the agent is continuously aware of teammates
  3. Merge with existing tracing hooks from tracing.py
"""

import logging
import time
from typing import Any

from .swarm_bus import SwarmBus
from .tracing import AgentTraceData

logger = logging.getLogger(__name__)

# Test-related patterns in Bash commands
_TEST_PATTERNS = ("pytest", "python -m pytest", "test", "tox", "unittest", "nosetests")


def build_swarm_hooks(
    bus: SwarmBus,
    agent_num: int,
    trace_data: AgentTraceData,
    inject_every: int = 5,
) -> dict:
    """
    Build hooks that combine tracing + swarm communication.

    Every tool call:
      - Logs the tool call to trace_data (tracing)
      - Auto-detects what the agent did and posts to SwarmBus

    Every `inject_every` tool calls:
      - Injects a formatted SWARM STATUS UPDATE into additionalContext
        so the agent sees it alongside the tool result

    Args:
        bus: Shared SwarmBus instance
        agent_num: This agent's number
        trace_data: Tracing data accumulator
        inject_every: How often to inject swarm summary (default: every 5 tool calls)

    Returns:
        A hooks dict suitable for ClaudeAgentOptions.hooks
    """
    from claude_agent_sdk import HookMatcher
    from claude_agent_sdk.types import PostToolUseHookInput, HookContext

    call_count = 0

    async def on_tool_use(
        input_data: PostToolUseHookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1

        result: dict[str, Any] = {}

        try:
            tool_name = input_data.get("tool_name", "unknown")
            tool_input = input_data.get("tool_input", {})

            # --- Tracing (same as build_agent_hooks) ---
            trace_data.tool_calls.append(
                {"tool": tool_name, "timestamp": time.time()}
            )

            # Track ChatOverflow interactions
            if tool_name == "Bash":
                cmd = ""
                if isinstance(tool_input, dict):
                    cmd = tool_input.get("command", "")
                elif isinstance(tool_input, str):
                    cmd = tool_input

                if (
                    "/questions" in cmd
                    or "/forums" in cmd
                    or "chatoverflow" in cmd.lower()
                ):
                    if (
                        "POST" in cmd
                        and "/questions" in cmd
                        and "/answers" not in cmd
                    ):
                        trace_data.chatoverflow_questions += 1
                    elif "POST" in cmd and "/answers" in cmd:
                        trace_data.chatoverflow_answers_received += 1
                    elif "/questions" in cmd:
                        trace_data.chatoverflow_questions += 1

            # --- Auto-detection: post activity to SwarmBus ---
            await _auto_detect_and_post(bus, agent_num, tool_name, tool_input)

            # --- Periodic injection of swarm summary ---
            if call_count % inject_every == 0:
                summary = await bus.get_swarm_summary(for_agent=agent_num)
                if summary.strip():
                    result = {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": summary,
                        }
                    }

        except Exception:
            pass  # Never let hook errors crash the agent

        return result

    return {
        "PostToolUse": [
            HookMatcher(hooks=[on_tool_use]),
        ],
    }


async def _auto_detect_and_post(
    bus: SwarmBus,
    agent_num: int,
    tool_name: str,
    tool_input: Any,
) -> None:
    """Detect what the agent did and post a message to the bus."""
    if isinstance(tool_input, dict):
        input_dict = tool_input
    else:
        input_dict = {}

    if tool_name in ("Read", "Grep", "Glob"):
        filepath = input_dict.get("file_path", "") or input_dict.get("path", "")
        pattern = input_dict.get("pattern", "")
        if filepath:
            await bus.set_current_file(agent_num, filepath)
            await bus.post(
                agent_num, "file_activity", f"examining `{filepath}`"
            )
        elif pattern:
            await bus.post(
                agent_num, "file_activity", f"searching for `{pattern}`"
            )

    elif tool_name in ("Edit", "Write"):
        filepath = input_dict.get("file_path", "")
        if filepath:
            await bus.set_current_file(agent_num, filepath)
            await bus.post(
                agent_num, "file_activity", f"modified `{filepath}`"
            )

    elif tool_name == "Bash":
        cmd = input_dict.get("command", "")
        if isinstance(cmd, str):
            if any(p in cmd.lower() for p in _TEST_PATTERNS):
                await bus.post(agent_num, "testing", f"ran tests: `{cmd[:120]}`")
            elif cmd.startswith("git diff"):
                await bus.post(agent_num, "status", "generated a patch diff")
