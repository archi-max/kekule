"""
Waypoint Coordinator -- the outer-loop brain of the self-improving swarm.

Analyzes epoch results (train with full logs, test with pass/fail only) and
produces three types of adjustments:
  1. lessons_text: coding/debugging lessons appended to the swarm system prompt
  2. oracle_adjustments: changes to oracle strategy composition
  3. composition: agent count and parallelism tuning
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------


@dataclass
class CompositionConfig:
    """Controls swarm shape -- adjustable by the coordinator each epoch."""

    num_coding_agents: int = 3
    num_oracle_rounds: int = 2
    oracle_parallelism: str = "parallel"  # "parallel" | "sequential"
    planner_guidance: str = ""


@dataclass
class CoordinatorOutput:
    """Full output from the waypoint coordinator."""

    lessons_text: str = ""
    oracle_adjustments: dict = field(default_factory=dict)
    composition: CompositionConfig = field(default_factory=CompositionConfig)
    analysis: str = ""
    train_score: float = 0.0
    test_score: float = 0.0


# ---------------------------------------------------------------------------
# Coordinator system prompt
# ---------------------------------------------------------------------------

COORDINATOR_SYSTEM_PROMPT = """
You are the Waypoint Coordinator for a self-improving agent swarm that solves
GitHub issues (SWE-bench). Your job is to analyze results from the latest epoch
and produce GENERIC improvements for the next epoch.

## What You Receive

1. **Train set results**: Full results including agent conversation logs, oracle
   check results, and evaluation outcomes. Use these to deeply analyze what
   went wrong and why.

2. **Test set results**: Only pass/fail counts (NO logs). This prevents you from
   overfitting to specific test tasks. You must generalize.

3. **Previous lessons**: Accumulated lessons from all prior epochs.

4. **Current oracle strategies**: What types of oracle agents are running.

5. **Current composition**: How many coding agents, oracle parallelism mode, etc.

## What You Must Output

Output a JSON object with these exact keys:

```json
{
  "lessons_text": "...",
  "oracle_adjustments": { ... },
  "composition": { ... },
  "analysis": "..."
}
```

### lessons_text (string, max ~500 words)
Generic coding and debugging lessons for the swarm agents. These get appended
to the swarm system prompt. They must be:
- GENERIC: apply to many tasks, not just ones you saw in the train set
- ACTIONABLE: "do X when Y" not "task Z failed because..."
- CONCISE: each lesson should be 1-2 sentences
- NON-REDUNDANT: don't repeat what's already in previous_lessons

Good examples:
- "When the issue describes a TypeError, check if the fix needs to handle both old and new API signatures."
- "Always run the full test module, not just a single test, to catch regressions."
- "For issues involving __repr__ or __str__, test with None, empty collections, and nested objects."

Bad examples:
- "django__django-14315 failed because the agent didn't check migrations." (too specific)
- "Try harder." (not actionable)

### oracle_adjustments (object) — THIS IS YOUR MOST IMPORTANT OUTPUT
The oracle system is the primary mechanism for improving the swarm. Better oracles
catch bugs before patches are submitted. Your oracle adjustments directly determine
whether the next epoch performs better.

Think deeply about what VERIFICATION CHECKS would have caught the failures you observed.
For each failed task, ask: "What test or check, if run against the patch, would have
told the swarm their fix was wrong BEFORE submission?"

Design oracles that:
- Catch the specific failure patterns you observed (e.g., missing edge cases, regressions)
- Can be expressed as pytest tests or bash checks
- Are generic enough to apply across different tasks

Keys are strategy names, values are dicts of fields to update.

Examples:
- Add new oracle type: `{"full_test_suite_runner": {"description": "Run the complete test module for any modified file, not just target tests", "agent_prompt": "Find all test files related to modified source files. Run the full test module. Report any failures.", "execution_mode": "bash", "__new__": true}}`
- Tune existing: `{"unit_test": {"prompt_addendum": "Always include a test for None/missing input and verify the return type matches the original method signature"}}`
- Adjust weight: `{"behavioral_assertion": {"weight": 1.5}}` (increase if it catches real issues)
- Enable/disable: `{"regression_check": {"enabled": false}}` (disable if it produces false positives)

