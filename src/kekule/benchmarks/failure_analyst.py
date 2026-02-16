"""
Failure Analyst -- per-task post-mortem agent that diagnoses WHY a swarm failed.

Runs after evaluation, before the waypoint coordinator. For each failed train
task, spawns a Claude agent that reads:
  1. The problem statement (what was the issue)
  2. The agent logs (what the swarm did)
  3. The eval test results (which tests passed/failed and why)
  4. The patch produced (what the swarm changed)

Produces a structured diagnosis: root cause of failure, what the swarm missed,
what behaviors needed fixing, and actionable suggestions.

These diagnoses feed into the waypoint coordinator, giving it much richer
per-task signal than raw logs alone.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

logger = logging.getLogger(__name__)


@dataclass
class FailureDiagnosis:
    """Structured diagnosis of why a swarm failed on a task."""

    instance_id: str
    root_cause: str  # Why the fix didn't work
    what_swarm_missed: list[str]  # Specific things the swarm overlooked
    behaviors_to_fix: list[str]  # Distinct behaviors the issue required
    test_analysis: str  # What the failing tests actually expected
    suggestion: str  # What the swarm should do differently
    confidence: float  # 0-1 how confident the analyst is


FAILURE_ANALYST_PROMPT = """
You are a Failure Analyst for a multi-agent swarm that solves GitHub issues.

## Your Mission
A swarm of agents attempted to fix a GitHub issue but FAILED. Your job is to
figure out exactly WHY and produce a structured diagnosis.

## What You Receive
- The problem statement (the GitHub issue)
- What the swarm agents did (their reasoning and tool calls)
- The evaluation results (which tests passed, which still fail)
- The patch the swarm produced (if any)

## What You Must Output

Output a JSON object with these exact keys:

```json
{
  "root_cause": "One sentence explaining the primary reason the fix failed",
  "what_swarm_missed": [
    "Specific thing 1 the swarm overlooked",
    "Specific thing 2 the swarm overlooked"
  ],
  "behaviors_to_fix": [
    "Distinct behavior 1 that the issue required changing",
    "Distinct behavior 2 that the issue required changing"
  ],
  "test_analysis": "What the failing tests actually expected vs what the fix produced",
  "suggestion": "Concrete actionable advice for the next attempt",
  "confidence": 0.8
}
```

## Analysis Guidelines

1. **Read the failing test names carefully.** The test name often tells you exactly
   what behavior is being verified.

2. **Compare expected vs actual.** If a test asserts `assertEqual(result, None)`,
   but the fix raises `KeyError`, the root cause is "missing None fallback."

3. **Count distinct behaviors.** An issue might require 2-3 different code changes.
   If the swarm only made 1, that's the root cause.

4. **Check side effects.** Tests that use `assertNotEqual` are checking that
   something CHANGED. The fix might validate correctly but miss the state change.

5. **Look for over-engineering.** Sometimes the swarm adds too much code when a
   simpler fix (even deletion) would work.

6. **Be specific, not generic.** "The fix was wrong" is useless. "The fix accessed
   data['attrs']['id'] without .get(), causing KeyError when no id exists" is useful.

7. **Suggest oracle checks.** For each failure, think: "What automated test or check
   would have caught this BEFORE submission?" Include this in your suggestion field.
   E.g., "An oracle that runs the full test module (not just target tests) would have
   caught the 116 regressions." or "An oracle that checks return types match the
   original method signature would have caught the None vs KeyError mismatch."

## Turn Budget
You have up to 30 tool-call turns. Use them wisely:
- First, READ the data provided in this prompt carefully
- Use Read/Grep/Bash to explore test output files, eval reports, or repo code if needed
- You MUST output the JSON diagnosis before your turns run out
- If you've explored enough, STOP exploring and output the JSON immediately
- Better to produce a partial diagnosis than no diagnosis at all

