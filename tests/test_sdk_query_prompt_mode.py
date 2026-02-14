import asyncio
import json
import os
from collections.abc import AsyncIterator

import pytest
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from claude_agent_sdk._internal.client import InternalClient
import claude_agent_sdk._internal.client as internal_client_mod

from kekule.benchmarks.solver_agent import streaming_user_prompt
from kekule.benchmarks.solver_agent import ensure_sdk_stream_close_timeout


def _result_message() -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "duration_ms": 1,
        "duration_api_ms": 1,
        "is_error": False,
        "num_turns": 1,
        "session_id": "s",
        "total_cost_usd": 0.0,
        "result": "ok",
    }


class _FakeTransport:
    instances: list["_FakeTransport"] = []

    def __init__(self, prompt, options):
        self.prompt = prompt
        self.options = options
        self.writes: list[str] = []
        self.end_input_calls = 0
        self.closed = False
        self.connected = False
        _FakeTransport.instances.append(self)

    async def connect(self) -> None:
        self.connected = True

    async def write(self, data: str) -> None:
        self.writes.append(data)

    async def end_input(self) -> None:
        self.end_input_calls += 1

    async def close(self) -> None:
        self.closed = True


class _FakeTaskGroup:
    def __init__(self):
        self._tasks: list[asyncio.Task] = []

    def start_soon(self, fn, *args) -> None:
        self._tasks.append(asyncio.create_task(fn(*args)))

    async def wait(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks)


class _FakeQuery:
    instances: list["_FakeQuery"] = []

    def __init__(self, transport, **kwargs):
        self.transport = transport
        self.kwargs = kwargs
        self._tg = _FakeTaskGroup()
        self.stream_input_called = False
        _FakeQuery.instances.append(self)

    async def start(self) -> None:
        pass

    async def initialize(self) -> None:
        pass

    async def stream_input(self, stream: AsyncIterator[dict]) -> None:
        self.stream_input_called = True
        async for _ in stream:
            pass

    async def receive_messages(self):
        # Allow scheduled stream_input task to run before finishing.
        await asyncio.sleep(0)
        yield _result_message()

    async def close(self) -> None:
        await self._tg.wait()
        await self.transport.close()


async def _dummy_hook(input_data, tool_use_id, context):
    return {}


def _with_hook_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model="claude-sonnet-4-5",
        hooks={"PostToolUse": [HookMatcher(hooks=[_dummy_hook])]},
    )


@pytest.mark.asyncio
async def test_string_prompt_path_closes_input_immediately(monkeypatch):
    _FakeTransport.instances.clear()
    _FakeQuery.instances.clear()
    monkeypatch.setattr(internal_client_mod, "SubprocessCLITransport", _FakeTransport)
    monkeypatch.setattr(internal_client_mod, "Query", _FakeQuery)

    client = InternalClient()
    options = _with_hook_options()
    messages = [m async for m in client.process_query(prompt="hello", options=options)]

    assert len(messages) == 1
    transport = _FakeTransport.instances[0]
    query = _FakeQuery.instances[0]
    assert transport.connected is True
    assert transport.end_input_calls == 1
    assert query.stream_input_called is False

    sent_user = json.loads(transport.writes[0])
    assert sent_user["type"] == "user"
    assert sent_user["message"]["content"] == "hello"


@pytest.mark.asyncio
async def test_async_prompt_path_uses_stream_input_without_direct_end_input(monkeypatch):
    _FakeTransport.instances.clear()
    _FakeQuery.instances.clear()
    monkeypatch.setattr(internal_client_mod, "SubprocessCLITransport", _FakeTransport)
    monkeypatch.setattr(internal_client_mod, "Query", _FakeQuery)

    async def prompt_stream():
        yield {
            "type": "user",
            "session_id": "s",
            "message": {"role": "user", "content": "hello"},
            "parent_tool_use_id": None,
        }

    client = InternalClient()
    options = _with_hook_options()
    messages = [
        m async for m in client.process_query(prompt=prompt_stream(), options=options)
    ]

    assert len(messages) == 1
    transport = _FakeTransport.instances[0]
    query = _FakeQuery.instances[0]
    assert query.stream_input_called is True
    assert transport.end_input_calls == 0


@pytest.mark.asyncio
async def test_streaming_user_prompt_shape():
    items = [item async for item in streaming_user_prompt("hello")]
    assert len(items) == 1
    assert items[0] == {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": "hello"},
        "parent_tool_use_id": None,
    }


def test_ensure_sdk_stream_close_timeout_sets_default(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", raising=False)
    ensure_sdk_stream_close_timeout()
    assert os.environ["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"] == "86400000"


def test_ensure_sdk_stream_close_timeout_preserves_existing(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "1234")
    ensure_sdk_stream_close_timeout()
    assert os.environ["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"] == "1234"
