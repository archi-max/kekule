"""Main entry point for Kekule agent swarm using Claude Agent SDK."""

import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage


async def simple_agent_example():
    """Run a simple agent query using Claude Agent SDK."""
    print("Running simple agent query...\n")

    async for message in query(
        prompt="What is 2 + 2? Explain your reasoning.",
        options=ClaudeAgentOptions(
            max_turns=1,
            system_prompt="You are a helpful assistant in a swarm orchestrator."
        )
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text)
                elif hasattr(block, "name"):
                    print(f"[Tool: {block.name}]")
        elif isinstance(message, ResultMessage):
            print(f"\n[Done: {message.subtype}]")


async def code_analysis_agent():
    """Run an agent that can analyze code using file tools."""
    print("\nRunning code analysis agent...\n")

    async for message in query(
        prompt="Find all Python files in src/kekule and list them with a brief description of their purpose.",
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Glob", "Grep"],
            permission_mode="default",
            system_prompt="You are an agent in a heterarchical swarm designed to analyze code."
        )
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text)
                elif hasattr(block, "name"):
                    print(f"[Tool: {block.name}]")
        elif isinstance(message, ResultMessage):
            print(f"\n[Done: {message.subtype}]")


async def main():
    """Main entry point demonstrating Claude Agent SDK usage."""
    print("=" * 60)
    print("Kekule: Heterarchical Agent Swarm")
    print("=" * 60)

    # Run simple example
    await simple_agent_example()

    # Run code analysis example
    await code_analysis_agent()

    print("\n" + "=" * 60)
    print("Agent execution complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
