"""
Monkey-patches for claude_agent_sdk bugs.

These patches fix known issues in SDK v0.1.35 that affect swarm operation
with in-process MCP servers. They should be removed when the SDK is updated.

Bug 1: Query.close() doesn't suppress ExceptionGroup from TaskGroup during
shutdown, causing unhandled errors when MCP control requests race with
process exit.

Bug 2: InternalClient.process_query() calls end_input() immediately for
string prompts even when SDK MCP servers or hooks are present, closing the
bidirectional channel before MCP tool calls can be processed.
"""

import json
import logging
import os
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)

_patched = False


def patch_sdk_mcp_close() -> None:
    """
    Patch the SDK for MCP server compatibility.

    Applies two fixes:
    1. Query.close() suppresses BaseExceptionGroup during TaskGroup shutdown
    2. InternalClient.process_query() keeps stdin open when MCP servers or
       hooks are present, so the bidirectional control channel stays alive
    """
    global _patched
    if _patched:
        return

    try:
        import anyio
        from claude_agent_sdk._internal.query import Query
        from claude_agent_sdk._internal.client import InternalClient, parse_message

        # --- Patch 1: Query.close() ---
        async def patched_close(self: Query) -> None:
            self._closed = True
            if self._tg:
                self._tg.cancel_scope.cancel()
                with suppress(anyio.get_cancelled_exc_class(), BaseExceptionGroup):
                    await self._tg.__aexit__(None, None, None)
            await self.transport.close()

        Query.close = patched_close  # type: ignore[assignment]

        # --- Patch 2: process_query for string prompts with MCP/hooks ---
        original_process_query = InternalClient.process_query

        async def patched_process_query(
            self: InternalClient,
            prompt: str | AsyncIterable[dict[str, Any]],
            options: Any,
            transport: Any = None,
        ) -> AsyncIterator[Any]:
            """Patched process_query that keeps stdin open for MCP/hooks."""
            from claude_agent_sdk._internal.transport.subprocess_cli import (
                SubprocessCLITransport,
            )
            from dataclasses import replace

            configured_options = options
            if options.can_use_tool:
                if isinstance(prompt, str):
                    raise ValueError(
                        "can_use_tool callback requires streaming mode."
                    )
                if options.permission_prompt_tool_name:
                    raise ValueError(
                        "can_use_tool cannot be used with permission_prompt_tool_name."
                    )
                configured_options = replace(
                    options, permission_prompt_tool_name="stdio"
                )

            if transport is not None:
                chosen_transport = transport
            else:
                chosen_transport = SubprocessCLITransport(
                    prompt=prompt, options=configured_options
                )

            await chosen_transport.connect()

            sdk_mcp_servers = {}
            if configured_options.mcp_servers and isinstance(
                configured_options.mcp_servers, dict
            ):
                for name, config in configured_options.mcp_servers.items():
                    if isinstance(config, dict) and config.get("type") == "sdk":
                        sdk_mcp_servers[name] = config["instance"]

            agents_dict = None
            if configured_options.agents:
                agents_dict = {
                    name: {
                        k: v
                        for k, v in asdict(agent_def).items()
                        if v is not None
                    }
                    for name, agent_def in configured_options.agents.items()
                }

            query_obj = Query(
                transport=chosen_transport,
                is_streaming_mode=True,
                can_use_tool=configured_options.can_use_tool,
                hooks=(
                    self._convert_hooks_to_internal_format(
                        configured_options.hooks
                    )
                    if configured_options.hooks
                    else None
                ),
                sdk_mcp_servers=sdk_mcp_servers,
                agents=agents_dict,
            )

            try:
                await query_obj.start()
                await query_obj.initialize()

                has_mcp = bool(sdk_mcp_servers)
                has_hooks = bool(configured_options.hooks)

                if isinstance(prompt, str):
                    user_message = {
                        "type": "user",
                        "session_id": "",
                        "message": {"role": "user", "content": prompt},
                        "parent_tool_use_id": None,
                    }
                    await chosen_transport.write(
                        json.dumps(user_message) + "\n"
                    )

                    if has_mcp or has_hooks:
                        # KEY FIX: Keep stdin open for bidirectional channel
                        timeout_ms = float(
                            os.environ.get(
                                "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "60000"
                            )
                        )
                        timeout_s = timeout_ms / 1000.0

                        async def _wait_and_close() -> None:
                            try:
                                with anyio.move_on_after(timeout_s):
                                    await query_obj._first_result_event.wait()
                            except Exception:
                                pass
                            try:
                                await chosen_transport.end_input()
                            except Exception:
                                pass

                        if query_obj._tg:
                            query_obj._tg.start_soon(_wait_and_close)
                    else:
                        await chosen_transport.end_input()

                elif isinstance(prompt, AsyncIterable) and query_obj._tg:
                    query_obj._tg.start_soon(query_obj.stream_input, prompt)

                async for data in query_obj.receive_messages():
                    yield parse_message(data)

            finally:
                await query_obj.close()

        InternalClient.process_query = patched_process_query  # type: ignore[assignment]

        _patched = True
        logger.debug(
            "[sdk-patch] Patched Query.close() and InternalClient.process_query()"
        )

    except Exception as e:
        logger.warning(f"[sdk-patch] Failed to patch SDK: {e}")