Output ONLY the JSON object, no other text.
"""


def _build_analyst_prompt(
    instance_id: str,
    problem_statement: str,
    agent_logs: str,
    eval_tests: dict | None,
    patch: str,
) -> str:
    """Build the prompt for the failure analyst agent."""
    sections = [f"## Task: {instance_id}\n"]

    sections.append(f"### Problem Statement\n{problem_statement}\n")

    if patch:
        # Truncate very long patches
        patch_display = patch[:3000] + "\n...(truncated)" if len(patch) > 3000 else patch
        sections.append(f"### Patch Produced\n```diff\n{patch_display}\n```\n")
    else:
        sections.append("### Patch Produced\nNo patch was generated.\n")

    if eval_tests:
        sections.append("### Evaluation Test Results")
        fixed = eval_tests.get("fail_to_pass_fixed", [])
        still_failing = eval_tests.get("fail_to_pass_still_failing", [])
        regressed = eval_tests.get("pass_to_pass_regressed", [])

        if fixed:
            sections.append(f"Tests the fix CORRECTLY fixed ({len(fixed)}):")
            for t in fixed[:10]:
                sections.append(f"  - {t}")
        if still_failing:
            sections.append(f"Tests that STILL FAIL ({len(still_failing)}):")
            for t in still_failing[:10]:
                sections.append(f"  - {t}")
        if regressed:
            sections.append(f"REGRESSIONS - tests that used to pass but now fail ({len(regressed)}):")
            for t in regressed[:10]:
                sections.append(f"  - {t}")
        if not still_failing and not regressed:
            sections.append("All target tests passed, no regressions.")
        sections.append("")
    else:
        sections.append("### Evaluation Test Results\nNo evaluation data available.\n")

    if agent_logs:
        log_display = agent_logs[:4000]
        sections.append(f"### Agent Activity Log\n```\n{log_display}\n```\n")

    sections.append("Analyze why this fix failed and output the JSON diagnosis.")

    return "\n".join(sections)


def _parse_diagnosis(text: str, instance_id: str) -> FailureDiagnosis:
    """Parse the analyst's JSON output into a FailureDiagnosis."""
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not obj_match:
        return FailureDiagnosis(
            instance_id=instance_id,
            root_cause="Analyst failed to produce structured output",
            what_swarm_missed=[],
            behaviors_to_fix=[],
            test_analysis="",
            suggestion="",
            confidence=0.0,
        )

    try:
        data = json.loads(obj_match.group())
    except json.JSONDecodeError:
        return FailureDiagnosis(
            instance_id=instance_id,
            root_cause="Analyst output was not valid JSON",
            what_swarm_missed=[],
            behaviors_to_fix=[],
            test_analysis=text[:500],
            suggestion="",
            confidence=0.0,
        )

    return FailureDiagnosis(
        instance_id=instance_id,
        root_cause=data.get("root_cause", "Unknown"),
        what_swarm_missed=data.get("what_swarm_missed", []),
        behaviors_to_fix=data.get("behaviors_to_fix", []),
        test_analysis=data.get("test_analysis", ""),
        suggestion=data.get("suggestion", ""),
        confidence=data.get("confidence", 0.5),
    )


async def analyze_failure(
    instance_id: str,
    problem_statement: str,
    agent_logs: str,
    eval_tests: dict | None,
    patch: str,
    model: str = "claude-sonnet-4-5",
    max_turns: int = 30,
) -> FailureDiagnosis:
    """Run the failure analyst on a single failed task.

    Args:
        instance_id: The SWE-bench instance ID.
        problem_statement: The GitHub issue text.
        agent_logs: Summarized agent activity log.
        eval_tests: Test breakdown from SWE-bench eval.
        patch: The git diff the swarm produced.
        model: Model for the analyst agent.
        max_turns: Max agent turns.

    Returns:
        FailureDiagnosis with structured analysis.
    """
    prompt = _build_analyst_prompt(
        instance_id, problem_statement, agent_logs, eval_tests, patch
    )

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": FAILURE_ANALYST_PROMPT,
        },
        model=model,
        permission_mode="bypassPermissions",
        allowed_tools=["Read", "Glob", "Grep", "Bash"],
        setting_sources=["user"],
        max_turns=max_turns,
    )

    last_text = ""
    start_time = time.time()

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        last_text = block.text
            elif isinstance(message, ResultMessage):
                elapsed = time.time() - start_time
                logger.info(
                    f"[analyst:{instance_id}] Completed: "
                    f"turns={message.num_turns}, "
                    f"cost=${message.total_cost_usd or 0:.4f}, "
                    f"time={elapsed:.1f}s"
                )
    except Exception as e:
        logger.error(f"[analyst:{instance_id}] Failed: {e}")
        return FailureDiagnosis(
            instance_id=instance_id,
            root_cause=f"Analyst agent failed: {e}",
            what_swarm_missed=[],
            behaviors_to_fix=[],
            test_analysis="",
            suggestion="",
            confidence=0.0,
        )

    return _parse_diagnosis(last_text, instance_id)


