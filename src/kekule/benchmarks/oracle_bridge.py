"""
Oracle Bridge -- connects the oracle verification system to SWE-bench tasks.

Supports multiple oracle strategies (unit tests, regression checks, behavioral
assertions). The waypoint coordinator can adjust which strategies are active,
add new ones, and tune their prompts across epochs.
"""

import asyncio
import logging
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, Field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from kekule.oracle.schemas import OracleResult, Rule

from .task_selector import SWETask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Oracle Strategy models
# ---------------------------------------------------------------------------


class OracleStrategy(BaseModel):
    """Defines one type of oracle agent and how it verifies fixes."""

    name: str = Field(..., description="Strategy identifier (snake_case)")
    description: str = Field(
        ..., description="What this oracle type does"
    )
    agent_prompt: str = Field(
        ..., description="System prompt for the oracle generator agent"
    )
    execution_mode: str = Field(
        default="pytest",
        description="How to run the oracle: 'pytest' | 'bash'",
    )
    enabled: bool = Field(default=True, description="Whether this strategy is active")
    weight: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="How much this oracle's results matter (0=ignore, 2=critical)",
    )
    prompt_addendum: str = Field(
        default="",
        description="Extra instructions appended by the coordinator",
    )


# ---------------------------------------------------------------------------
# Default oracle strategies
# ---------------------------------------------------------------------------

UNIT_TEST_PROMPT = """
You are an Oracle Generator for SWE-bench verification.

## Your Mission
Given a GitHub issue (problem statement), generate pytest tests that verify whether
a fix correctly addresses the reported behavior.

## Workflow
1. Read the problem statement carefully. Identify what behavior is broken.
2. Explore the codebase to understand the relevant modules, classes, and functions.
3. Write pytest tests that:
   - Test the specific behavior described in the issue
   - Include at least one test for the main fix
   - Include at least one edge case test
4. Write the test file to the specified output path.

## Test Quality
- Tests MUST be runnable with `pytest <file>` (no extra flags)
- Tests MUST import from the codebase correctly (verify import paths exist)
- Tests MUST have clear assertion messages
- Tests SHOULD NOT modify the codebase (read-only verification)
- Tests SHOULD be focused on the issue, not general functionality
- Do NOT use external fixtures unless verified in conftest.py
- Do NOT make network calls
"""

REGRESSION_CHECK_PROMPT = """
You are a Regression Oracle Generator for SWE-bench verification.

## Your Mission
Given a GitHub issue, generate pytest tests that verify the fix does NOT break
existing functionality in the affected modules.

## Workflow
1. Read the problem statement to identify which modules are affected.
2. Explore the codebase to find existing public APIs and usage patterns.
3. Write pytest tests that verify:
   - Existing functionality still works after the fix
   - Related methods/functions aren't broken
   - Type contracts are maintained
4. Write the test file to the specified output path.

## Test Quality
- Focus on EXISTING behavior, not the new fix
- Test the public API of affected modules
- Use real module imports (verify they exist)
- Tests should pass on BOTH the original and fixed code
"""

BEHAVIORAL_ASSERTION_PROMPT = """
You are a Behavioral Oracle Generator for SWE-bench verification.

## Your Mission
Given a GitHub issue, generate lightweight behavioral checks as bash scripts.
These are quick smoke tests that verify basic correctness.

## Workflow
1. Read the problem statement.
2. Explore the codebase to understand imports and module structure.
3. Write a bash script that:
   - Uses `python -c "..."` to import and test key behaviors
   - Exits 0 if all checks pass, non-zero otherwise
   - Prints clear messages about what passed/failed
4. Write the script to the specified output path.

## Script Quality
- Each check should be a single python -c command
- Use set -e to fail fast
- Print descriptive messages before each check
- Keep it under 20 checks -- focus on the most important behaviors
"""

