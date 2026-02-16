"""Tests for the SwarmBus in-memory message bus."""

import asyncio

import pytest

from kekule.benchmarks.swarm_bus import SwarmBus, SwarmMessage


@pytest.fixture
def bus():
    """Create a SwarmBus with 3 agents and no filesystem sync."""
    return SwarmBus(num_agents=3)


@pytest.fixture
def bus_with_ledger(tmp_path):
    """Create a SwarmBus with filesystem ledger sync."""
    ledger_dir = tmp_path / "swarm_ledger"
    ledger_dir.mkdir()
    return SwarmBus(num_agents=3, ledger_dir=ledger_dir)


class TestSwarmMessage:
    def test_message_fields(self):
        msg = SwarmMessage(
            agent_num=0, role="test_runner", category="finding", content="found bug"
        )
        assert msg.agent_num == 0
        assert msg.role == "test_runner"
        assert msg.category == "finding"
        assert msg.content == "found bug"
        assert msg.timestamp > 0
        assert msg.seq == 0  # Default before bus assigns it


class TestSwarmBusPost:
    @pytest.mark.asyncio
    async def test_post_increments_seq(self, bus):
        bus.set_role(0, "tester")
        await bus.post(0, "finding", "message 1")
        await bus.post(0, "finding", "message 2")
        assert len(bus._messages) == 2
        assert bus._messages[0].seq == 1
        assert bus._messages[1].seq == 2

    @pytest.mark.asyncio
    async def test_post_uses_role_name(self, bus):
        bus.set_role(0, "bug_reproducer")
        await bus.post(0, "status", "exploring")
        assert bus._messages[0].role == "bug_reproducer"

    @pytest.mark.asyncio
    async def test_post_default_role(self, bus):
        """When no role set, defaults to agent-N."""
        await bus.post(1, "status", "hello")
        assert bus._messages[0].role == "agent-1"


class TestSwarmBusGetUpdates:
    @pytest.mark.asyncio
    async def test_get_updates_excludes_own_messages(self, bus):
        bus.set_role(0, "a")
        bus.set_role(1, "b")
        await bus.post(0, "finding", "from agent 0")
        await bus.post(1, "finding", "from agent 1")

        updates_for_0 = await bus.get_updates_for(0)
        assert len(updates_for_0) == 1
        assert updates_for_0[0].agent_num == 1

    @pytest.mark.asyncio
    async def test_cursor_based_reads(self, bus):
        bus.set_role(1, "tracer")
        await bus.post(1, "finding", "msg1")
        await bus.post(1, "finding", "msg2")

        # First read gets both
        updates = await bus.get_updates_for(0)
        assert len(updates) == 2

        # Second read gets nothing (cursor advanced)
        updates = await bus.get_updates_for(0)
        assert len(updates) == 0

        # Post another, third read gets just the new one
        await bus.post(1, "finding", "msg3")
        updates = await bus.get_updates_for(0)
        assert len(updates) == 1
        assert updates[0].content == "msg3"

    @pytest.mark.asyncio
    async def test_independent_cursors(self, bus):
        bus.set_role(0, "a")
        await bus.post(0, "finding", "hello")

        # Agent 1 reads
        updates_1 = await bus.get_updates_for(1)
        assert len(updates_1) == 1

        # Agent 2 also reads (independent cursor)
        updates_2 = await bus.get_updates_for(2)
        assert len(updates_2) == 1

        # Agent 1 reads again, nothing new
        updates_1 = await bus.get_updates_for(1)
        assert len(updates_1) == 0


class TestSwarmBusStatus:
    @pytest.mark.asyncio
    async def test_update_and_read_status(self, bus):
        await bus.update_status(0, "exploring")
        await bus.update_status(1, "fixing")
        assert bus._statuses[0] == "exploring"
        assert bus._statuses[1] == "fixing"

    @pytest.mark.asyncio
    async def test_set_current_file(self, bus):
        await bus.set_current_file(0, "src/main.py")
        assert bus._current_files[0] == "src/main.py"


class TestSwarmBusSummary:
    @pytest.mark.asyncio
    async def test_summary_includes_statuses(self, bus):
        bus.set_role(0, "reproducer")
        bus.set_role(1, "tracer")
        bus.set_role(2, "architect")
        await bus.update_status(0, "exploring")
        await bus.update_status(1, "fixing")
        await bus.update_status(2, "verifying")
        await bus.set_current_file(1, "src/bug.py")

        summary = await bus.get_swarm_summary(for_agent=0)
        assert "SWARM STATUS UPDATE" in summary
        assert "tracer" in summary
        assert "fixing" in summary
        assert "src/bug.py" in summary
        assert "reproducer" not in summary  # Should exclude self

    @pytest.mark.asyncio
    async def test_summary_includes_messages(self, bus):
        bus.set_role(1, "tracer")
        await bus.post(1, "finding", "root cause found in parser.py")

        summary = await bus.get_swarm_summary(for_agent=0)
        assert "root cause found in parser.py" in summary
        assert "finding" in summary

    @pytest.mark.asyncio
    async def test_summary_advances_cursor(self, bus):
        bus.set_role(1, "tracer")
        await bus.post(1, "finding", "msg1")

        # First summary gets it
        summary1 = await bus.get_swarm_summary(for_agent=0)
        assert "msg1" in summary1

        # Second summary has no new messages
        summary2 = await bus.get_swarm_summary(for_agent=0)
        assert "msg1" not in summary2


class TestSwarmBusLedger:
    @pytest.mark.asyncio
    async def test_writes_to_broadcast_file(self, bus_with_ledger):
        bus_with_ledger.set_role(0, "tester")
        await bus_with_ledger.post(0, "finding", "bug found")

        broadcast_file = bus_with_ledger._ledger_dir / "BROADCAST.md"
        assert broadcast_file.exists()
        content = broadcast_file.read_text()
        assert "bug found" in content
        assert "tester" in content

    @pytest.mark.asyncio
    async def test_appends_multiple_messages(self, bus_with_ledger):
        bus_with_ledger.set_role(0, "a")
        bus_with_ledger.set_role(1, "b")
        await bus_with_ledger.post(0, "finding", "first")
        await bus_with_ledger.post(1, "status", "second")

        broadcast_file = bus_with_ledger._ledger_dir / "BROADCAST.md"
        content = broadcast_file.read_text()
        assert "first" in content
        assert "second" in content


class TestSwarmBusConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_posts(self, bus):
        """Multiple agents posting concurrently should not lose messages."""
        bus.set_role(0, "a")
        bus.set_role(1, "b")
        bus.set_role(2, "c")

        async def agent_posts(agent_num, count):
            for i in range(count):
                await bus.post(agent_num, "data", f"msg-{i}")

        await asyncio.gather(
            agent_posts(0, 10),
            agent_posts(1, 10),
            agent_posts(2, 10),
        )

        assert len(bus._messages) == 30
        # All seq numbers should be unique
        seqs = {m.seq for m in bus._messages}
        assert len(seqs) == 30