ALWAYS suggest at least one oracle adjustment. If existing oracles are working well,
tune their prompts. If they're missing things, add a new oracle type that would
catch the pattern you observed.

### composition (object)
Adjustments to swarm shape.

```json
{
  "num_coding_agents": 3,
  "num_oracle_rounds": 2,
  "oracle_parallelism": "parallel",
  "planner_guidance": ""
}
```

- `num_coding_agents`: How many coding roles (2-5). Decrease if agents duplicate work,
  increase if tasks are complex and need more parallelism.
- `num_oracle_rounds`: Max inner-loop rounds (1-3). Increase if first-pass fixes are
  consistently wrong.
- `oracle_parallelism`: "parallel" (oracle roles in swarm) or "sequential" (after swarm).
  Switch to sequential if cost is too high.
- `planner_guidance`: Optional hints for the role planner. E.g., "Always include a
  dedicated test_runner role."

### analysis (string)
Your full analysis. This is logged but NOT injected into agent prompts. Be detailed:
- What patterns of failure did you observe?
- Which oracle strategies were effective vs. noisy?
- How did cost and turn counts distribute?
- What's your hypothesis for why test score differs from train score?

## CRITICAL Rules for lessons_text
- lessons_text MUST be 100% generic. NO task IDs, NO specific function/class/method names,
  NO specific test names, NO specific variable names from the tasks you analyzed.
- BAD: "The test for id_for_label expected None" (references a specific method)
- BAD: "For session-related fixes, cycle the session" (too narrow to one domain)
- GOOD: "When modifying a method that returns a value, always check what callers expect
  for missing/None cases — return a sensible default rather than raising an exception."
- GOOD: "When a test asserts inequality (assertNotEqual), the fix must produce a state
  change, not just a valid value."
- Each lesson should apply to ANY codebase, not just the ones you saw.
- If you catch yourself writing a specific class name, method name, or test name — STOP
  and rephrase as a general principle.
- Do NOT make lessons_text longer than ~500 words total
- Do NOT repeat lessons already in previous_lessons
- If train and test scores diverge, your lessons may be overfitting — make them MORE generic

## Turn Budget
You have up to 35 tool-call turns. Use them wisely:
- First, analyze the data provided in this prompt
- Use Read/Grep/Bash to explore eval reports, test outputs, or log files if you need more detail
- You MUST output the JSON object before your turns run out
- Reserve your last 3-5 turns for producing the final JSON output
- Better to produce partial analysis than no output at all

