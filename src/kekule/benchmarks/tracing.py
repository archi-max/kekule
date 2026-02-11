"""
LangFuse tracing integration for the SWE-bench harness.

Creates traces/spans/generations for each experiment iteration, problem, and agent.
Captures the full agent conversation including tool uses and results.

All credentials are configured via environment variables:
  LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentTraceData:
    """Accumulated data for an agent's trace span."""

    agent_id: str
    instance_id: str
    agent_num: int
    iteration: int
    model: str
    tool_calls: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    prompt: str = ""
    chatoverflow_questions: int = 0
    chatoverflow_answers_received: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    patch_produced: bool = False
    patch_content: str = ""
    error: str | None = None


class TracingManager:
    """Manages LangFuse traces for the experiment."""

    def __init__(self, config: Any):
        self.config = config
        self._enabled = config.langfuse_enabled
        self.langfuse = None

        if self._enabled:
            try:
                from langfuse import Langfuse
                self.langfuse = Langfuse(
                    secret_key=config.langfuse_secret_key,
                    public_key=config.langfuse_public_key,
                    host=config.langfuse_base_url,
                )
                logger.info(f"LangFuse connected: {config.langfuse_base_url}")
            except ImportError:
                logger.warning("langfuse package not installed, tracing disabled")
                self._enabled = False
            except Exception as e:
                logger.warning(f"Failed to connect to LangFuse: {e}")
                self._enabled = False
        else:
            logger.info("LangFuse tracing not configured (set LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL to enable)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def create_experiment_trace(self, iteration: int):
        """Create a top-level span for an experiment iteration."""
        if not self._enabled:
            return _NoOpSpan()

        prefix = self.config.experiment_name or "swe-bench"
        name = f"{prefix}-iteration-{iteration}"

        span = self.langfuse.start_span(
            name=name,
            metadata={
                "experiment_name": self.config.experiment_name or None,
                "model": self.config.model,
                "agents_per_problem": self.config.agents_per_problem,
                "num_problems": self.config.num_problems,
                "iteration": iteration,
            },
        )
        logger.info(f"Created trace for iteration {iteration}: {name} ({span.id})")
        return span

    def create_agent_span(
        self,
        parent_span,
        agent_id: str,
        instance_id: str,
        agent_num: int,
        iteration: int,
    ):
        """Create a child span for a single agent's work."""
        if not self._enabled:
            return _NoOpSpan()

        span = parent_span.start_span(
            name=f"agent-{agent_num}-{instance_id}",
            metadata={
                "agent_id": agent_id,
                "instance_id": instance_id,
                "agent_num": agent_num,
                "iteration": iteration,
                "model": self.config.model,
            },
            input={"instance_id": instance_id, "agent_id": agent_id},
        )
        return span

    def end_agent_span(self, span, trace_data: AgentTraceData):
        """End an agent span with full conversation trace."""
        if not self._enabled:
            return

        # Set the prompt as input on the span
        span.update(
            input={"prompt": trace_data.prompt},
            output={
                "patch_produced": trace_data.patch_produced,
                "patch": trace_data.patch_content[:5000] if trace_data.patch_content else "",
                "num_turns": trace_data.num_turns,
                "total_cost_usd": trace_data.total_cost_usd,
                "tool_call_count": len(trace_data.tool_calls),
                "error": trace_data.error,
            },
        )

        # Create generations and tool spans from the captured conversation
        self._create_conversation_traces(span, trace_data)

        span.end()

    def _create_conversation_traces(self, parent_span, trace_data: AgentTraceData):
        """Create Langfuse generations and spans from the conversation messages."""
        turn = 0

        for msg in trace_data.messages:
            msg_type = msg.get("type")

            if msg_type == "assistant":
                turn += 1
                text_parts = []
                tool_uses = []

                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_uses.append(block)

                assistant_text = "\n".join(text_parts) if text_parts else None

                # Create a generation for this assistant turn
                gen = parent_span.start_generation(
                    name=f"turn-{turn}",
                    model=msg.get("model", trace_data.model),
                    input={"turn": turn},
                    output=assistant_text,
                    metadata={
                        "tool_uses": [
                            {"name": t["name"], "input_preview": _truncate_dict(t.get("input", {}), 500)}
                            for t in tool_uses
                        ],
                    } if tool_uses else None,
                )
                gen.end()

                # Create child spans for each tool use
                for tool in tool_uses:
                    tool_span = parent_span.start_span(
                        name=f"tool:{tool['name']}",
                        input=_truncate_dict(tool.get("input", {}), 2000),
                        metadata={"turn": turn, "tool_use_id": tool.get("id", "")},
                    )
                    tool_span.end()

            elif msg_type == "tool_result":
                # Create event for tool results
                parent_span.create_event(
                    name="tool_result",
                    input={
                        "tool_use_id": msg.get("tool_use_id", ""),
                        "is_error": msg.get("is_error", False),
                        "content_preview": _truncate(str(msg.get("content", "")), 1000),
                    },
                )

    def log_evaluation_result(
        self,
        parent_span,
        instance_id: str,
        agent_num: int,
        passed: bool,
        details: dict | None = None,
    ):
        """Log an evaluation result as an event on the parent span."""
        if not self._enabled:
            return

        parent_span.create_event(
            name="evaluation-result",
            metadata={
                "instance_id": instance_id,
                "agent_num": agent_num,
                "passed": passed,
                **(details or {}),
            },
        )

    def log_experiment_summary(
        self,
        parent_span,
        results: list[dict],
    ):
        """Log the overall experiment summary."""
        if not self._enabled:
            return

        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        parent_span.update(
            output={
                "total_agents": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": passed / total if total > 0 else 0,
            },
        )
        parent_span.end()

    def flush(self):
        """Flush all pending events to LangFuse."""
        if self._enabled and self.langfuse:
            self.langfuse.flush()

    def shutdown(self):
        """Shutdown the LangFuse client."""
        if self._enabled and self.langfuse:
            self.langfuse.shutdown()


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string to max_len characters."""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"... ({len(s)} chars total)"


def _truncate_dict(d: dict, max_len: int) -> dict:
    """Truncate string values in a dict for display."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str) and len(v) > max_len:
            result[k] = v[:max_len] + f"... ({len(v)} chars)"
        else:
            result[k] = v
    return result


class _NoOpSpan:
    """No-op span used when tracing is disabled."""

    id = "noop"

    def start_span(self, **kwargs):
        return _NoOpSpan()

    def start_generation(self, **kwargs):
        return _NoOpSpan()

    def update(self, **kwargs):
        pass

    def end(self):
        pass

    def create_event(self, **kwargs):
        pass


def build_agent_hooks(trace_data: AgentTraceData):
    """
    Build Claude Agent SDK hooks that log tool usage to the trace data.

    Tracks ChatOverflow interactions via HTTP API (curl commands in Bash tool).
    Returns a hooks dict suitable for ClaudeAgentOptions.
    """
    from claude_agent_sdk import HookMatcher
    from claude_agent_sdk.types import PostToolUseHookInput, HookContext

    async def on_tool_use(
        input_data: PostToolUseHookInput,
        tool_use_id: str | None,
        context: HookContext,
    ):
        try:
            tool_name = input_data.get("tool_name", "unknown")
            tool_input = input_data.get("tool_input", {})
            trace_data.tool_calls.append(
                {
                    "tool": tool_name,
                    "timestamp": time.time(),
                }
            )
            # Track ChatOverflow interactions via HTTP API (Bash curl commands)
            if tool_name == "Bash":
                cmd = ""
                if isinstance(tool_input, dict):
                    cmd = tool_input.get("command", "")
                elif isinstance(tool_input, str):
                    cmd = tool_input

                if "/questions" in cmd or "/forums" in cmd or "chatoverflow" in cmd.lower():
                    if "POST" in cmd and "/questions" in cmd and "/answers" not in cmd:
                        trace_data.chatoverflow_questions += 1
                    elif "POST" in cmd and "/answers" in cmd:
                        trace_data.chatoverflow_answers_received += 1
                    elif "/questions" in cmd:
                        trace_data.chatoverflow_questions += 1
        except Exception:
            pass  # Never let hook errors crash the agent

        return {}

    return {
        "PostToolUse": [
            HookMatcher(hooks=[on_tool_use]),
        ],
    }
