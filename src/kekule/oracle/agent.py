"""
Oracle Agent -- generates pytest verification artifacts from Rules.

Takes a Rule + repo context, explores the codebase using Claude Agent SDK
tools, and writes a focused, deterministic pytest test file.
"""

import asyncio
import logging
import time
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from .schemas import Rule

logger = logging.getLogger(__name__)


ORACLE_AGENT_SYSTEM_PROMPT = """
You are an Oracle Generator for the Kekule verification system.

## Your Mission
Given a Rule (acceptance criteria), explore the repository and generate a pytest test file
that deterministically verifies whether the codebase satisfies the rule.

## Workflow
1. Read the Rule's description and oracle_config carefully.
2. Explore the relevant parts of the codebase using Read, Glob, Grep, Bash.
3. Understand the actual code structure, imports, and module layout.
4. Write a pytest test file that verifies the rule.
5. Write the test file to the specified output path using the Write tool.

## Test Quality Requirements
- Tests MUST be deterministic (no randomness, no timing dependencies)
- Tests MUST be focused (test exactly what the rule describes, nothing more)
- Tests MUST have clear assertion messages explaining what failed
- Tests MUST import from the codebase correctly (verify import paths exist before using them)
- Tests MUST be runnable with just `pytest <file>` (no extra flags required)
- Tests SHOULD NOT modify the codebase (read-only verification)
- Tests SHOULD include a module-level docstring explaining what rule they verify
- Tests SHOULD cover the main case and edge cases from oracle_config if specified
- Tests SHOULD use descriptive function names like `test_<what_is_being_verified>`

## Important
- Do NOT assume module structure -- explore with Glob and Read first
- Do NOT use external test fixtures unless you've verified they exist in conftest.py
- Do NOT make network calls in tests
- Do NOT write tests that depend on mutable global state
- After writing the test file, verify it exists with Read
"""


async def generate_oracle(
    rule: Rule,
    repo_path: str | Path,
    output_dir: str | Path | None = None,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 30,
) -> Path:
    """Generate a pytest oracle artifact for a single rule.

    The agent explores the repo, understands the codebase, and writes
    a pytest test file that verifies the rule.

    Args:
        rule: The Rule to generate a verification test for.
        repo_path: Path to the repository to verify against.
        output_dir: Directory for oracle artifacts. Defaults to
                     repo_path/oracle_artifacts/<rule.id>/
        model: Model to use for generation.
        max_turns: Max agent turns.

    Returns:
        Path to the generated test file.

    Raises:
        RuntimeError: If the agent fails to create the test file.
    """
    repo_path = Path(repo_path).resolve()
    if not repo_path.exists():
        raise FileNotFoundError(f"Repository not found: {repo_path}")

    if output_dir is None:
        output_dir = repo_path / "oracle_artifacts" / rule.id
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    test_file = output_dir / f"test_oracle_{rule.id}.py"
    prompt = _build_oracle_prompt(rule, test_file)

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": ORACLE_AGENT_SYSTEM_PROMPT,
        },
        model=model,
        permission_mode="bypassPermissions",
        cwd=str(repo_path),
        allowed_tools=["Read", "Write", "Glob", "Grep", "Bash"],
        setting_sources=["user"],
        max_turns=max_turns,
    )

    start_time = time.time()
    logger.info(f"[{rule.id}] Generating oracle artifact...")

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    logger.debug(f"[{rule.id}] tool: {block.name}")
                elif isinstance(block, TextBlock) and len(block.text) > 100:
                    logger.debug(f"[{rule.id}] text: {block.text[:80]}...")
        elif isinstance(message, ResultMessage):
            elapsed = time.time() - start_time
            logger.info(
                f"[{rule.id}] Agent completed: turns={message.num_turns}, "
                f"cost=${message.total_cost_usd or 0:.4f}, "
                f"time={elapsed:.1f}s"
            )
            if message.is_error:
                logger.error(f"[{rule.id}] Agent error: {message.result}")

    if not test_file.exists():
        raise RuntimeError(
            f"Oracle agent failed to create test file: {test_file}. "
            f"Rule: {rule.id} ({rule.description})"
        )

    logger.info(f"[{rule.id}] Oracle artifact written to {test_file}")
    return test_file


async def generate_all_oracles(
    rules: list[Rule],
    repo_path: str | Path,
    output_dir: str | Path | None = None,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 30,
    max_parallel: int = 3,
) -> dict[str, Path]:
    """Generate oracle artifacts for multiple rules with concurrency control.

    Args:
        rules: List of rules to generate oracles for.
        repo_path: Path to the repository.
        output_dir: Base directory for artifacts. If None, uses
                     repo_path/oracle_artifacts/<rule_id>/ per rule.
        model: Model to use.
        max_turns: Max turns per oracle generation.
        max_parallel: Max concurrent oracle generations.

    Returns:
        Dict mapping rule_id -> artifact path.
    """
    semaphore = asyncio.Semaphore(max_parallel)
    results: dict[str, Path] = {}
    errors: list[str] = []

    async def _generate_with_limit(rule: Rule) -> tuple[str, Path | None]:
        async with semaphore:
            try:
                rule_output_dir = None
                if output_dir is not None:
                    rule_output_dir = Path(output_dir) / rule.id
                path = await generate_oracle(
                    rule=rule,
                    repo_path=repo_path,
                    output_dir=rule_output_dir,
                    model=model,
                    max_turns=max_turns,
                )
                return rule.id, path
            except Exception as e:
                logger.error(f"[{rule.id}] Oracle generation failed: {e}")
                return rule.id, None

    tasks = [_generate_with_limit(rule) for rule in rules]
    completed = await asyncio.gather(*tasks, return_exceptions=True)

    for result in completed:
        if isinstance(result, Exception):
            logger.error(f"Unexpected error: {result}")
            continue
        rule_id, path = result
        if path is not None:
            results[rule_id] = path
        else:
            errors.append(rule_id)

    if errors:
        logger.warning(
            f"Failed to generate oracles for {len(errors)} rules: {errors}"
        )

    return results


def _build_oracle_prompt(rule: Rule, test_file: Path) -> str:
    """Build the prompt sent to the oracle-generating agent."""
    config_section = ""
    if rule.oracle_config:
        import json

        config_section = (
            f"\n### Oracle Configuration\n"
            f"```json\n{json.dumps(rule.oracle_config, indent=2)}\n```\n"
        )

    return f"""## Rule to Verify

**Rule ID:** {rule.id}
**Description:** {rule.description}
**Oracle Type:** {rule.oracle_type.value}
**Uncertainty:** {rule.uncertainty}
{config_section}
## Task

1. Explore this repository to understand the relevant code.
2. Write a pytest test file that verifies the rule described above.
3. Write the test file to: `{test_file}`

The test file should be self-contained and runnable with `pytest {test_file}`.
"""