DEFAULT_ORACLE_STRATEGIES = [
    OracleStrategy(
        name="unit_test",
        description=(
            "Generate focused pytest unit tests that verify the fix "
            "handles the reported behavior"
        ),
        agent_prompt=UNIT_TEST_PROMPT,
        execution_mode="pytest",
    ),
    OracleStrategy(
        name="regression_check",
        description=(
            "Generate tests that verify the fix doesn't break "
            "existing functionality"
        ),
        agent_prompt=REGRESSION_CHECK_PROMPT,
        execution_mode="pytest",
    ),
    OracleStrategy(
        name="behavioral_assertion",
        description=(
            "Generate simple bash-based behavioral checks "
            "(import, call, assert)"
        ),
        agent_prompt=BEHAVIORAL_ASSERTION_PROMPT,
        execution_mode="bash",
    ),
]


# ---------------------------------------------------------------------------
# Rule generation from SWE-bench tasks
# ---------------------------------------------------------------------------


def _build_rule_gen_prompt(
    task: SWETask,
    strategy: OracleStrategy,
    output_path: Path,
) -> str:
    """Build the prompt for an oracle generator agent."""
    addendum = ""
    if strategy.prompt_addendum:
        addendum = f"\n## Additional Instructions\n{strategy.prompt_addendum}\n"

    return f"""## GitHub Issue

**Repository:** {task.repo}
**Instance ID:** {task.instance_id}

### Problem Statement

{task.problem_statement}

---
{addendum}
## Task

Generate verification artifacts for this issue.
Write the output file to: `{output_path}`

The repository is in your current working directory. Explore it to understand
the code structure before writing tests.
"""


