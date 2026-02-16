"""
Phase 1: Conversation Agent -- multi-turn intent capture.

Uses ClaudeSDKClient for a stateful conversation where the agent
explores the repo, the user describes what they want verified,
and the agent captures structured Intent.
"""

import json
import logging
from pathlib import Path
from typing import Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from .schemas import Intent

logger = logging.getLogger(__name__)


CONVERSATION_SYSTEM_PROMPT = """
You are a Requirements Analyst for the Kekule Oracle verification system.

## Your Role
Have a conversation with the user to understand what they want verified in their codebase.
You are NOT generating tests or rules yet -- you are capturing their intent clearly.

## Workflow
1. First, explore the repository to understand its structure, tech stack, and key modules.
2. Present a brief summary of what you found.
3. Ask the user what aspects they want to verify.
4. For each area they mention:
   - Ask what "correct behavior" means to them
   - Ask about priorities (critical vs. nice-to-have)
   - Ask about edge cases they're worried about
   - Ask about any known bugs or fragile areas
5. Summarize what you've heard and confirm.

## Guidelines
- Be conversational and concise. Don't overwhelm with questions.
- Ask one or two focused questions at a time.
- Push for specifics: "works correctly" -> "returns X when given Y"
- If the user is vague, suggest concrete examples based on the code you explored.
- Track priorities: what MUST work vs. what SHOULD work vs. what would be NICE.

## Important
- You are having a CONVERSATION. Respond naturally to the user.
- Do NOT output JSON or structured data during the conversation.
- Only output structured JSON when explicitly asked to extract intent.
"""

EXTRACT_INTENT_PROMPT = """
Based on our conversation, output a structured JSON summary of the user's verification intent.

Output ONLY a JSON object (no markdown fences, no commentary) with this exact structure:
{
  "summary": "One-paragraph summary of what the user wants verified",
  "priorities": ["Most important thing", "Second most important", ...],
  "requirements": [
    {
      "description": "Specific thing to verify",
      "priority": "critical" | "high" | "medium" | "low",
      "area": "Which part of the codebase",
      "measurable": true/false (whether we have concrete pass/fail criteria)
    }
  ],
  "context": "Any relevant background the user provided"
}

Include EVERY requirement discussed in the conversation. Mark requirements as
measurable=true only if the user gave specific expected values or behaviors.
"""


async def _drain_text(client: ClaudeSDKClient) -> str:
    """Drain all text from the agent's response, return the concatenated text."""
    texts = []
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)
        elif isinstance(message, ResultMessage):
            if message.is_error:
                logger.error(f"Agent error: {message.result}")
    return "\n".join(texts)


async def capture_intent(
    repo_path: Path,
    on_message: Callable[[str], None] | None = None,
    get_input: Callable[[str], str] | None = None,
    model: str = "claude-sonnet-4-5",
    max_conversation_turns: int = 10,
) -> Intent:
    """Run a multi-turn conversation to capture the user's verification intent.

    Args:
        repo_path: Path to the repository to verify.
        on_message: Callback to display agent messages to the user.
        get_input: Callback to get user input. If None, uses stdin.
        model: Claude model to use.
        max_conversation_turns: Max back-and-forth exchanges.

    Returns:
        Structured Intent capturing what the user wants verified.
    """
    repo_path = Path(repo_path).resolve()

    if on_message is None:
        on_message = print
    if get_input is None:
        get_input = lambda prompt: input(f"\n{prompt}\n> ")

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": CONVERSATION_SYSTEM_PROMPT,
        },
        model=model,
        permission_mode="bypassPermissions",
        cwd=str(repo_path),
        allowed_tools=["Read", "Glob", "Grep", "Bash"],
        setting_sources=["user"],
        max_turns=50,
    )

    async with ClaudeSDKClient(options=options) as client:
        # Initial: agent explores repo and presents what it found
        initial_prompt = (
            "Explore this repository to understand its structure, modules, and "
            "key functionality. Then give me a brief summary of what you found "
            "and ask what I'd like to verify."
        )
        await client.query(initial_prompt)
        summary = await _drain_text(client)
        on_message(summary)

        # Conversation loop
        for turn in range(max_conversation_turns):
            user_input = get_input("Your response (or 'done' to finish)")

            if not user_input or user_input.strip().lower() in (
                "done",
                "confirm",
                "that's it",
                "that's all",
                "finished",
            ):
                break

            await client.query(user_input)
            response = await _drain_text(client)
            on_message(response)

        # Extract structured intent
        logger.info("Extracting structured intent from conversation...")
        await client.query(EXTRACT_INTENT_PROMPT)
        intent_text = await _drain_text(client)

    # Parse the intent JSON
    from . import _parse_json_from_text

    intent = _parse_json_from_text(intent_text, Intent)
    if intent is None:
        logger.warning("Could not parse intent from conversation, using fallback")
        intent = Intent(
            summary="Could not extract structured intent from conversation",
            context=intent_text[:500],
        )

    logger.info(
        f"Captured intent: {len(intent.requirements)} requirements, "
        f"{len(intent.priorities)} priorities"
    )
    return intent
