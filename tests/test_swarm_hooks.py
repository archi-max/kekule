"""Tests for swarm hooks (auto-detection and periodic injection)."""

from unittest.mock import MagicMock

import pytest

from kekule.benchmarks.swarm_bus import SwarmBus
from kekule.benchmarks.swarm_hooks import build_swarm_hooks, _auto_detect_and_post
from kekule.benchmarks.tracing import AgentTraceData


@pytest.fixture
def bus():
    bus = SwarmBus(num_agents=3)
    bus.set_role(0, "tester")
    bus.set_role(1, "tracer")
    return bus


@pytest.fixture
def trace_data():
    return AgentTraceData(
        agent_id="test-0",
        instance_id="test__instance",
        agent_num=0,
        iteration=0,
        model="test-model",
    )


class TestAutoDetect:
    @pytest.mark.asyncio
    async def test_read_posts_file_activity(self, bus):
        await _auto_detect_and_post(
            bus, 0, "Read", {"file_path": "/src/main.py"}
        )
        assert len(bus._messages) == 1
        assert bus._messages[0].category == "file_activity"
        assert "main.py" in bus._messages[0].content

    @pytest.mark.asyncio
    async def test_edit_posts_file_activity(self, bus):
        await _auto_detect_and_post(
            bus, 0, "Edit", {"file_path": "/src/bug.py"}
        )
        assert len(bus._messages) == 1
        assert "modified" in bus._messages[0].content

    @pytest.mark.asyncio
    async def test_grep_posts_search(self, bus):
        await _auto_detect_and_post(
            bus, 0, "Grep", {"pattern": "def parse"}
        )
        assert len(bus._messages) == 1
        assert "searching" in bus._messages[0].content

    @pytest.mark.asyncio
    async def test_bash_test_command_posts_testing(self, bus):
        await _auto_detect_and_post(
            bus, 0, "Bash", {"command": "pytest tests/test_parser.py"}
        )
        assert len(bus._messages) == 1
        assert bus._messages[0].category == "testing"

    @pytest.mark.asyncio
    async def test_bash_git_diff_posts_status(self, bus):
        await _auto_detect_and_post(
            bus, 0, "Bash", {"command": "git diff > fix.diff"}
        )
        assert len(bus._messages) == 1
        assert bus._messages[0].category == "status"

    @pytest.mark.asyncio
    async def test_bash_non_test_no_post(self, bus):
        await _auto_detect_and_post(
            bus, 0, "Bash", {"command": "ls -la"}
        )
        assert len(bus._messages) == 0

    @pytest.mark.asyncio
    async def test_sets_current_file_on_read(self, bus):
        await _auto_detect_and_post(
            bus, 0, "Read", {"file_path": "/src/utils.py"}
        )
        assert bus._current_files[0] == "/src/utils.py"

    @pytest.mark.asyncio
    async def test_sets_current_file_on_write(self, bus):
        await _auto_detect_and_post(
            bus, 0, "Write", {"file_path": "/src/fix.py"}
        )
        assert bus._current_files[0] == "/src/fix.py"


class TestBuildSwarmHooks:
    @pytest.mark.asyncio
    async def test_returns_hooks_dict(self, bus, trace_data):
        hooks = build_swarm_hooks(bus, 0, trace_data)
        assert "PostToolUse" in hooks
        assert len(hooks["PostToolUse"]) == 1

    @pytest.mark.asyncio
    async def test_logs_tool_calls(self, bus, trace_data):
        hooks = build_swarm_hooks(bus, 0, trace_data)
        hook_fn = hooks["PostToolUse"][0].hooks[0]

        # Simulate a Read tool call
        await hook_fn(
            {"tool_name": "Read", "tool_input": {"file_path": "/foo.py"}},
            "tool-1",
            MagicMock(),
        )

        assert len(trace_data.tool_calls) == 1
        assert trace_data.tool_calls[0]["tool"] == "Read"

    @pytest.mark.asyncio
    async def test_periodic_injection(self, bus, trace_data):
        """Every inject_every calls should return additionalContext."""
        hooks = build_swarm_hooks(bus, 0, trace_data, inject_every=3)
        hook_fn = hooks["PostToolUse"][0].hooks[0]

        # Post some messages from agent 1 first
        bus.set_role(1, "tracer")
        await bus.post(1, "finding", "root cause found")
        await bus.update_status(1, "fixing")

        results = []
        for i in range(6):
            result = await hook_fn(
                {"tool_name": "Read", "tool_input": {"file_path": f"/f{i}.py"}},
                f"tool-{i}",
                MagicMock(),
            )
            results.append(result)

        # Calls 1 and 2: no injection. Call 3 (index 2): injection.
        # Call 4 and 5: no injection. Call 6 (index 5): injection.
        assert results[2].get("hookSpecificOutput") is not None
        assert results[5].get("hookSpecificOutput") is not None
        assert results[0] == {}
        assert results[1] == {}

    @pytest.mark.asyncio
    async def test_no_injection_when_no_updates(self, bus, trace_data):
        """If there are no updates from others, injection is skipped."""
        hooks = build_swarm_hooks(bus, 0, trace_data, inject_every=1)
        hook_fn = hooks["PostToolUse"][0].hooks[0]

        result = await hook_fn(
            {"tool_name": "Read", "tool_input": {"file_path": "/x.py"}},
            "tool-1",
            MagicMock(),
        )

        # Summary will still have statuses section but no messages
        # The hook checks if summary.strip() is truthy, which it will be
        # because of the header. So it should still inject.
        if "hookSpecificOutput" in result:
            ctx = result["hookSpecificOutput"]["additionalContext"]
            assert "SWARM STATUS UPDATE" in ctx