Output ONLY the JSON object, no other text
"""


# ---------------------------------------------------------------------------
# Input preparation
# ---------------------------------------------------------------------------


def _prepare_train_summary(
    train_results: list[dict],
    train_oracle_results: dict | None = None,
    max_log_chars: int = 3000,
) -> str:
    """Summarize train results with logs for the coordinator."""
    lines = ["## Train Set Results\n"]

    passed = sum(1 for r in train_results if r.get("resolved", False))
    total = len(train_results)
    rate = passed / total * 100 if total else 0
    lines.append(f"**Score: {passed}/{total} ({rate:.1f}%)**\n")

    for r in train_results:
        instance_id = r.get("instance_id", "unknown")
        resolved = r.get("resolved", False)
        mark = "PASS" if resolved else "FAIL"
        cost = r.get("cost_usd", 0)
        turns = r.get("num_turns", 0)

        lines.append(f"### [{mark}] {instance_id}")
        lines.append(f"- Cost: ${cost:.4f}, Turns: {turns}")
        lines.append(f"- Patch: {'yes' if r.get('model_patch') else 'no'}")

        if r.get("error"):
            lines.append(f"- Error: {r['error'][:200]}")

        # Include eval test breakdown (which specific tests passed/failed)
        eval_tests = r.get("eval_tests")
        if eval_tests:
            still_failing = eval_tests.get("fail_to_pass_still_failing", [])
            fixed = eval_tests.get("fail_to_pass_fixed", [])
            regressed = eval_tests.get("pass_to_pass_regressed", [])

            if fixed:
                lines.append(f"- Tests fixed ({len(fixed)}): {', '.join(fixed[:5])}")
            if still_failing:
                lines.append(f"- Tests STILL FAILING ({len(still_failing)}): {', '.join(still_failing[:5])}")
            if regressed:
                lines.append(f"- REGRESSIONS ({len(regressed)}): {', '.join(regressed[:5])}")
            if not still_failing and not regressed and fixed:
                lines.append("- All target tests pass, no regressions")

        # Include structured failure diagnosis (from failure analyst agent)
        diagnosis = r.get("failure_diagnosis")
        if diagnosis:
            lines.append(f"- **Root cause:** {diagnosis.get('root_cause', 'Unknown')}")
            missed = diagnosis.get("what_swarm_missed", [])
            if missed:
                lines.append(f"- **What swarm missed:** {'; '.join(missed[:5])}")
            behaviors = diagnosis.get("behaviors_to_fix", [])
            if behaviors:
                lines.append(f"- **Behaviors needed ({len(behaviors)}):** {'; '.join(behaviors[:5])}")
            test_analysis = diagnosis.get("test_analysis", "")
            if test_analysis:
                lines.append(f"- **Test analysis:** {test_analysis[:300]}")
            suggestion = diagnosis.get("suggestion", "")
            if suggestion:
                lines.append(f"- **Suggestion:** {suggestion[:300]}")
        elif not resolved and r.get("agent_logs"):
            # Fallback to raw agent logs if no diagnosis available
            log_text = r["agent_logs"][:max_log_chars]
            lines.append(f"- Key agent decisions:\n```\n{log_text}\n```")

        lines.append("")

    # Oracle results summary
    if train_oracle_results:
        lines.append("## Oracle Check Summary\n")
        for task_id, strategy_results in train_oracle_results.items():
            if isinstance(strategy_results, dict):
                for strategy_name, result in strategy_results.items():
                    if isinstance(result, dict):
                        mark = "PASS" if result.get("passed") else "FAIL"
                        lines.append(f"- [{mark}] {task_id} / {strategy_name}")
        lines.append("")

    return "\n".join(lines)


def _prepare_test_summary(test_results: list[dict]) -> str:
    """Summarize test results (pass/fail ONLY, no logs)."""
    passed = sum(1 for r in test_results if r.get("resolved", False))
    total = len(test_results)

    rate = passed / total * 100 if total else 0
    return (
        f"## Test Set Results\n\n"
        f"**Score: {passed}/{total} ({rate:.1f}%)**\n\n"
        f"(No individual task logs available for the test set. "
        f"Use only aggregate metrics for generalization.)\n"
    )


def _prepare_current_config(
    strategies: list | None = None,
    composition: CompositionConfig | None = None,
) -> str:
    """Summarize current oracle and composition config."""
    lines = ["## Current Configuration\n"]

    if strategies:
        lines.append("### Oracle Strategies")
        for s in strategies:
            status = "enabled" if s.enabled else "disabled"
            lines.append(
                f"- **{s.name}** [{status}] (mode={s.execution_mode}, "
                f"weight={s.weight}): {s.description}"
            )
            if s.prompt_addendum:
                lines.append(f"  Addendum: {s.prompt_addendum}")
        lines.append("")

    if composition:
        lines.append("### Composition")
        lines.append(f"- Coding agents: {composition.num_coding_agents}")
        lines.append(f"- Oracle rounds: {composition.num_oracle_rounds}")
        lines.append(f"- Oracle parallelism: {composition.oracle_parallelism}")
        if composition.planner_guidance:
            lines.append(f"- Planner guidance: {composition.planner_guidance}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main coordinator function
# ---------------------------------------------------------------------------


async def analyze_epoch(
    train_results: list[dict],
    test_results: list[dict],
    train_oracle_results: dict | None = None,
    previous_lessons: str = "",
    current_strategies: list | None = None,
    current_composition: CompositionConfig | None = None,
    epoch_num: int = 0,
    model: str = "claude-opus-4-5",
    max_turns: int = 35,
) -> CoordinatorOutput:
    """Run the waypoint coordinator agent to analyze an epoch.

    Args:
        train_results: Full results + logs for train tasks.
        test_results: Pass/fail only for test tasks (NO logs).
        train_oracle_results: Oracle check results for train tasks.
        previous_lessons: Accumulated lessons from prior epochs.
        current_strategies: Current oracle strategy configs.
        current_composition: Current composition config.
        epoch_num: Current epoch number.
        model: Model for the coordinator agent.
        max_turns: Max agent turns.

    Returns:
        CoordinatorOutput with lessons, oracle adjustments, and composition.
    """
    if current_composition is None:
        current_composition = CompositionConfig()

    # Build the prompt with all context
    train_summary = _prepare_train_summary(train_results, train_oracle_results)
    test_summary = _prepare_test_summary(test_results)
    config_summary = _prepare_current_config(current_strategies, current_composition)

    previous_section = ""
    if previous_lessons:
        previous_section = (
            f"## Previous Lessons (accumulated)\n\n{previous_lessons}\n\n"
            "Do NOT repeat these. Only add NEW lessons.\n"
        )

    prompt = f"""## Epoch {epoch_num} Analysis