async def generate_strategy_artifact(
    task: SWETask,
    repo_dir: Path,
    strategy: OracleStrategy,
    output_dir: Path,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 15,
) -> Path | None:
    """Generate oracle artifacts for a single strategy.

    Returns the path to the generated artifact, or None if generation failed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if strategy.execution_mode == "pytest":
        artifact_path = output_dir / f"test_oracle_{strategy.name}.py"
    else:
        artifact_path = output_dir / f"check_{strategy.name}.sh"

    prompt = _build_rule_gen_prompt(task, strategy, artifact_path)

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": strategy.agent_prompt,
        },
        model=model,
        permission_mode="bypassPermissions",
        cwd=str(repo_dir),
        allowed_tools=["Read", "Write", "Glob", "Grep", "Bash"],
        setting_sources=["user"],
        max_turns=max_turns,
    )

    start_time = time.time()
    logger.info(f"[oracle:{strategy.name}] Generating artifact for {task.instance_id}...")

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        logger.debug(f"[oracle:{strategy.name}] tool: {block.name}")
            elif isinstance(message, ResultMessage):
                elapsed = time.time() - start_time
                logger.info(
                    f"[oracle:{strategy.name}] Agent completed: "
                    f"turns={message.num_turns}, "
                    f"cost=${message.total_cost_usd or 0:.4f}, "
                    f"time={elapsed:.1f}s"
                )
                if message.is_error:
                    logger.error(
                        f"[oracle:{strategy.name}] Agent error: {message.result}"
                    )
    except Exception as e:
        logger.error(f"[oracle:{strategy.name}] Generation failed: {e}")
        return None

    if not artifact_path.exists():
        logger.warning(
            f"[oracle:{strategy.name}] Agent did not create artifact at {artifact_path}"
        )
        return None

    logger.info(f"[oracle:{strategy.name}] Artifact written to {artifact_path}")
    return artifact_path


async def generate_task_oracles(
    task: SWETask,
    repo_dir: Path,
    strategies: list[OracleStrategy] | None = None,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 15,
    max_parallel: int = 3,
) -> dict[str, Path]:
    """Generate oracle artifacts for all enabled strategies.

    Args:
        task: The SWE-bench task.
        repo_dir: Path to the repository.
        strategies: Oracle strategies to use. Defaults to DEFAULT_ORACLE_STRATEGIES.
        model: Model for oracle generation agents.
        max_turns: Max agent turns per strategy.
        max_parallel: Max concurrent oracle generations.

    Returns:
        Dict mapping strategy_name -> artifact path.
    """
    if strategies is None:
        strategies = DEFAULT_ORACLE_STRATEGIES

    enabled = [s for s in strategies if s.enabled]
    if not enabled:
        logger.warning("No oracle strategies enabled")
        return {}

    semaphore = asyncio.Semaphore(max_parallel)
    results: dict[str, Path] = {}

    async def _gen_with_limit(strategy: OracleStrategy) -> tuple[str, Path | None]:
        async with semaphore:
            output_dir = repo_dir / "oracle_tests" / strategy.name
            path = await generate_strategy_artifact(
                task=task,
                repo_dir=repo_dir,
                strategy=strategy,
                output_dir=output_dir,
                model=model,
                max_turns=max_turns,
            )
            return strategy.name, path

    completed = await asyncio.gather(
        *[_gen_with_limit(s) for s in enabled],
        return_exceptions=True,
    )

    for result in completed:
        if isinstance(result, Exception):
            logger.error(f"Oracle generation error: {result}")
            continue
        name, path = result
        if path is not None:
            results[name] = path

    logger.info(
        f"Generated {len(results)}/{len(enabled)} oracle artifacts "
        f"for {task.instance_id}"
    )
    return results


# ---------------------------------------------------------------------------
# Oracle execution (run checks in workspace)
# ---------------------------------------------------------------------------


async def run_pytest_oracle(
    artifact_path: Path,
    repo_dir: Path,
    timeout_s: int = 120,
) -> OracleResult:
    """Run a pytest oracle artifact directly in the workspace.

    No Docker — runs pytest in the repo directory for speed.
    The workspace is already isolated per-agent.
    """
    start_time = time.time()
    strategy_name = artifact_path.parent.name

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "python", "-m", "pytest",
                str(artifact_path),
                "--tb=short", "-v", "--no-header",
                "-x",  # Stop on first failure
            ],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

        elapsed = time.time() - start_time
        passed = result.returncode == 0
        evidence = result.stdout
        if result.stderr:
            evidence += f"\n--- stderr ---\n{result.stderr}"

        logger.info(
            f"[oracle:{strategy_name}] {'PASSED' if passed else 'FAILED'} "
            f"(exit_code={result.returncode}, time={elapsed:.1f}s)"
        )

        return OracleResult(
            rule_id=strategy_name,
            passed=passed,
            evidence=evidence,
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=result.returncode,
        )

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"[oracle:{strategy_name}] Timed out after {timeout_s}s")
        return OracleResult(
            rule_id=strategy_name,
            passed=False,
            evidence=f"Timed out after {timeout_s}s",
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=-1,
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[oracle:{strategy_name}] Error: {e}")
        return OracleResult(
            rule_id=strategy_name,
            passed=False,
            evidence=str(e),
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=-1,
        )


async def run_bash_oracle(
    artifact_path: Path,
    repo_dir: Path,
    timeout_s: int = 60,
) -> OracleResult:
    """Run a bash oracle script directly in the workspace."""
    start_time = time.time()
    strategy_name = artifact_path.parent.name

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["bash", str(artifact_path)],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

        elapsed = time.time() - start_time
        passed = result.returncode == 0
        evidence = result.stdout
        if result.stderr:
            evidence += f"\n--- stderr ---\n{result.stderr}"

        logger.info(
            f"[oracle:{strategy_name}] {'PASSED' if passed else 'FAILED'} "
            f"(exit_code={result.returncode}, time={elapsed:.1f}s)"
        )

        return OracleResult(
            rule_id=strategy_name,
            passed=passed,
            evidence=evidence,
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=result.returncode,
        )

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return OracleResult(
            rule_id=strategy_name,
            passed=False,
            evidence=f"Timed out after {timeout_s}s",
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=-1,
        )
    except Exception as e:
        elapsed = time.time() - start_time
        return OracleResult(
            rule_id=strategy_name,
            passed=False,
            evidence=str(e),
            artifact_path=str(artifact_path),
            execution_time_s=elapsed,
            exit_code=-1,
        )


async def run_oracle_checks(
    artifact_paths: dict[str, Path],
    strategies: list[OracleStrategy],
    repo_dir: Path,
    max_parallel: int = 3,
) -> dict[str, OracleResult]:
    """Run all oracle artifacts and collect results.

    Args:
        artifact_paths: Dict mapping strategy_name -> artifact path.
        strategies: List of OracleStrategy configs.
        repo_dir: Repository directory.
        max_parallel: Max concurrent oracle executions.

    Returns:
        Dict mapping strategy_name -> OracleResult.
    """
    strategy_map = {s.name: s for s in strategies}
    semaphore = asyncio.Semaphore(max_parallel)
    results: dict[str, OracleResult] = {}

    async def _run_with_limit(
        name: str, path: Path
    ) -> tuple[str, OracleResult]:
        async with semaphore:
            strategy = strategy_map.get(name)
            if strategy and strategy.execution_mode == "bash":
                result = await run_bash_oracle(path, repo_dir)
            else:
                result = await run_pytest_oracle(path, repo_dir)
            return name, result

    completed = await asyncio.gather(
        *[
            _run_with_limit(name, path)
            for name, path in artifact_paths.items()
        ],
        return_exceptions=True,
    )

    for item in completed:
        if isinstance(item, Exception):
            logger.error(f"Oracle execution error: {item}")
            continue
        name, result = item
        results[name] = result

    passed = sum(1 for r in results.values() if r.passed)
    total = len(results)
    logger.info(f"Oracle checks: {passed}/{total} passed")

    return results


# ---------------------------------------------------------------------------
# Feedback formatting
# ---------------------------------------------------------------------------


def format_oracle_feedback(
    results: dict[str, OracleResult],
    strategies: list[OracleStrategy] | None = None,
) -> str:
    """Format oracle results as feedback text for the swarm's next round.

    Args:
        results: Dict mapping strategy_name -> OracleResult.
        strategies: Strategy configs (for descriptions and weights).

    Returns:
        Formatted feedback string for injection into the swarm prompt.
    """
    strategy_map = {}
    if strategies:
        strategy_map = {s.name: s for s in strategies}

    lines = ["## Oracle Verification Results\n"]

    passed_all = all(r.passed for r in results.values())
    if passed_all:
        lines.append("**All oracle checks PASSED.**\n")
    else:
        failed = [name for name, r in results.items() if not r.passed]
        lines.append(
            f"**{len(failed)} oracle check(s) FAILED.** "
            f"Fix the issues below before accepting the patch.\n"
        )

    for name, result in sorted(results.items()):
        strategy = strategy_map.get(name)
        desc = strategy.description if strategy else name
        mark = "PASS" if result.passed else "FAIL"
        lines.append(f"### [{mark}] {name}: {desc}")

        if not result.passed and result.evidence:
            # Show last 30 lines of evidence to keep context manageable
            evidence_lines = result.evidence.strip().split("\n")
            tail = evidence_lines[-30:]
            lines.append("```")
            lines.extend(tail)
            lines.append("```")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Strategy adjustment (applied by waypoint coordinator)
# ---------------------------------------------------------------------------


def apply_oracle_adjustments(
    strategies: list[OracleStrategy],
    adjustments: dict,
) -> list[OracleStrategy]:
    """Apply coordinator adjustments to the oracle strategy list.

    Adjustments is a dict where keys are strategy names and values are
    dicts of fields to update. Special key "__new__" adds new strategies.

    Examples:
        {"regression_check": {"enabled": false}}
        {"unit_test": {"prompt_addendum": "Focus on edge cases"}}
        {"e2e_test": {"description": "...", "agent_prompt": "...",
                       "execution_mode": "bash", "__new__": true}}
    """
    strategy_map = {s.name: s for s in strategies}

    for name, changes in adjustments.items():
        if not isinstance(changes, dict):
            continue

        if changes.pop("__new__", False) or name not in strategy_map:
            # Create a new strategy
            try:
                new_strategy = OracleStrategy(name=name, **changes)
                strategy_map[name] = new_strategy
                logger.info(f"Added new oracle strategy: {name}")
            except Exception as e:
                logger.warning(f"Failed to create oracle strategy '{name}': {e}")
        else:
            # Update existing strategy
            existing = strategy_map[name]
            updated_data = existing.model_dump()
            updated_data.update(changes)
            try:
                strategy_map[name] = OracleStrategy(**updated_data)
                logger.info(f"Updated oracle strategy: {name}")
            except Exception as e:
                logger.warning(f"Failed to update oracle strategy '{name}': {e}")

    return list(strategy_map.values())
