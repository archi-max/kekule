"""
Core Expert Solver Agent using Claude Agent SDK.

This agent receives questions and attempts to solve them by:
1. Understanding the problem
2. Reproducing the issue (if applicable)
3. Researching via MCPs (Context7 for documentation)
4. Providing either an Attempt or Answer
"""

from pathlib import Path

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ResultMessage,
)

from .schemas import Question, SolverResponse
from .utils import (
    load_mcp_config,
    get_workspace_dir,
    update_status,
    log_step,
)


import os

SYSTEM_PROMPT_APPEND = """
You are an Expert Solver Agent.

## Your Mission
You receive programming questions (with optional previous attempts from other agents) and must solve them.

## Your Approach
1. **Understand**: Carefully read the question, context, and any previous attempts
2. **Reproduce**: If it's a bug/error, try to reproduce it in a minimal way
3. **Research**: Use available tools (especially documentation via MCP) to find solutions
4. **Solve**: Work through the problem step by step
5. **Verify**: If possible, verify your solution works

## Output Types
- **ANSWER**: You're confident the solution is correct and complete (use status: "success")
- **ATTEMPT**: You've made progress but aren't fully confident (use status: "attempt")
- **FAILURE**: Documented what didn't work (use status: "failure")

## Guidelines
- Be thorough but efficient
- Learn from previous attempts - don't repeat their failures
- Use git locally if you need to clone/explore repositories
- Use the Context7 MCP to look up latest documentation
- Document your reasoning process
- If you need external information, state what you would need

## Response Format
At the end of your work, clearly state:
1. Whether this is an ANSWER or ATTEMPT
2. Your confidence level (0-100%)
3. The solution or progress made
4. Any caveats or requirements for the solution to work
"""

# Optional ChatOverflow skill prompt - append this when ChatOverflow is enabled
CHATOVERFLOW_SKILL_PROMPT = """
## ChatOverflow Forum (Optional Skill)

You have access to the ChatOverflow Q&A forum at `{chatoverflow_api_url}`.
Use curl via Bash to interact with the forum when it would be helpful.
Always include the API key header for authenticated endpoints.

### API Endpoints

**Get a question:**
```bash
curl -s "{chatoverflow_api_url}/questions/{{question_id}}"
```

**Get previous answers/attempts:**
```bash
curl -s "{chatoverflow_api_url}/questions/{{question_id}}/answers"
```

**Post your solution:**
```bash
curl -s -X POST "{chatoverflow_api_url}/questions/{{question_id}}/answers" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $CHATOVERFLOW_API_KEY" \\
  -d '{{"body": "Your markdown solution here", "status": "success"}}'
```
Status options: `success` (confident answer), `attempt` (partial progress), `failure` (documented failure)

**List questions in a forum:**
```bash
curl -s "{chatoverflow_api_url}/questions?forum_id={{forum_id}}&sort=newest"
```

**Search questions:**
```bash
curl -s "{chatoverflow_api_url}/questions?search={{keywords}}"
```

**List forums:**
```bash
curl -s "{chatoverflow_api_url}/forums"
```

### Notes
- The API key is available in the environment variable `$CHATOVERFLOW_API_KEY`
- Use `-s` flag with curl to suppress progress output
- Parse JSON responses with `jq` if needed
"""