{train_summary}

{test_summary}

{config_summary}

{previous_section}

Analyze the results and output a JSON object with lessons_text,
oracle_adjustments, composition, and analysis.
"""

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": COORDINATOR_SYSTEM_PROMPT,
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
                    f"[coordinator] Completed: turns={message.num_turns}, "
                    f"cost=${message.total_cost_usd or 0:.4f}, "
                    f"time={elapsed:.1f}s"
                )
    except Exception as e:
        logger.error(f"[coordinator] Failed: {e}")
        return CoordinatorOutput(
            analysis=f"Coordinator failed: {e}",
            train_score=_compute_score(train_results),
            test_score=_compute_score(test_results),
        )

    # Parse the coordinator's JSON output
    output = _parse_coordinator_output(last_text)
    output.train_score = _compute_score(train_results)
    output.test_score = _compute_score(test_results)

    logger.info(
        f"[coordinator] Epoch {epoch_num}: "
        f"train={output.train_score:.1%}, test={output.test_score:.1%}, "
        f"lessons={len(output.lessons_text)} chars, "
        f"oracle_adjustments={len(output.oracle_adjustments)} changes, "
        f"composition changes="
        f"agents={output.composition.num_coding_agents}, "
        f"rounds={output.composition.num_oracle_rounds}"
    )

    return output


def _compute_score(results: list[dict]) -> float:
    """Compute pass rate from results."""
    if not results:
        return 0.0
    passed = sum(1 for r in results if r.get("resolved", False))
    return passed / len(results)


def _parse_coordinator_output(text: str) -> CoordinatorOutput:
    """Extract and validate coordinator JSON output."""
    # Try to find a JSON object in the text
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not obj_match:
        logger.warning("[coordinator] No JSON found in output")
        return CoordinatorOutput(analysis=text)

    try:
        data = json.loads(obj_match.group())
    except json.JSONDecodeError:
        logger.warning("[coordinator] Failed to parse JSON output")
        return CoordinatorOutput(analysis=text)

    if not isinstance(data, dict):
        return CoordinatorOutput(analysis=text)

    # Extract lessons
    lessons = data.get("lessons_text", "")
    if not isinstance(lessons, str):
        lessons = str(lessons)

    # Extract oracle adjustments
    oracle_adj = data.get("oracle_adjustments", {})
    if not isinstance(oracle_adj, dict):
        oracle_adj = {}

    # Extract composition
    comp_data = data.get("composition", {})
    composition = CompositionConfig()
    if isinstance(comp_data, dict):
        if "num_coding_agents" in comp_data:
            val = comp_data["num_coding_agents"]
            if isinstance(val, int) and 1 <= val <= 6:
                composition.num_coding_agents = val
        if "num_oracle_rounds" in comp_data:
            val = comp_data["num_oracle_rounds"]
            if isinstance(val, int) and 1 <= val <= 5:
                composition.num_oracle_rounds = val
        if "oracle_parallelism" in comp_data:
            val = comp_data["oracle_parallelism"]
            if val in ("parallel", "sequential"):
                composition.oracle_parallelism = val
        if "planner_guidance" in comp_data:
            val = comp_data["planner_guidance"]
            if isinstance(val, str):
                composition.planner_guidance = val

    # Extract analysis
    analysis = data.get("analysis", "")
    if not isinstance(analysis, str):
        analysis = str(analysis)

    return CoordinatorOutput(
        lessons_text=lessons,
        oracle_adjustments=oracle_adj,
        composition=composition,
        analysis=analysis,
    )
