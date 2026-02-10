"""Simple example using Claude Agents SDK."""

import asyncio
import os
from anthropic import Anthropic


async def main():
    """Run a simple query using Claude."""
    # Initialize the Anthropic client
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Simple query example
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": "What is the capital of France?"
            }
        ]
    )

    print("Response:", message.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
