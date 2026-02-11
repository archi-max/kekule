"""
LangFuse tracing integration for the SWE-bench harness.

Creates traces/spans for each experiment iteration, problem, and agent.
Logs tool usage, costs, and results.

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
    chatoverflow_questions: int = 0
    chatoverflow_answers_received: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    patch_produced: bool = False
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

        span = self.langfuse.start_span(
            name=f"swe-bench-iteration-{iteration}",
            metadata={
                "model": self.config.model,
                "agents_per_problem": self.config.agents_per_problem,
                "num_problems": self.config.num_problems,
                "iteration": iteration,
            },
        )
        logger.info(f"Created trace for iteration {iteration}: {span.id}")
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
        """End an agent span with results."""
        if not self._enabled:
            return

        span.update(
            output={
                "patch_produced": trace_data.patch_produced,
                "num_turns": trace_data.num_turns,
                "total_cost_usd": trace_data.total_cost_usd,
                "chatoverflow_questions": trace_data.chatoverflow_questions,
                "chatoverflow_answers_received": trace_data.chatoverflow_answers_received,
                "tool_call_count": len(trace_data.tool_calls),
                "error": trace_data.error,
            },
            metadata={
                "tool_calls": trace_data.tool_calls[-20:],
            },
        )
        span.end()

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


class _NoOpSpan:
    """No-op span used when tracing is disabled."""

    id = "noop"

    def start_span(self, **kwargs):
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