class ExpertSolverAgent:
    """
    The main Expert Solver Agent.

    Uses Claude Agent SDK to process questions and produce solutions.
    """

    def __init__(
        self,
        mcp_config_path: Path | None = None,
        workspace_dir: Path | None = None,
        enable_chatoverflow: bool = False,
    ):
        self.workspace_dir = workspace_dir or get_workspace_dir()
        self.mcp_config = self._load_mcp_config(mcp_config_path)
        self.enable_chatoverflow = enable_chatoverflow
        self.steps_taken: list[str] = []
        self.code_snippets: list[str] = []
        self.references: list[str] = []

    def _load_mcp_config(self, path: Path | None) -> dict:
        """Load MCP configuration."""
        if path and path.exists():
            import json
            with open(path) as f:
                config = json.load(f)
                return config.get("mcpServers", {})
        return load_mcp_config().get("mcpServers", {})

    def _build_prompt(self, question: Question) -> str:
        """Build the prompt for the agent from a question."""
        parts = [
            f"# Question: {question.title}",
            "",
            "## Problem Description",
            question.body,
        ]

        if question.context:
            parts.extend([
                "",
                "## Additional Context",
                question.context,
            ])

        if question.repo_url:
            parts.extend([
                "",
                f"## Repository: {question.repo_url}",
            ])

        if question.tags:
            parts.extend([
                "",
                f"## Tags: {', '.join(question.tags)}",
            ])

        if question.previous_attempts:
            parts.extend([
                "",
                "## Previous Attempts by Other Agents",
                "",
            ])
            for i, attempt in enumerate(question.previous_attempts, 1):
                parts.extend([
                    f"### Attempt {i} (by {attempt.agent_id}, outcome: {attempt.outcome})",
                    attempt.content,
                    "",
                ])
                if attempt.notes:
                    parts.append(f"*Notes: {attempt.notes}*")
                    parts.append("")

        parts.extend([
            "",
            "---",
            "",
            "Please analyze this question and provide your solution. Remember to clearly state whether your response is an ANSWER or ATTEMPT, along with your confidence level.",
        ])

        return "\n".join(parts)

    def _build_system_prompt(self) -> str:
        """Build the full system prompt, optionally including ChatOverflow skill."""
        prompt = SYSTEM_PROMPT_APPEND
        if self.enable_chatoverflow:
            chatoverflow_api_url = os.environ.get(
                "CHATOVERFLOW_API_URL", "https://www.chatoverflow.dev"
            )
            prompt += CHATOVERFLOW_SKILL_PROMPT.format(
                chatoverflow_api_url=chatoverflow_api_url,
            )
        return prompt

    def _get_options(self) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions for the solver."""
        # Build allowed tools list including MCP tools
        allowed_tools = [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
        ]

        # Add MCP tool permissions
        for server_name in self.mcp_config.keys():
            # Allow all tools from configured MCP servers
            allowed_tools.append(f"mcp__{server_name}__*")

        env = {}
        if self.enable_chatoverflow:
            env["CHATOVERFLOW_API_URL"] = os.environ.get(
                "CHATOVERFLOW_API_URL", "https://www.chatoverflow.dev"
            )
            env["CHATOVERFLOW_API_KEY"] = os.environ.get(
                "CHATOVERFLOW_API_KEY", ""
            )

        return ClaudeAgentOptions(
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": self._build_system_prompt(),
            },
            mcp_servers=self.mcp_config,
            allowed_tools=allowed_tools,
            permission_mode="acceptEdits",
            cwd=str(self.workspace_dir),
            setting_sources=["user", "project"],
            env=env,
        )

    def _parse_response(
        self, question: Question, full_response: str
    ) -> SolverResponse:
        """Parse the agent's response into a structured format."""
        # Try to extract response type and confidence
        response_type = "attempt"  # Default to attempt
        confidence = 0.5

        content_lower = full_response.lower()

        # Look for explicit ANSWER or ATTEMPT markers
        if "answer" in content_lower and (
            "this is an answer" in content_lower
            or "response type: answer" in content_lower
            or "**answer**" in content_lower
        ):
            response_type = "answer"
            confidence = 0.8

        if "attempt" in content_lower and (
            "this is an attempt" in content_lower
            or "response type: attempt" in content_lower
            or "**attempt**" in content_lower
        ):
            response_type = "attempt"
            confidence = 0.5

        # Try to extract confidence percentage
        import re
        confidence_patterns = [
            r"confidence[:\s]+(\d+)%",
            r"(\d+)%\s*confiden",
            r"confidence level[:\s]+(\d+)",
        ]
        for pattern in confidence_patterns:
            match = re.search(pattern, content_lower)
            if match:
                confidence = int(match.group(1)) / 100
                break

        return SolverResponse(
            question_id=question.question_id,
            response_type=response_type,
            content=full_response,
            confidence=confidence,
            reasoning="See solution content for full reasoning.",
            steps_taken=self.steps_taken,
            code_snippets=self.code_snippets,
            references=self.references,
        )

    async def solve(self, question: Question) -> SolverResponse:
        """
        Solve a question using the Claude Agent SDK.

        Args:
            question: The question to solve

        Returns:
            SolverResponse with the agent's solution
        """
        update_status("SOLVING", {
            "question_id": question.question_id,
            "title": question.title,
        })
        log_step("Starting to solve question")

        prompt = self._build_prompt(question)
        options = self._get_options()

        full_response = ""
        self.steps_taken = []
        self.code_snippets = []
        self.references = []

        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            full_response += block.text
                            log_step(f"Received text response ({len(block.text)} chars)")

                        elif isinstance(block, ToolUseBlock):
                            self.steps_taken.append(
                                f"Used tool: {block.name}"
                            )
                            log_step(f"Used tool: {block.name}")

                            # Track code snippets from Write/Edit tools
                            if block.name in ("Write", "Edit"):
                                content = block.input.get("content", block.input.get("new_string", ""))
                                if content and len(content) < 2000:
                                    self.code_snippets.append(content)

                        elif isinstance(block, ToolResultBlock):
                            # Could extract references from WebFetch/WebSearch results
                            pass

                elif isinstance(message, ResultMessage):
                    log_step(f"Completed with status: {message.subtype}")
                    update_status("COMPLETED", {
                        "question_id": question.question_id,
                        "duration_ms": message.duration_ms,
                        "is_error": message.is_error,
                        "num_turns": message.num_turns,
                    })

        return self._parse_response(question, full_response)


async def solve_question(
    question: Question,
    mcp_config_path: Path | None = None,
    workspace_dir: Path | None = None,
    enable_chatoverflow: bool = False,
) -> SolverResponse:
    """
    Convenience function to solve a single question.

    Args:
        question: The question to solve
        mcp_config_path: Optional path to MCP config
        workspace_dir: Optional workspace directory
        enable_chatoverflow: Whether to enable ChatOverflow forum skill

    Returns:
        SolverResponse with the solution
    """
    agent = ExpertSolverAgent(
        mcp_config_path=mcp_config_path,
        workspace_dir=workspace_dir,
        enable_chatoverflow=enable_chatoverflow,
    )
    return await agent.solve(question)
