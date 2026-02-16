"""Tests for the BeadsTracker and swarm beads integration."""

import shutil

import pytest
import pytest_asyncio

from kekule.benchmarks.swarm_beads import (
    BeadsTracker,
    create_role_tasks,
    SWARM_MCP_TOOL_NAMES,
)


# Skip all tests if bd is not installed
pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None,
    reason="bd binary not installed",
)


@pytest.fixture
def tracker(tmp_path):
    """Create a BeadsTracker with a temp directory."""
    return BeadsTracker(tmp_path)


@pytest_asyncio.fixture
async def initialized_tracker(tmp_path):
    """Create and initialize a BeadsTracker."""
    t = BeadsTracker(tmp_path)
    await t.init(prefix="test")
    return t


class TestBeadsTrackerAvailable:
    def test_available_when_bd_installed(self, tracker):
        assert tracker.available is True


class TestBeadsTrackerInit:
    @pytest.mark.asyncio
    async def test_init_creates_database(self, tracker):
        result = await tracker.init(prefix="test")
        assert result is True
        assert tracker._initialized is True
        # Check .beads directory was created
        beads_dir = tracker._repo_dir / ".beads"
        assert beads_dir.exists()

    @pytest.mark.asyncio
    async def test_init_idempotent_fails_second_time(self, tracker):
        """bd init fails if already initialized (returns None)."""
        await tracker.init(prefix="test")
        # Second init should fail (bd returns error)
        result = await tracker.init(prefix="test")
        assert result is False


class TestBeadsTrackerCreate:
    @pytest.mark.asyncio
    async def test_create_task(self, initialized_tracker):
        result = await initialized_tracker.create_task(
            "Fix the bug", description="Role: fixer"
        )
        assert result is not None
        assert "id" in result
        assert result["title"] == "Fix the bug"
        assert result["status"] == "open"

    @pytest.mark.asyncio
    async def test_create_task_without_description(self, initialized_tracker):
        result = await initialized_tracker.create_task("Simple task")
        assert result is not None
        assert "id" in result


class TestBeadsTrackerDeps:
    @pytest.mark.asyncio
    async def test_add_dependency(self, initialized_tracker):
        t1 = await initialized_tracker.create_task("Task A")
        t2 = await initialized_tracker.create_task("Task B")
        assert t1 and t2

        # A depends on B (B must finish first)
        result = await initialized_tracker.add_dependency(t1["id"], t2["id"])
        assert result is not None
        assert result["status"] == "added"

    @pytest.mark.asyncio
    async def test_ready_shows_unblocked(self, initialized_tracker):
        t1 = await initialized_tracker.create_task("Blocked task")
        t2 = await initialized_tracker.create_task("Ready task")
        assert t1 and t2

        await initialized_tracker.add_dependency(t1["id"], t2["id"])

        ready = await initialized_tracker.ready()
        ready_ids = {t["id"] for t in ready}
        # t2 should be ready (nothing blocks it)
        assert t2["id"] in ready_ids
        # t1 should NOT be ready (blocked by t2)
        assert t1["id"] not in ready_ids

    @pytest.mark.asyncio
    async def test_blocked_shows_blocked(self, initialized_tracker):
        t1 = await initialized_tracker.create_task("Blocked task")
        t2 = await initialized_tracker.create_task("Blocker task")
        assert t1 and t2

        await initialized_tracker.add_dependency(t1["id"], t2["id"])

        blocked = await initialized_tracker.blocked()
        blocked_ids = {t["id"] for t in blocked}
        assert t1["id"] in blocked_ids


class TestBeadsTrackerUpdate:
    @pytest.mark.asyncio
    async def test_update_status(self, initialized_tracker):
        t = await initialized_tracker.create_task("Test task")
        assert t is not None

        result = await initialized_tracker.update_status(t["id"], "in_progress")
        assert result is not None

    @pytest.mark.asyncio
    async def test_close_task(self, initialized_tracker):
        t = await initialized_tracker.create_task("Task to close")
        assert t is not None

        result = await initialized_tracker.close_task(t["id"], "done")
        assert result is not None
        # Result should show the closed task
        if isinstance(result, list):
            assert result[0]["status"] == "closed"
        elif isinstance(result, dict):
            assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_list_tasks(self, initialized_tracker):
        await initialized_tracker.create_task("Task 1")
        await initialized_tracker.create_task("Task 2")

        tasks = await initialized_tracker.list_tasks()
        assert len(tasks) >= 2


class TestCreateRoleTasks:
    @pytest.mark.asyncio
    async def test_create_role_tasks_basic(self, initialized_tracker):
        roles = [
            {"name": "reproducer", "goal": "Reproduce the bug"},
            {"name": "tracer", "goal": "Trace root cause"},
            {"name": "fixer", "goal": "Fix the bug"},
        ]
        deps = [
            ["tracer", "reproducer"],
            ["fixer", "tracer"],
        ]

        role_ids = await create_role_tasks(initialized_tracker, roles, deps)
        assert len(role_ids) == 3
        assert "reproducer" in role_ids
        assert "tracer" in role_ids
        assert "fixer" in role_ids

        # All IDs should be non-empty strings
        for name, tid in role_ids.items():
            assert isinstance(tid, str)
            assert len(tid) > 0

    @pytest.mark.asyncio
    async def test_create_role_tasks_no_deps(self, initialized_tracker):
        roles = [
            {"name": "a", "goal": "Do A"},
            {"name": "b", "goal": "Do B"},
        ]

        role_ids = await create_role_tasks(initialized_tracker, roles, None)
        assert len(role_ids) == 2

    @pytest.mark.asyncio
    async def test_create_role_tasks_with_deps_unblocks_correctly(
        self, initialized_tracker
    ):
        """After creating tasks with deps, verify ready/blocked state."""
        roles = [
            {"name": "first", "goal": "Do first"},
            {"name": "second", "goal": "Do second"},
        ]
        deps = [["second", "first"]]

        role_ids = await create_role_tasks(initialized_tracker, roles, deps)

        ready = await initialized_tracker.ready()
        ready_ids = {t["id"] for t in ready}

        # "first" should be ready (nothing blocks it)
        assert role_ids["first"] in ready_ids
        # "second" should NOT be ready (blocked by "first")
        assert role_ids["second"] not in ready_ids


class TestSwarmMcpToolNames:
    def test_tool_names_format(self):
        """All tool names should follow the mcp__swarm__* convention."""
        for name in SWARM_MCP_TOOL_NAMES:
            assert name.startswith("mcp__swarm__")

    def test_expected_tools_present(self):
        expected = {
            "mcp__swarm__swarm_broadcast",
            "mcp__swarm__swarm_read_updates",
            "mcp__swarm__swarm_claim_task",
            "mcp__swarm__swarm_create_task",
            "mcp__swarm__swarm_add_dep",
            "mcp__swarm__swarm_ready",
            "mcp__swarm__swarm_blocked",
            "mcp__swarm__swarm_complete_task",
        }
        assert set(SWARM_MCP_TOOL_NAMES) == expected