async def analyze_all_failures(
    failed_results: list[dict],
    tasks_by_id: dict,
    model: str = "claude-sonnet-4-5",
    max_parallel: int = 5,
) -> list[FailureDiagnosis]:
    """Run failure analysis on all failed tasks.

    Args:
        failed_results: Result dicts for tasks that failed (resolved=False).
        tasks_by_id: Dict mapping instance_id -> SWETask (for problem statements).
        model: Model for analyst agents.
        max_parallel: Max concurrent analysts.

    Returns:
        List of FailureDiagnosis objects.
    """
    if not failed_results:
        return []

    semaphore = asyncio.Semaphore(max_parallel)

    async def _analyze_with_limit(result: dict) -> FailureDiagnosis:
        async with semaphore:
            instance_id = result["instance_id"]
            task = tasks_by_id.get(instance_id)
            problem_statement = task.problem_statement if task else "Unknown"

            return await analyze_failure(
                instance_id=instance_id,
                problem_statement=problem_statement,
                agent_logs=result.get("agent_logs", ""),
                eval_tests=result.get("eval_tests"),
                patch=result.get("model_patch", ""),
                model=model,
            )

    diagnoses = await asyncio.gather(
        *[_analyze_with_limit(r) for r in failed_results],
        return_exceptions=True,
    )

    results: list[FailureDiagnosis] = []
    for d in diagnoses:
        if isinstance(d, Exception):
            logger.error(f"Failure analysis error: {d}")
        else:
            results.append(d)

    logger.info(f"Analyzed {len(results)} failed tasks")
    return results


def format_diagnoses_for_coordinator(diagnoses: list[FailureDiagnosis]) -> str:
    """Format diagnoses as context for the waypoint coordinator.

    This replaces raw agent_logs with structured, actionable analysis.
    """
    if not diagnoses:
        return ""

    lines = ["## Failure Analysis (per-task diagnoses)\n"]

    for d in diagnoses:
        lines.append(f"### {d.instance_id}")
        lines.append(f"**Root cause:** {d.root_cause}")

        if d.behaviors_to_fix:
            lines.append(f"**Distinct behaviors needed ({len(d.behaviors_to_fix)}):**")
            for b in d.behaviors_to_fix:
                lines.append(f"  - {b}")

        if d.what_swarm_missed:
            lines.append(f"**What the swarm missed:**")
            for m in d.what_swarm_missed:
                lines.append(f"  - {m}")

        if d.test_analysis:
            lines.append(f"**Test analysis:** {d.test_analysis}")

        if d.suggestion:
            lines.append(f"**Suggestion:** {d.suggestion}")

        lines.append(f"**Confidence:** {d.confidence}")
        lines.append("")

    return "\n".join(lines)


def diagnoses_to_json(diagnoses: list[FailureDiagnosis]) -> list[dict]:
    """Convert diagnoses to JSON-serializable dicts for saving."""
    return [
        {
            "instance_id": d.instance_id,
            "root_cause": d.root_cause,
            "what_swarm_missed": d.what_swarm_missed,
            "behaviors_to_fix": d.behaviors_to_fix,
            "test_analysis": d.test_analysis,
            "suggestion": d.suggestion,
            "confidence": d.confidence,
        }
        for d in diagnoses
    ]
